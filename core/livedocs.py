#!/usr/bin/env python3
"""livedocs.py — bind curated doc "Logic IDs" to codebase-memory graph nodes.

Generic core: anchors each Logic ID (parsed from a doc adapter's
Logic-to-Code tables) to a graph node by qualified_name, captures a self-owned
content_hash (+ the graph's optional fp/signature), and later detects drift.
Language- and doc-format-agnostic; the Drupal doc generators live in an adapter.

Subcommands:
  anchor  <sem_dir> <project>            resolve Logic IDs -> graph nodes, write .anchors.json
  check   <sem_dir> <project>            detect drift against the graph (exit 1 if any)
  enrich  <sem_dir> <project> <logic_id> live call graph for one Logic ID
  inject  <sem_dir> <project> [dir]      write a compact ## Codebase section into CLAUDE.md
"""
import json, os, re, subprocess, sys, time, datetime, pathlib, hashlib

# Path to the codebase-memory-mcp CLI. Overridable so the tool works when the
# binary lives elsewhere, and so tests can point it at a shim.
BIN = pathlib.Path(os.environ.get(
    "LIVEDOCS_CBM", pathlib.Path.home() / ".local/bin/codebase-memory-mcp"))

# A Logic ID token, e.g. FEAT-L1 (markdown emphasis stripped before matching).
LID_RE = re.compile(r"^[A-Z]+-L\d+$")
# A name the resolver can look up: identifiers plus dotted/namespaced callables
# (e.g. app.module.init, Foo\Bar). Dotted names are KEPT, not dropped, so
# behavior/callback rows are recorded (anchored or not_in_graph), never skipped.
NAME_RE = re.compile(r"^[A-Za-z_][\w.\\]*$")


class BackendError(RuntimeError):
    """The codebase-memory backend is missing or persistently unready."""


# The CLI backend lazy-loads a project's graph on first access and, under burst
# load, can return {"error": "... not found or not indexed"} while still EXITING
# 0 -- indistinguishable from a genuine miss. Retry that transient state with
# bounded backoff so identical runs agree; a persistent failure raises
# BackendError rather than silently poisoning anchors as not_in_graph (issue #6).
_COLD = "not found or not indexed"


def cbm(tool, payload, retries=5):
    delay, last = 0.25, ""
    for attempt in range(retries + 1):
        try:
            p = subprocess.run([str(BIN), "cli", tool, json.dumps(payload)],
                               capture_output=True, text=True)
        except FileNotFoundError:
            raise BackendError(f"codebase-memory backend not found at {BIN} "
                               f"(set LIVEDOCS_CBM to its path)")
        try:
            data = json.loads(p.stdout)
            transient = isinstance(data, dict) and _COLD in str(data.get("error", ""))
            last = data.get("error", "") if transient else last
        except json.JSONDecodeError:
            data, transient = {}, True
            last = (p.stderr or p.stdout or "no output").strip()[:200]
        if not transient:
            return data
        if attempt < retries:
            time.sleep(delay)
            delay = min(delay * 2, 2.0)
            continue
        raise BackendError(
            f"backend not ready for '{tool}' after {retries} retries: {last}")
    return {}


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# --- content-drift hashing (self-owned signal; the graph's fp is optional) ---
def normalize(src):
    # Only non-semantic formatting is folded: CRLF/CR->LF, per-line rstrip,
    # drop leading+trailing fully-blank lines. NO dedent, NO comment strip.
    src = (src or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [l.rstrip() for l in src.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def content_hash_of(src):
    n = normalize(src)
    return hashlib.sha256(n.encode()).hexdigest() if n else None


_ROOTS = {}  # project -> root_path (cached per process)


def project_root(project):
    # An explicit override always wins (and rescues file-fallback when the
    # backend can't supply a root_path, issue #7).
    override = os.environ.get("LIVEDOCS_ROOT")
    if override:
        return override
    if project not in _ROOTS:
        r = cbm("list_projects", {})
        match = next((p for p in r.get("projects", [])
                      if p.get("name") == project), None)
        root = (match or {}).get("root_path") or None
        if match is not None and not root:
            print(f"  warning: backend returned no root_path for '{project}'; "
                  f"file-fallback verification disabled "
                  f"(set LIVEDOCS_ROOT to the project dir to restore it)",
                  file=sys.stderr)
        _ROOTS[project] = root
    return _ROOTS[project]


def _is_comment(line):
    return line.lstrip().startswith(("//", "#", "*", "/*", "*/"))


def _declares(line, name):
    # True if `line` DECLARES/defines/assigns `name` (not a mere mention).
    # Excludes comments so prose like `// NOTE: MAX_N ...` can't pollute the hash.
    if _is_comment(line):
        return False
    n = re.escape(name)
    return bool(re.search(
        r"\b(?:const|class|interface|trait|enum|function|def|use)\s+[\w\\]*" + n + r"\b"
        r"|\bdefine\s*\(\s*['\"]" + n + r"['\"]"
        r"|(?:^|[^\w$])\$?" + n + r"\s*[:=]", line))


def file_fallback_hash(root, declared_file, name):
    # Non-graph verifier for symbols the graph doesn't model (PHP class constants,
    # traits...). Hash only the line(s) that DECLARE `name`, never incidental
    # mentions — an unrelated comment referencing the symbol must not flag drift.
    if not root or not declared_file or "*" in declared_file:
        return (None, None, None)
    if not NAME_RE.match(name or ""):
        return (None, None, None)
    p = pathlib.Path(root) / declared_file
    if not p.is_file():
        return (None, None, None)
    try:
        text = p.read_text()
    except OSError:
        return (None, None, None)
    pat = re.compile(r"\b" + re.escape(name) + r"\b")
    matched = [(i + 1, line) for i, line in enumerate(text.split("\n")) if pat.search(line)]
    if not matched:
        return (None, None, None)
    # Prefer declaration lines; fall back to non-comment mentions; never comments.
    decl = [(i, l) for i, l in matched if _declares(l, name)]
    chosen = decl or [(i, l) for i, l in matched if not _is_comment(l)]
    if not chosen:
        return (None, None, None)
    blob = "\n".join(line.strip() for _, line in chosen)
    return (content_hash_of(blob), [chosen[0][0], chosen[-1][0]], "file")


# Logic-to-Code tables are matched by SHAPE, not one positional layout. The
# Logic ID column is found by content (cells matching FEAT-L<n>, emphasis
# stripped); the File and Class/Function columns are found by HEADER LABEL,
# falling back to the legacy fixed positions (col 3 = file, col 4 = method) when
# a table carries no header row. This tolerates `**[ID]**` emphasis, extra
# columns, and 6/7-column variants (issues #1/#4/#5).
_FILE_KEYS = ("file",)
_METHOD_KEYS = ("function", "method", "class", "callable", "symbol", "implementation")


def clean_methods(cell):
    # Each `Class::method()` of a (possibly multi-method, backticked) cell, in
    # order. A cell may list several methods separated by commas.
    for part in cell.split(","):
        name = part.replace("`", "").split("(")[0].split("::")[-1].strip()
        name = re.sub(r"\s+.*$", "", name)  # drop trailing notes like "et al."
        if name:
            yield name


def clean_method(cell):
    # Back-compat: the first method of a multi-method cell.
    return next(clean_methods(cell), "")


def _row_cells(line):
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") else s
    return [c.strip() for c in s.split("|")]


def _row_lid(cell):
    # The Logic ID in a cell, with markdown emphasis/backticks/brackets removed.
    t = re.sub(r"[`*\[\]]", "", cell).strip()
    return t if LID_RE.match(t) else None


def _is_separator(cells):
    # A markdown header underline row: | :--- | ---: | ... |
    return any(cells) and all(c == "" or re.fullmatch(r":?-{2,}:?", c) for c in cells)


def _iter_table_rows(text):
    # Yield (logic_id, file_cell, method_cell) for every Logic-to-Code row in
    # any pipe-table in the document.
    block = []
    for line in text.split("\n"):
        if line.lstrip().startswith("|"):
            block.append(line)
            continue
        yield from _rows_from_block(block)
        block = []
    yield from _rows_from_block(block)


def _rows_from_block(block):
    rows = [_row_cells(l) for l in block]
    rows = [r for r in rows if not _is_separator(r)]
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    # Logic ID column = the column with the most LID-bearing cells.
    lid_col, best = 0, 0
    for c in range(ncols):
        cnt = sum(1 for r in rows if c < len(r) and _row_lid(r[c]))
        if cnt > best:
            best, lid_col = cnt, c
    if not best:
        return  # not a Logic-to-Code table
    # Header = first row without a LID in the LID column. Its labels locate the
    # File and Class/Function columns; absent a header, fall back to legacy
    # fixed positions (3rd col = file, 4th col = method).
    header = next((r for r in rows
                   if not (lid_col < len(r) and _row_lid(r[lid_col]))), None)
    file_col = method_col = None
    if header:
        for c, cell in enumerate(header):
            lab = cell.lower()
            if file_col is None and any(k in lab for k in _FILE_KEYS):
                file_col = c
            if method_col is None and any(k in lab for k in _METHOD_KEYS):
                method_col = c
    if file_col is None:
        file_col = min(2, ncols - 1)
    if method_col is None:
        method_col = min(3, ncols - 1)
    for r in rows:
        lid = _row_lid(r[lid_col]) if lid_col < len(r) else None
        if not lid:
            continue
        fcell = re.sub(r"[`*]", "", r[file_col]).strip() if file_col < len(r) else ""
        mcell = r[method_col] if method_col < len(r) else ""
        yield lid, fcell, mcell


def parse_specs(sem_dir):
    for md in sorted((sem_dir / "tech").glob("*.md")):
        text = md.read_text()
        feat = re.search(r"feature_id:\s*(\S+)", text)
        declared = re.search(r"logic_id_count:\s*(\d+)", text)
        seen = set()
        for lid, fpath, mcell in _iter_table_rows(text):
            methods = [m for m in clean_methods(mcell) if NAME_RE.match(m)]
            if not methods:
                continue  # no resolvable name in the row
            seen.add(lid)
            multi = len(methods) > 1
            for k, method in enumerate(methods, 1):
                # Each method in a multi-method cell becomes its own sub-anchor
                # (LID#1, LID#2) so drift is caught when ANY listed method moves.
                yield dict(logic_id=lid,
                           anchor_id=f"{lid}#{k}" if multi else lid,
                           feature=feat.group(1) if feat else "",
                           spec=f"tech/{md.name}",
                           declared_file=fpath.strip(), method=method)
        if declared and int(declared.group(1)) != len(seen):
            print(f"  warning: {md.name} declares logic_id_count="
                  f"{declared.group(1)} but {len(seen)} Logic IDs parsed",
                  file=sys.stderr)


def count_logic_ids(sem_dir):
    # Distinct Logic IDs (not method sub-anchors) across all specs.
    return len({(a["spec"], a["logic_id"]) for a in parse_specs(sem_dir)})


def declared_counts(sem_dir):
    # The logic_id_count each spec declares in frontmatter, keyed by spec path.
    out = {}
    for md in sorted((sem_dir / "tech").glob("*.md")):
        m = re.search(r"logic_id_count:\s*(\d+)", md.read_text())
        if m:
            out[f"tech/{md.name}"] = int(m.group(1))
    return out


# Logic anchors can point to any symbol kind, not just methods.
ANCHORABLE = ("Method", "Function", "Class", "Interface", "Variable")


def resolve(project, method, declared_file):
    payload = {"project": project, "name_pattern": f"^{re.escape(method)}$"}
    if declared_file:
        payload["file_pattern"] = pathlib.PurePath(declared_file).name
    r = cbm("search_graph", payload)
    hits = [n for n in r.get("results", []) if n.get("label") in ANCHORABLE]
    if len(hits) == 1:
        return hits[0], "ok"
    if len(hits) > 1:
        # disambiguate by callable kinds first, then by declared file basename
        callable_hits = [n for n in hits if n.get("label") in ("Method", "Function")]
        pool = callable_hits or hits
        if declared_file:
            base = pathlib.PurePath(declared_file).name
            # basename EQUALITY on file_path (live key; `file` is a stale fallback).
            # search_graph's file_pattern is itself a basename SUBSTRING match, so it
            # over-returns; equality filters the extras back out.
            narrowed = [n for n in pool
                        if pathlib.PurePath(n.get("file_path") or n.get("file") or "").name == base]
            if narrowed:
                pool = narrowed
            if len(pool) > 1:
                # same-basename overload: tiebreak on parent_class == declared class
                cls = pathlib.PurePath(declared_file).stem
                byclass = [n for n in pool
                           if (n.get("parent_class") or "").rsplit(".", 1)[-1] == cls]
                if byclass:
                    pool = byclass
        if len(pool) == 1:
            return pool[0], "ok"
        return None, "ambiguous"
    # nothing under any anchorable label: search WITHOUT the file filter to tell
    # "moved" (exists elsewhere) from "not modelled / absent"
    if declared_file:
        wide = cbm("search_graph", {"project": project, "name_pattern": f"^{re.escape(method)}$"})
        if any(n.get("label") in ANCHORABLE for n in wide.get("results", [])):
            return None, "moved"
    return None, "not_in_graph"


def snippet(project, qn):
    return cbm("get_code_snippet", {"project": project, "qualified_name": qn})


def cmd_anchor(sem_dir, project):
    out = {"schema": 2, "project": project, "generated_at": now(), "anchors": []}
    root = project_root(project)
    for a in parse_specs(sem_dir):
        node, st = resolve(project, a["method"], a["declared_file"])
        if node:
            s = snippet(project, node["qualified_name"])
            a.update(qualified_name=node["qualified_name"], fp=s.get("fp"),
                     signature=s.get("signature"),
                     content_hash=content_hash_of(s.get("source")),
                     hash_source="snippet" if s.get("source") else None,
                     start_end=[s.get("start_line"), s.get("end_line")],
                     parent_class=node.get("parent_class"),
                     status="ok", verified_at=now())
        else:
            ch = se = hs = None
            if st == "not_in_graph":
                ch, se, hs = file_fallback_hash(root, a["declared_file"], a["method"])
            a.update(qualified_name=None, fp=None, signature=None,
                     content_hash=ch, hash_source=hs, start_end=se,
                     parent_class=None, status=st, verified_at=now())
        out["anchors"].append(a)
    # coverage: declared (frontmatter) vs anchored (distinct Logic IDs that
    # produced >=1 anchor row), per spec. `check` uses this to tell code drift
    # apart from a broken pipeline / under-coverage (issue #2).
    declared = declared_counts(sem_dir)
    anchored_by_spec = {}
    for x in out["anchors"]:
        anchored_by_spec.setdefault(x["spec"], set()).add(x["logic_id"])
    out["coverage"] = [
        {"spec": spec, "declared": d, "anchored": len(anchored_by_spec.get(spec, ()))}
        for spec, d in sorted(declared.items())]
    out["declared_logic_ids"] = sum(declared.values())
    out["anchored_logic_ids"] = len({(x["spec"], x["logic_id"]) for x in out["anchors"]})
    (sem_dir / ".anchors.json").write_text(json.dumps(out, indent=2))
    n = len(out["anchors"])
    by = {}
    for x in out["anchors"]:
        by[x["status"]] = by.get(x["status"], 0) + 1
    print(f"wrote {n} anchors -> {sem_dir/'.anchors.json'}")
    print("  status:", ", ".join(f"{k}={v}" for k, v in sorted(by.items())))


def load_anchors(sem_dir, project):
    # Read the sidecar, or exit with a hint (not a traceback) if it is missing.
    sidecar = sem_dir / ".anchors.json"
    if not sidecar.is_file():
        print(f"no baseline at {sidecar} - "
              f"run `livedocs anchor {sem_dir} {project}` first", file=sys.stderr)
        sys.exit(2)
    return json.loads(sidecar.read_text())


def cmd_check(sem_dir, project):
    data = load_anchors(sem_dir, project)
    root = project_root(project)
    drift = []
    for a in data["anchors"]:
        # 1. status gate: re-verify file-fallback anchors against disk; carry the rest.
        if a["status"] != "ok":
            if a["status"] == "not_in_graph" and a.get("hash_source") == "file":
                ch, _, _ = file_fallback_hash(root, a["declared_file"], a["method"])
                if ch is None:
                    drift.append((a, "gone"))
                elif ch != a.get("content_hash"):
                    drift.append((a, "changed"))
            else:
                drift.append((a, a["status"]))
            continue
        # 2. existence
        s = snippet(project, a["qualified_name"])
        if not s.get("qualified_name"):
            moved, _ = resolve(project, a["method"], "")
            drift.append((a, "moved" if moved else "gone")); continue
        # 3. signature (only when both present+nonempty)
        sig_a, sig_b = a.get("signature"), s.get("signature")
        if sig_a and sig_b and sig_a != sig_b:
            drift.append((a, "signature_changed")); continue
        # 4. content_hash is authoritative when present (catches fp-null blind spot).
        #    A vanished source can no longer corroborate the stored hash -> drift.
        if a.get("content_hash") is not None:
            now_hash = content_hash_of(s.get("source")) if s.get("source") is not None else None
            if now_hash != a["content_hash"]:
                drift.append((a, "changed")); continue
        # 5. legacy fp corroborator (schema<2 / unhashable anchor only)
        else:
            if s.get("fp") != a.get("fp"):
                drift.append((a, "changed"))
    # Coverage problems are distinct from code drift: 0 anchored while specs
    # declare Logic IDs means the pipeline is broken (e.g. unparseable specs);
    # fewer anchored than declared per spec is under-coverage (issue #2).
    declared_total = data.get("declared_logic_ids", 0)
    anchored_total = data.get(
        "anchored_logic_ids",
        len({(a["spec"], a["logic_id"]) for a in data["anchors"]}))
    coverage = []
    if declared_total and anchored_total == 0:
        coverage.append((f"0 of {declared_total} declared Logic IDs anchored",
                         "pipeline broken - specs unparseable? re-run `anchor`"))
    for cov in data.get("coverage", []):
        if cov["anchored"] < cov["declared"]:
            coverage.append((f"{cov['anchored']} of {cov['declared']} anchored",
                             cov["spec"]))

    for a, st in sorted(drift, key=lambda x: x[1]):
        name = a.get("anchor_id") or a["logic_id"]
        print(f"  {st.upper():18} {name:12} {a['method']:32} {a['spec']}")
    for detail, where in coverage:
        print(f"  {'UNDER-COVERED':18} {detail:24} {where}")
    summary = f"\n{len(drift)} stale / {len(data['anchors'])} anchors"
    if coverage:
        summary += f"; {len(coverage)} coverage issue(s)"
    print(summary)
    # 0 = clean, 1 = drift, 2 = coverage collapse / under-coverage (takes
    # priority: incomplete coverage means the drift result is not trustworthy).
    sys.exit(2 if coverage else (1 if drift else 0))


def cmd_enrich(sem_dir, project, logic_id):
    data = load_anchors(sem_dir, project)
    a = next((x for x in data["anchors"]
              if logic_id in (x["logic_id"], x.get("anchor_id"))), None)
    if a is None:
        sys.exit(f"no anchor with logic_id {logic_id} in {sem_dir/'.anchors.json'}")
    print(json.dumps(cbm("trace_path", {"project": project, "function_name": a["method"],
                                        "direction": "both", "depth": 2}), indent=2))


CLAUDE_MD_START = "<!-- livedocs:start -->"
CLAUDE_MD_END = "<!-- livedocs:end -->"


def _spec_meta(sem_dir):
    # Per-tech-spec (code, name, modules) from filename + frontmatter, in file order.
    out = []
    for md in sorted((sem_dir / "tech").glob("*.md")):
        text = md.read_text()
        stem = md.stem  # e.g. ORD_01_Orders
        m = re.match(r"^([A-Z]+)_", stem)
        code = m.group(1) if m else stem
        name = re.sub(r"^[A-Z]+_\d+_", "", stem).replace("_", " ")
        mods = []
        mm = re.search(r"^module:\s*(.+)$", text, re.M)
        if mm:
            mods = [p.strip() for p in mm.group(1).split(",")
                    if p.strip() and "(contrib)" not in p]
        out.append((code, name, mods))
    return out


def _codebase_section(sem_dir, rel):
    # Compose a compact, framework-agnostic `## Codebase` section. Lines that name
    # adapter-specific files (a top index, the structural index) are emitted only
    # when those files actually exist, so the core stays generic.
    specs = _spec_meta(sem_dir)
    logic_ids = count_logic_ids(sem_dir)
    modules = sorted({m for _, _, mods in specs for m in mods})

    body = [f"- {len(specs)} features, {logic_ids} Logic IDs"
            + (f" across {len(modules)} modules" if modules else "")]
    index = next((f for f in ("00_BUSINESS_INDEX.md", "FEATURE_MAP.md")
                  if (sem_dir / f).is_file()), None)
    if index:
        body.append(f"- Start at `{rel}/{index}` for the feature registry")
    body.append(f"- Tech specs (one file per feature, each with a Logic-to-Code "
                f"table): `{rel}/tech/*.md`")
    if (sem_dir / "structural").is_dir():
        body.append(f"- Structural index (what exists, generated from code): "
                    f"`{rel}/structural/*.md`")
    body.append("- A Logic ID such as `ORD-L1` names one method; find it in the "
                f"`{rel}/tech/{{CODE}}_*.md` file for its feature")
    body.append("- Run `/livedocs-check` to confirm the docs still match the code")

    rows = [f"{c}:{n}" for c, n, _ in specs]
    listing = "\n".join("|".join(rows[i:i + 6]) for i in range(0, len(rows), 6))

    return (f"## Codebase\n\n"
            f"This project has living documentation under `{rel}/`. Read it before\n"
            f"exploring the code by hand; it ties each feature to the methods that\n"
            f"implement it, and `/livedocs-check` reports when it drifts.\n\n"
            + "\n".join(body) + "\n\n"
            + "Features: " + listing + "\n")


def cmd_inject(sem_dir, project, project_dir=None):
    if not list((sem_dir / "tech").glob("*.md")):
        print(f"  no tech specs in {sem_dir/'tech'} - skipping CLAUDE.md injection")
        return
    # CLAUDE.md sits at the project root: an explicit dir wins, then the graph's
    # known root, then the docs dir's grandparent (the docs/<X>/ convention).
    root = pathlib.Path(project_dir or project_root(project)
                        or sem_dir.resolve().parent.parent)
    rel = os.path.relpath(sem_dir.resolve(), root.resolve())
    claude_md = root / "CLAUDE.md"

    section = _codebase_section(sem_dir, rel)
    block = f"{CLAUDE_MD_START}\n{section}{CLAUDE_MD_END}\n"

    if not claude_md.is_file():
        claude_md.write_text(f"# {root.name}\n\n{block}")
        action = "created CLAUDE.md"
    else:
        text = claude_md.read_text()
        if CLAUDE_MD_START in text and CLAUDE_MD_END in text:
            text = re.sub(re.escape(CLAUDE_MD_START) + r".*?"
                          + re.escape(CLAUDE_MD_END) + r"\n?",
                          lambda _: block, text, count=1, flags=re.S)
            action = "updated CLAUDE.md Codebase section"
        elif re.search(r"^## Codebase\b", text, re.M):
            # Adopt a pre-existing unmarked section: replace it (to next ## or EOF)
            # and wrap the replacement in markers so future runs are clean.
            text = re.sub(r"^## Codebase\b.*?(?=^## |\Z)",
                          lambda _: block + "\n", text, count=1, flags=re.S | re.M)
            action = "wrapped existing Codebase section in livedocs markers"
        else:
            sep = "" if text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
            text = text + sep + block
            action = "appended Codebase section to CLAUDE.md"
        claude_md.write_text(text)
    specs = list((sem_dir / "tech").glob("*.md"))
    logic_ids = count_logic_ids(sem_dir)
    print(f"  {action} ({len(specs)} features, {logic_ids} Logic IDs) -> {claude_md}")


USAGE = ("usage:\n"
         "  livedocs anchor <sem_dir> <project>\n"
         "  livedocs check  <sem_dir> <project>\n"
         "  livedocs inject <sem_dir> <project> [project_dir]\n"
         "  livedocs enrich <sem_dir> <project> <logic_id>")


def main(args):
    if len(args) < 3:
        print(USAGE, file=sys.stderr)
        return 2
    cmd, sem, proj = args[0], pathlib.Path(args[1]), args[2]
    if cmd == "anchor":
        cmd_anchor(sem, proj)
    elif cmd == "check":
        cmd_check(sem, proj)
    elif cmd == "enrich":
        if len(args) < 4:
            print(USAGE, file=sys.stderr)
            return 2
        cmd_enrich(sem, proj, args[3])
    elif cmd == "inject":
        cmd_inject(sem, proj, args[3] if len(args) > 3 else None)
    else:
        print(f"unknown command: {cmd}\n{USAGE}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BackendError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(3)
