#!/usr/bin/env python3
"""cbm_bridge.py — bind curated doc "Logic IDs" to codebase-memory graph nodes.

Generic bridge core: anchors each Logic ID (parsed from a doc adapter's
Logic-to-Code tables) to a graph node by qualified_name, captures a self-owned
content_hash (+ the graph's optional fp/signature), and later detects drift.
Language- and doc-format-agnostic; the Drupal doc generators live in an adapter.

Subcommands:
  anchor  <sem_dir> <project>            resolve Logic IDs -> graph nodes, write .anchors.json
  check   <sem_dir> <project>            detect drift against the graph (exit 1 if any)
  enrich  <sem_dir> <project> <logic_id> live call graph for one Logic ID
"""
import json, re, subprocess, sys, datetime, pathlib, hashlib

BIN = pathlib.Path.home() / ".local/bin/codebase-memory-mcp"


def cbm(tool, payload):
    p = subprocess.run([str(BIN), "cli", tool, json.dumps(payload)],
                       capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
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
    if project not in _ROOTS:
        r = cbm("list_projects", {})
        _ROOTS[project] = next((p.get("root_path") for p in r.get("projects", [])
                                if p.get("name") == project), None)
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
    if not re.match(r"^[A-Za-z_]\w*$", name or ""):
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


# Logic-to-Code rows: | MCP-L15 | description | `file` | `Class::method()` | complexity |
# The method column is captured whole (it may list several `Class::method()`
# separated by commas, or contain backticks) and cleaned in parse_specs; a
# backtick-bounded capture would silently drop multi-method rows.
ROW = re.compile(r"^\|\s*([A-Z]+-L\d+)\s*\|[^|]*\|\s*`?([^`|]+?)`?\s*\|\s*([^|]+?)\s*\|", re.M)


def clean_method(cell):
    # First `Class::method()` of a (possibly multi-method, backticked) cell.
    first = cell.replace("`", "").split(",")[0]
    name = first.split("(")[0].split("::")[-1].strip()
    return re.sub(r"\s+.*$", "", name)  # drop trailing notes like "et al."


def parse_specs(sem_dir):
    for md in sorted((sem_dir / "tech").glob("*.md")):
        text = md.read_text()
        feat = re.search(r"feature_id:\s*(\S+)", text)
        declared = re.search(r"logic_id_count:\s*(\d+)", text)
        n = 0
        for lid, fpath, method in ROW.findall(text):
            method = clean_method(method)
            if not re.match(r"^[A-Za-z_]\w*$", method):
                continue  # skip class-attribute / non-method rows
            n += 1
            yield dict(logic_id=lid, feature=feat.group(1) if feat else "",
                       spec=f"tech/{md.name}", declared_file=fpath.strip(), method=method)
        if declared and int(declared.group(1)) != n:
            print(f"  warning: {md.name} declares logic_id_count="
                  f"{declared.group(1)} but {n} method rows parsed",
                  file=sys.stderr)


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
    (sem_dir / ".anchors.json").write_text(json.dumps(out, indent=2))
    n = len(out["anchors"])
    by = {}
    for x in out["anchors"]:
        by[x["status"]] = by.get(x["status"], 0) + 1
    print(f"wrote {n} anchors -> {sem_dir/'.anchors.json'}")
    print("  status:", ", ".join(f"{k}={v}" for k, v in sorted(by.items())))


def cmd_check(sem_dir, project):
    data = json.loads((sem_dir / ".anchors.json").read_text())
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
    for a, st in sorted(drift, key=lambda x: x[1]):
        print(f"  {st.upper():18} {a['logic_id']:10} {a['method']:32} {a['spec']}")
    print(f"\n{len(drift)} stale / {len(data['anchors'])} anchors")
    sys.exit(1 if drift else 0)


def cmd_enrich(sem_dir, project, logic_id):
    a = next(x for x in json.loads((sem_dir / ".anchors.json").read_text())["anchors"]
             if x["logic_id"] == logic_id)
    print(json.dumps(cbm("trace_path", {"project": project, "function_name": a["method"],
                                        "direction": "both", "depth": 2}), indent=2))


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd, sem, proj = args[0], pathlib.Path(args[1]), args[2]
    if cmd == "anchor":
        cmd_anchor(sem, proj)
    elif cmd == "check":
        cmd_check(sem, proj)
    elif cmd == "enrich":
        cmd_enrich(sem, proj, args[3])
    else:
        sys.exit(f"unknown command: {cmd}")
