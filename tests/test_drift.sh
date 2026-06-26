#!/usr/bin/env bash
# test_drift.sh — end-to-end drift proof for livedocs.py.
#
# Proves content-drift detection on:
#   - an fp-NULL short method  (the self-owned content_hash fallback)
#   - a longer method          (content_hash; also fp-null in a small fixture)
#   - non-graph file-fallback symbols (class constants via declaration hashing)
#   - signature precedence over content
#   - normalization negative controls (trailing-whitespace edit = NO false drift)
#   - declaration-only fallback (unrelated comment mention = NO false drift)
#   - CLAUDE.md injection (S0b: create, idempotent re-run, content preserved)
# Plus an optional, non-destructive sub-test (set OB_DOCS and OB_PROJECT) that
# exercises the legacy fp corroborator branch (sidecar poison) on a real,
# already-indexed project and reports the disambiguation delta.
#
# Stdlib + the cbm CLI only. Cleans up in a trap. Exits nonzero on any failure.
set -u

SCRATCH="$(mktemp -d)"
FIX=$SCRATCH/drift_fixture
SEM=$FIX/docs/semantic
OB_SEM=$SCRATCH/ob_sem
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE="$REPO_ROOT/core/livedocs.py"
CBM="${CBM:-$HOME/.local/bin/codebase-memory-mcp}"
OB_DOCS="${OB_DOCS:-}"        # docs dir of a real, already-indexed project (optional)
OB="${OB_PROJECT:-}"          # its codebase-memory-mcp project name
ANCHORS=$SEM/.anchors.json

PROJ=""        # captured after first index
PASS=0; FAIL=0

cleanup() {
  [ -n "$PROJ" ] && "$CBM" cli delete_project "{\"project\":\"$PROJ\"}" >/dev/null 2>&1
  rm -rf "$SCRATCH"
}
trap cleanup EXIT

ok()  { PASS=$((PASS+1)); echo "PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL: $1"; }
# Robust assertion primitives — no eval, no nested-quote gymnastics.
eq()     { if [ "$2" = "$3" ];   then ok "$1"; else bad "$1 (got '$2' want '$3')"; fi; }
truthy() { if [ -n "$2" ] && [ "$2" != None ] && [ "$2" != False ]; then ok "$1"; else bad "$1 (got '$2')"; fi; }
grepq()  { if printf '%s\n' "$3" | grep -q "$2"; then ok "$1"; else bad "$1 (pattern '$2' absent)"; fi; }
ngrepq() { if printf '%s\n' "$3" | grep -q "$2"; then bad "$1 (pattern '$2' unexpectedly present)"; else ok "$1"; fi; }

# field <logic_id> <key>   prints anchor[key], or the top-level schema for @schema
field() {
  python3 - "$ANCHORS" "$1" "$2" <<'PY'
import json, sys
data = json.load(open(sys.argv[1])); lid, key = sys.argv[2], sys.argv[3]
if key == "@schema":
    print(data.get("schema")); raise SystemExit
a = next((x for x in data["anchors"] if x["logic_id"] == lid), None)
v = (a or {}).get(key)
print("" if v is None else v)
PY
}

# --- helpers -----------------------------------------------------------------
poll_ready() {
  for _ in $(seq 1 60); do
    st=$("$CBM" cli index_status "{\"project\":\"$PROJ\"}" 2>/dev/null \
         | python3 -c 'import json,sys;print(json.load(sys.stdin).get("status",""))' 2>/dev/null)
    [ "$st" = "ready" ] && return 0
    sleep 1
  done
  return 1
}

reindex() {
  # forced clean re-index: delete + index + poll to ready (determinism)
  "$CBM" cli delete_project "{\"project\":\"$PROJ\"}" >/dev/null 2>&1
  "$CBM" cli index_repository "{\"repo_path\":\"$FIX\"}" >/dev/null 2>&1
  poll_ready
}

reanchor() { reindex && python3 "$BRIDGE" anchor "$SEM" "$PROJ" >/dev/null; }

write_fixture() {
  rm -rf "$FIX"
  mkdir -p "$FIX/src" "$SEM/tech"

  cat > "$FIX/src/Calc.php" <<'PHP'
<?php
namespace Fixture;

class Calc {
  /**
   * Short op. (this docblock is NOT part of get_code_snippet.source)
   */
  public function shortFn(int $n): int {
    return $n + 1;
  }

  /**
   * Long op docblock.
   */
  public function longFn(int $n): string {
    $acc = 0;
    for ($i = 0; $i < $n; $i++) {
      if ($i % 2 === 0) {
        $acc += $i;
      } else {
        $acc -= $i;
      }
    }
    if ($acc < 0) {
      $acc = -$acc;
    }
    $out = "result:" . $acc;
    return $out;
  }
}
PHP

  cat > "$FIX/src/util.php" <<'PHP'
<?php
namespace Fixture;

function helperFn(int $n): int {
  return $n * 3;
}
PHP

  cat > "$FIX/constants.php" <<'PHP'
<?php
namespace Fixture;

const MAX_N = 1000;
const TABLE = [1, 2, 3];
PHP

  cat > "$SEM/tech/CALC_01.md" <<'MD'
---
feature_id: CALC
---

# Calc feature

## Logic-to-Code

| Logic ID | Description | File | Method | Cplx |
| CALC-L1 | short op | `src/Calc.php` | `Calc::shortFn()` | 1 |
| CALC-L2 | long op  | `src/Calc.php` | `Calc::longFn()`  | 5 |
| CALC-L3 | helper   | `src/util.php` | `helperFn()`      | 1 |
| CALC-L4 | max      | `constants.php` | `MAX_N`          | 1 |
| CALC-L5 | table    | `constants.php` | `TABLE`          | 1 |
MD
}

# --- S0a: parser regression (multi-method cell + count reconciliation) ------
# A Logic-to-Code row whose Function/Method column lists several `Class::method()`
# separated by commas must parse to the FIRST method, not be silently dropped;
# and a logic_id_count that disagrees with the parsed rows must emit a warning.
echo "=== S0a: parser handles multi-method rows + count mismatch ==="
PT="$(mktemp -d)"; mkdir -p "$PT/tech"
cat > "$PT/tech/PARSE_01_Parse.md" <<'MD'
---
feature_id: PARSE
logic_id_count: 3
---
| Logic ID | Description | File | Function/Method | Complexity |
|----------|-------------|------|-----------------|------------|
| PARSE-L1 | single method        | `src/A.php` | `A::alpha()` | low |
| PARSE-L2 | two methods, one cell | `src/A.php` | `A::beta()`, `A::gamma()` | low |
| PARSE-L3 | bare function         | `src/A.php` | `delta()` | low |
MD
pout=$(python3 - "$PT" "$BRIDGE" <<'PY' 2>&1
import sys, importlib.util, pathlib
spec=importlib.util.spec_from_file_location("c", sys.argv[2]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
print("METHODS:", ",".join(r["method"] for r in c.parse_specs(pathlib.Path(sys.argv[1]))))
PY
)
echo "$pout"
grepq "S0a multi-method row parsed (first=beta)" 'METHODS:.*beta' "$pout"
grepq "S0a bare function parsed (delta)"         'METHODS:.*delta' "$pout"
sed -i 's/logic_id_count: 3/logic_id_count: 4/' "$PT/tech/PARSE_01_Parse.md"
pwarn=$(python3 - "$PT" "$BRIDGE" <<'PY' 2>&1 1>/dev/null
import sys, importlib.util, pathlib
spec=importlib.util.spec_from_file_location("c", sys.argv[2]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
list(c.parse_specs(pathlib.Path(sys.argv[1])))
PY
)
grepq "S0a count-mismatch warning emitted" 'declares logic_id_count=4' "$pwarn"
rm -rf "$PT"

# --- S0c: parser format flexibility (emphasis, extra/7 columns, bare 4-col) --
# Issue #1: columns are located by HEADER LABEL and markdown emphasis is stripped
# from the ID cell, so one positional layout is not assumed.
echo "=== S0c: parser tolerates emphasis + extra/variant columns ==="
PT="$(mktemp -d)"; mkdir -p "$PT/tech"
cat > "$PT/tech/FMT_01.md" <<'MD'
---
feature_id: FMT
---
| Logic ID | Business Rule | Component Type | File Path | Class/Function | Complexity |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **[FMT-L1]** | rule | Service | `src/A.php` | `A::doIt()` | Low |
| **FMT-L2**   | rule | Service | `src/B.php` | `B::go()` | Low |
MD
cat > "$PT/tech/BARE_01.md" <<'MD'
---
feature_id: BARE
---
| Logic ID | Description | File | Method |
| BARE-L1 | x | `src/C.php` | `C::run()` |
MD
cat > "$PT/tech/SEV_01.md" <<'MD'
---
feature_id: SEV
---
| Logic ID | Business Rule | Component Type | File Path | Class/Function | Complexity | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| SEV-L1 | r | Svc | `src/D.php` | `D::a()` | Low | n/a |
MD
cdump=$(python3 - "$PT" "$BRIDGE" <<'PY' 2>/dev/null
import sys, importlib.util, pathlib
spec=importlib.util.spec_from_file_location("c", sys.argv[2]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
for r in c.parse_specs(pathlib.Path(sys.argv[1])):
    print(f"{r['anchor_id']}|{r['declared_file']}|{r['method']}")
PY
)
echo "$cdump"
grepq "S0c emphasis [ID] parsed (right file+method)" 'FMT-L1|src/A.php|doIt' "$cdump"
grepq "S0c emphasis **ID** parsed"                   'FMT-L2|src/B.php|go'   "$cdump"
grepq "S0c bare 4-col still parses (no regression)"  'BARE-L1|src/C.php|run' "$cdump"
grepq "S0c 7-column variant parses"                  'SEV-L1|src/D.php|a'    "$cdump"
rm -rf "$PT"

# --- S0d: multi-method cell -> one sub-anchor per method (issue #4) ----------
echo "=== S0d: multi-method cell -> one sub-anchor per method ==="
PT="$(mktemp -d)"; mkdir -p "$PT/tech"
cat > "$PT/tech/MM_01.md" <<'MD'
---
feature_id: MM
---
| Logic ID | Description | File | Class/Function | Cplx |
| :--- | :--- | :--- | :--- | :--- |
| MM-L1 | two methods | `src/A.php` | `A::foo()`, `A::bar()` | Low |
| MM-L2 | one method  | `src/A.php` | `A::solo()` | Low |
MD
ddump=$(python3 - "$PT" "$BRIDGE" <<'PY' 2>/dev/null
import sys, importlib.util, pathlib
spec=importlib.util.spec_from_file_location("c", sys.argv[2]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
for r in c.parse_specs(pathlib.Path(sys.argv[1])):
    print(f"{r['logic_id']}|{r['anchor_id']}|{r['method']}")
PY
)
echo "$ddump"
grepq "S0d multi-method first sub-anchor"  'MM-L1|MM-L1#1|foo' "$ddump"
grepq "S0d multi-method second sub-anchor" 'MM-L1|MM-L1#2|bar' "$ddump"
grepq "S0d single method stays bare"       'MM-L2|MM-L2|solo'  "$ddump"
rm -rf "$PT"

# --- S0e: dotted/namespaced symbol name is parsed, not dropped (issue #5) ----
echo "=== S0e: dotted/namespaced symbol name parsed, no spurious warning ==="
PT="$(mktemp -d)"; mkdir -p "$PT/tech"
cat > "$PT/tech/JS_01.md" <<'MD'
---
feature_id: JS
logic_id_count: 1
---
| Logic ID | Business Rule | File Path | Class/Function | Complexity |
| :--- | :--- | :--- | :--- | :--- |
| JS-L1 | Init widget | `js/app.behaviors.js` | `App.behaviors.initWidget` | Low |
MD
edump=$(python3 - "$PT" "$BRIDGE" <<'PY' 2>&1
import sys, importlib.util, pathlib
spec=importlib.util.spec_from_file_location("c", sys.argv[2]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
for r in c.parse_specs(pathlib.Path(sys.argv[1])):
    print(f"{r['anchor_id']}|{r['method']}")
PY
)
echo "$edump"
grepq  "S0e dotted JS behavior parsed"        'JS-L1|App.behaviors.initWidget' "$edump"
ngrepq "S0e no spurious count warning for JS" 'declares logic_id_count' "$edump"
rm -rf "$PT"

# --- S0f: check exit codes for coverage collapse / under-coverage (issue #2) --
# 0 = clean, 1 = drift, 2 = coverage collapse / under-coverage. project_root is
# stubbed so this is hermetic (no backend): crafted sidecars drive the verdict.
echo "=== S0f: check exit codes for coverage collapse / under-coverage ==="
CT="$(mktemp -d)"
check_exit() {  # <sidecar-json> -> prints command output + 'EXIT <code>'
  printf '%s' "$1" > "$CT/.anchors.json"
  python3 - "$CT" "$BRIDGE" <<'PY' 2>&1
import sys, importlib.util, pathlib
spec = importlib.util.spec_from_file_location("c", sys.argv[2])
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
c.project_root = lambda p: None          # no backend
try:
    c.cmd_check(pathlib.Path(sys.argv[1]), "p")
except SystemExit as e:
    print("EXIT", e.code)
PY
}
collapse=$(check_exit '{"schema":2,"project":"p","anchors":[],"coverage":[{"spec":"tech/X.md","declared":5,"anchored":0}],"declared_logic_ids":5,"anchored_logic_ids":0}')
echo "$collapse"
grepq "S0f collapse exits 2"  '^EXIT 2$' "$collapse"
grepq "S0f collapse message"  '0 of 5 declared Logic IDs anchored' "$collapse"
under=$(check_exit '{"schema":2,"project":"p","anchors":[],"coverage":[{"spec":"tech/Y.md","declared":10,"anchored":6}],"declared_logic_ids":10,"anchored_logic_ids":6}')
echo "$under"
grepq "S0f under-coverage exits 2"   '^EXIT 2$' "$under"
grepq "S0f under-coverage message"   '6 of 10 anchored' "$under"
grepq "S0f names under-covered spec" 'tech/Y.md' "$under"
clean=$(check_exit '{"schema":2,"project":"p","anchors":[],"coverage":[{"spec":"tech/Z.md","declared":3,"anchored":3}],"declared_logic_ids":3,"anchored_logic_ids":3}')
echo "$clean"
grepq "S0f fully-covered (no graph) exits 0" '^EXIT 0$' "$clean"
rm -rf "$CT"

# --- S0g: CLI prints usage / hints, never raw tracebacks (issue #3) ----------
echo "=== S0g: CLI guards (no tracebacks) ==="
g1=$(python3 "$BRIDGE" 2>&1; echo "rc=$?")
echo "$g1"
ngrepq "S0g no args: no traceback" 'Traceback' "$g1"
grepq  "S0g no args: usage shown"  'usage:'    "$g1"
grepq  "S0g no args: exit 2"       'rc=2'      "$g1"
g2=$(python3 "$BRIDGE" check 2>&1; echo "rc=$?")
ngrepq "S0g short argv: no traceback" 'Traceback' "$g2"
grepq  "S0g short argv: exit 2"       'rc=2'      "$g2"
EM="$(mktemp -d)"; mkdir -p "$EM/tech"
g3=$(python3 "$BRIDGE" check "$EM" someproj 2>&1; echo "rc=$?")
echo "$g3"
ngrepq "S0g missing sidecar: no traceback" 'Traceback'           "$g3"
grepq  "S0g missing sidecar: anchor hint"  'run .livedocs anchor' "$g3"
grepq  "S0g missing sidecar: exit 2"       'rc=2'                 "$g3"
rm -rf "$EM"

# --- S0h: cbm retries the cold-start error, raises on persistence (issue #6) --
# Uses a fake cbm (LIVEDOCS_CBM) that returns the cold-start error JSON for the
# first N-1 calls. Proves transient errors self-heal (deterministic runs) and a
# persistent one raises BackendError instead of becoming a not_in_graph anchor.
echo "=== S0h: cbm cold-start retry + BackendError ==="
HT="$(mktemp -d)"
cat > "$HT/fakecbm" <<'SH'
#!/usr/bin/env bash
n=$(cat "$HT_COUNTER" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$HT_COUNTER"
if [ "$n" -ge "${FAKE_OK_ON:-999}" ]; then
  echo '{"results":[{"qualified_name":"X","label":"Method"}]}'
else
  echo '{"error":"project not found or not indexed","available_projects":["p"]}'
fi
SH
cat > "$HT/fakeempty" <<'SH'
#!/usr/bin/env bash
echo '{"results":[]}'
SH
chmod +x "$HT/fakecbm" "$HT/fakeempty"
h1=$(HT_COUNTER="$HT/c1" FAKE_OK_ON=3 LIVEDOCS_CBM="$HT/fakecbm" python3 - "$BRIDGE" <<'PY' 2>&1
import sys, importlib.util, os
spec=importlib.util.spec_from_file_location("c", sys.argv[1]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
r = c.cbm("search_graph", {"project":"p"}, retries=5)
print("RESULT_OK", bool(r.get("results")))
print("CALLS", open(os.environ["HT_COUNTER"]).read().strip())
PY
)
echo "$h1"
grepq "S0h retries cold error then succeeds" 'RESULT_OK True' "$h1"
grepq "S0h took exactly 3 backend calls"     'CALLS 3'        "$h1"
h2=$(HT_COUNTER="$HT/c2" FAKE_OK_ON=999 LIVEDOCS_CBM="$HT/fakecbm" python3 - "$BRIDGE" <<'PY' 2>&1
import sys, importlib.util
spec=importlib.util.spec_from_file_location("c", sys.argv[1]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
try:
    c.cbm("search_graph", {"project":"p"}, retries=2); print("NO_RAISE")
except c.BackendError as e:
    print("RAISED")
PY
)
echo "$h2"
grepq  "S0h persistent cold error raises BackendError" 'RAISED'   "$h2"
ngrepq "S0h never silently returns on persistent error" 'NO_RAISE' "$h2"
h3=$(LIVEDOCS_CBM="$HT/fakeempty" python3 - "$BRIDGE" <<'PY' 2>&1
import sys, importlib.util
spec=importlib.util.spec_from_file_location("c", sys.argv[1]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
print("EMPTY_OK", c.cbm("search_graph", {"project":"p"}, retries=2) == {"results": []})
PY
)
echo "$h3"
grepq "S0h genuine empty result is NOT retried" 'EMPTY_OK True' "$h3"

# --- S0i: empty root_path warns; LIVEDOCS_ROOT override restores it (issue #7) -
echo "=== S0i: empty root_path warning + LIVEDOCS_ROOT override ==="
cat > "$HT/fakeroot" <<'SH'
#!/usr/bin/env bash
echo '{"projects":[{"name":"p","root_path":""}]}'
SH
chmod +x "$HT/fakeroot"
i1=$(LIVEDOCS_CBM="$HT/fakeroot" python3 - "$BRIDGE" <<'PY' 2>&1
import sys, importlib.util
spec=importlib.util.spec_from_file_location("c", sys.argv[1]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
print("ROOT", repr(c.project_root("p")))
PY
)
echo "$i1"
grepq "S0i empty root_path warns"   'no root_path' "$i1"
grepq "S0i empty root_path -> None" 'ROOT None'    "$i1"
i2=$(LIVEDOCS_ROOT=/tmp/ld_override LIVEDOCS_CBM="$HT/fakeroot" python3 - "$BRIDGE" <<'PY' 2>&1
import sys, importlib.util
spec=importlib.util.spec_from_file_location("c", sys.argv[1]); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
print("ROOT", repr(c.project_root("p")))
PY
)
echo "$i2"
grepq  "S0i LIVEDOCS_ROOT override wins"      'ROOT .*/tmp/ld_override' "$i2"
ngrepq "S0i override suppresses root warning" 'no root_path'            "$i2"
rm -rf "$HT"

# --- S0b: CLAUDE.md injection (no graph; explicit project dir) ---------------
# `livedocs inject` reuses parse_specs and needs no graph when given the project
# dir, so it runs here without cbm. Proves: create, idempotent re-run (one marker
# pair, one heading), correct counts, and that surrounding CLAUDE.md is preserved.
echo "=== S0b: inject ## Codebase into CLAUDE.md ==="
IT="$(mktemp -d)"; mkdir -p "$IT/docs/semantic/tech" "$IT/docs/semantic/structural"
cat > "$IT/docs/semantic/tech/ORD_01_Orders.md" <<'MD'
---
feature_id: ORD
module: shop
logic_id_count: 2
---
| Logic ID | Description | File | Function/Method | Complexity |
|----------|-------------|------|-----------------|------------|
| ORD-L1 | Place an order  | `src/OrderManager.php` | `OrderManager::placeOrder()`  | high |
| ORD-L2 | Cancel an order | `src/OrderManager.php` | `OrderManager::cancelOrder()` | low  |
MD
cat > "$IT/docs/semantic/tech/PAY_01_Payments.md" <<'MD'
---
feature_id: PAY
module: payments
logic_id_count: 1
---
| Logic ID | Description | File | Function/Method | Complexity |
|----------|-------------|------|-----------------|------------|
| PAY-L1 | Charge a card | `src/Gateway.php` | `Gateway::charge()` | high |
MD
# create path
iout=$(python3 "$BRIDGE" inject "$IT/docs/semantic" no-such-project "$IT" 2>&1)
echo "$iout"
grepq "S0b reports counts (2 features, 3 Logic IDs)" '2 features, 3 Logic IDs' "$iout"
eq    "S0b CLAUDE.md created"     "$( [ -f "$IT/CLAUDE.md" ] && echo yes )" yes
eq    "S0b one start marker"      "$(grep -c 'livedocs:start' "$IT/CLAUDE.md")" 1
eq    "S0b one Codebase heading"  "$(grep -c '^## Codebase'   "$IT/CLAUDE.md")" 1
grepq "S0b stat line in section"  '2 features, 3 Logic IDs across 2 modules' "$(cat "$IT/CLAUDE.md")"
grepq "S0b feature listing"       'Features: ORD:Orders|PAY:Payments'        "$(cat "$IT/CLAUDE.md")"
# idempotent re-run
python3 "$BRIDGE" inject "$IT/docs/semantic" no-such-project "$IT" >/dev/null 2>&1
eq "S0b still one start marker after re-run"     "$(grep -c 'livedocs:start' "$IT/CLAUDE.md")" 1
eq "S0b still one Codebase heading after re-run" "$(grep -c '^## Codebase'   "$IT/CLAUDE.md")" 1
# preserves surrounding content (append path)
printf '# My Project\n\nKEEP THIS LINE.\n' > "$IT/CLAUDE.md"
python3 "$BRIDGE" inject "$IT/docs/semantic" no-such-project "$IT" >/dev/null 2>&1
grepq "S0b preserves pre-existing CLAUDE.md content" 'KEEP THIS LINE' "$(cat "$IT/CLAUDE.md")"
rm -rf "$IT"

# --- S0/S1: fixture + first index -------------------------------------------
echo "=== S0/S1: write fixture + index ==="
write_fixture
"$CBM" cli index_repository "{\"repo_path\":\"$FIX\"}" >/dev/null 2>&1
PROJ=$("$CBM" cli list_projects '{}' 2>/dev/null | python3 -c '
import json,sys
fix=sys.argv[1]
for p in json.load(sys.stdin).get("projects",[]):
    if p.get("root_path")==fix: print(p["name"]); break
' "$FIX")
if [ -z "$PROJ" ]; then echo "FAIL: could not capture project name"; exit 1; fi
echo "project = $PROJ"
poll_ready

# --- S2: pre-assert source present on both methods --------------------------
echo "=== S2: source present (guards degenerate fixture) ==="
sfn=$("$CBM" cli search_graph "{\"project\":\"$PROJ\",\"name_pattern\":\"^shortFn$\"}" 2>/dev/null \
      | python3 -c 'import json,sys;r=json.load(sys.stdin)["results"];print(r[0]["qualified_name"] if r else "")')
lfn=$("$CBM" cli search_graph "{\"project\":\"$PROJ\",\"name_pattern\":\"^longFn$\"}" 2>/dev/null \
      | python3 -c 'import json,sys;r=json.load(sys.stdin)["results"];print(r[0]["qualified_name"] if r else "")')
ssrc=$("$CBM" cli get_code_snippet "{\"project\":\"$PROJ\",\"qualified_name\":\"$sfn\"}" 2>/dev/null \
       | python3 -c 'import json,sys;print(bool(json.load(sys.stdin).get("source")))')
lsrc=$("$CBM" cli get_code_snippet "{\"project\":\"$PROJ\",\"qualified_name\":\"$lfn\"}" 2>/dev/null \
       | python3 -c 'import json,sys;print(bool(json.load(sys.stdin).get("source")))')
eq "S2 shortFn has source" "$ssrc" True
eq "S2 longFn has source"  "$lsrc" True

# --- S3: anchor + shape asserts ---------------------------------------------
echo "=== S3: anchor ==="
python3 "$BRIDGE" anchor "$SEM" "$PROJ"
eq     "S3 schema==2"               "$(field CALC-L1 @schema)"           2
eq     "S3 L1 status ok"            "$(field CALC-L1 status)"            ok
eq     "S3 L1 fp null (blind spot)" "$(field CALC-L1 fp)"                ""
truthy "S3 L1 content_hash set"     "$(field CALC-L1 content_hash)"
eq     "S3 L1 hash_source snippet"  "$(field CALC-L1 hash_source)"       snippet
eq     "S3 L2 status ok"            "$(field CALC-L2 status)"            ok
truthy "S3 L2 content_hash set"     "$(field CALC-L2 content_hash)"
eq     "S3 L3 hash_source snippet"  "$(field CALC-L3 hash_source)"       snippet
eq     "S3 L4 not_in_graph"         "$(field CALC-L4 status)"            not_in_graph
truthy "S3 L4 file fallback hash"   "$(field CALC-L4 content_hash)"
eq     "S3 L4 hash_source file"     "$(field CALC-L4 hash_source)"       file
truthy "S3 L5 file fallback hash"   "$(field CALC-L5 content_hash)"
eq     "S3 L5 hash_source file"     "$(field CALC-L5 hash_source)"       file

# --- S4: baseline check (clean) ---------------------------------------------
echo "=== S4: baseline check ==="
reindex
out=$(python3 "$BRIDGE" check "$SEM" "$PROJ"); rc=$?
echo "$out"
eq    "S4 exit 0"  "$rc" 0
grepq "S4 0 stale" '^0 stale' "$out"

# --- S5: positive short (fp-null fallback) ----------------------------------
echo "=== S5: edit shortFn body ==="
sed -i 's/return \$n + 1;/return \$n + 2;/' "$FIX/src/Calc.php"
reindex
out=$(python3 "$BRIDGE" check "$SEM" "$PROJ"); rc=$?
echo "$out"
eq    "S5 exit 1"     "$rc" 1
grepq "S5 L1 CHANGED" 'CHANGED .*CALC-L1' "$out"
sed -i 's/return \$n + 2;/return \$n + 1;/' "$FIX/src/Calc.php"

# --- S6: positive long ------------------------------------------------------
echo "=== S6: edit longFn body ==="
sed -i 's/\$out = "result:" \. \$acc;/\$out = "RESULT=" . \$acc;/' "$FIX/src/Calc.php"
reindex
out=$(python3 "$BRIDGE" check "$SEM" "$PROJ"); rc=$?
echo "$out"
eq     "S6 exit 1"        "$rc" 1
grepq  "S6 L2 CHANGED"    'CHANGED .*CALC-L2' "$out"
ngrepq "S6 L1 NOT listed" 'CALC-L1' "$out"
sed -i 's/\$out = "RESULT=" \. \$acc;/\$out = "result:" . \$acc;/' "$FIX/src/Calc.php"

# --- S7: signature precedence -----------------------------------------------
echo "=== S7: change longFn signature ==="
sed -i 's/public function longFn(int \$n): string {/public function longFn(int \$n, int \$m): string {/' "$FIX/src/Calc.php"
reindex
out=$(python3 "$BRIDGE" check "$SEM" "$PROJ"); rc=$?
echo "$out"
grepq "S7 L2 SIGNATURE_CHANGED" 'SIGNATURE_CHANGED .*CALC-L2' "$out"
sed -i 's/public function longFn(int \$n, int \$m): string {/public function longFn(int \$n): string {/' "$FIX/src/Calc.php"

# --- S8: non-graph file fallback (real declaration edit = drift) ------------
echo "=== S8: edit constants ==="
sed -i 's/const MAX_N = 1000;/const MAX_N = 1001;/' "$FIX/constants.php"
reindex
out=$(python3 "$BRIDGE" check "$SEM" "$PROJ"); rc=$?
echo "$out"
grepq "S8 L4 CHANGED" 'CHANGED .*CALC-L4' "$out"
sed -i 's/const MAX_N = 1001;/const MAX_N = 1000;/' "$FIX/constants.php"
sed -i 's/const TABLE = \[1, 2, 3\];/const TABLE = [1, 2, 3, 4];/' "$FIX/constants.php"
reindex
out=$(python3 "$BRIDGE" check "$SEM" "$PROJ"); rc=$?
echo "$out"
grepq "S8 L5 CHANGED" 'CHANGED .*CALC-L5' "$out"
sed -i 's/const TABLE = \[1, 2, 3, 4\];/const TABLE = [1, 2, 3];/' "$FIX/constants.php"

# --- S8b: file-fallback declaration-only (unrelated comment = NO drift) ------
# Regression guard for the false-drift bug: an unrelated comment mentioning the
# constant must NOT change its declaration hash.
echo "=== S8b: unrelated comment mentioning MAX_N ==="
reanchor
printf '\n// NOTE: MAX_N is the documented upper bound.\n' >> "$FIX/constants.php"
reindex
out=$(python3 "$BRIDGE" check "$SEM" "$PROJ"); rc=$?
echo "$out"
eq     "S8b exit 0 (comment ignored)" "$rc" 0
ngrepq "S8b L4 NOT drifted"           'CALC-L4' "$out"
write_fixture

# --- S9: negative control (trailing-whitespace, no false drift) -------------
# normalize() folds CRLF/CR and rstrips each line; trailing whitespace on code
# lines must therefore NOT drift. (Interior blank lines ARE preserved by design
# and so are NOT a valid no-drift control — see normalize() docstring.)
echo "=== S9: trailing-whitespace-only edits ==="
reanchor
python3 - "$FIX/src/Calc.php" <<'PY'
import sys
p = sys.argv[1]; t = open(p).read()
t = t.replace("    $acc = 0;\n", "    $acc = 0;   \n")     # trailing ws, no new line
t = t.replace("    return $out;\n", "    return $out;\t\n")  # trailing tab
open(p, "w").write(t)
PY
reindex
out=$(python3 "$BRIDGE" check "$SEM" "$PROJ"); rc=$?
echo "$out"
eq "S9 exit 0 (trailing ws ignored)" "$rc" 0
write_fixture

# --- S10: docstring control (documents tradeoff) ----------------------------
echo "=== S10: docblock-only edit ==="
reanchor
sed -i 's/   \* Long op docblock./   * Long op docblock. EDITED PROSE ONLY./' "$FIX/src/Calc.php"
reindex
out=$(python3 "$BRIDGE" check "$SEM" "$PROJ"); rc=$?
echo "$out"
eq "S10 exit 0 (docstring excluded)" "$rc" 0
write_fixture

# --- S11: cleanup happens in trap -------------------------------------------

# ============================================================================
# OPTIONAL FP-CORROBORATOR SUB-TEST (non-destructive; set OB_DOCS + OB_PROJECT)
# ============================================================================
if [ -z "$OB_DOCS" ] || [ ! -d "$OB_DOCS" ] || [ -z "$OB" ]; then
  echo "=== P1-P5: SKIPPED (set OB_DOCS to a docs dir and OB_PROJECT to its project) ==="
else
echo "=== P1-P5: fp-corroborator + disambiguation delta ==="
rm -rf "$OB_SEM"
cp -r "$OB_DOCS" "$OB_SEM"
rm -f "$OB_SEM/.anchors.json"   # drop any stale sidecar carried by the copy
python3 "$BRIDGE" anchor "$OB_SEM" "$OB" >/dev/null 2>&1

# P3: poison a real fp-bearing anchor into the LEGACY path: set content_hash=None
#     and flip fp -> wrong value, so check must fall to the fp corroborator.
deltas=$(python3 - "$OB_SEM/.anchors.json" <<'PY'
import json, sys
p = sys.argv[1]; data = json.load(open(p))
amb = sum(1 for a in data["anchors"] if a["status"] == "ambiguous")
victim = next((a for a in data["anchors"]
               if a["status"] == "ok" and a.get("fp")), None)
if victim:
    victim["content_hash"] = None                       # force legacy fp path
    victim["fp"] = "DEADBEEF" + (victim["fp"] or "")[8:]  # wrong fp
    json.dump(data, open(p, "w"), indent=2)
print(json.dumps({"ambiguous": amb,
                  "victim_lid": (victim or {}).get("logic_id")}))
PY
)
echo "anchor summary: $deltas"
amb=$(printf '%s' "$deltas"  | python3 -c 'import json,sys;print(json.load(sys.stdin)["ambiguous"])')
vlid=$(printf '%s' "$deltas" | python3 -c 'import json,sys;print(json.load(sys.stdin)["victim_lid"] or "")')
truthy "P3 found fp-bearing victim anchor" "$vlid"

# P4: check must report the poisoned anchor as CHANGED via the legacy fp branch
out=$(python3 "$BRIDGE" check "$OB_SEM" "$OB"); rc=$?
printf '%s\n' "$out" | grep -E "CHANGED" | grep "$vlid" | head -3
grepq "P4 poisoned anchor CHANGED (fp corroborator)" "CHANGED .*$vlid" "$out"

# P5: disambiguation delta (report + assert it fell below the baseline).
echo "P5 DISAMBIGUATION: ambiguous count now = $amb (baseline 9; lone glob row expected to remain)"
if [ "$amb" -lt 9 ]; then ok "P5 ambiguous fell below baseline 9 (now $amb)"; else bad "P5 ambiguous not reduced (now $amb)"; fi
fi   # end OB_DOCS guard

# --- summary -----------------------------------------------------------------
echo
echo "==================================================="
echo "RESULT: $PASS passed, $FAIL failed"
echo "==================================================="
[ "$FAIL" -eq 0 ]
