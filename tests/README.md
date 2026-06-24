# tests

## test_drift.sh

This is an end-to-end test of the drift detection in `core/livedocs.py`. It
builds a small throwaway PHP project in a temporary directory, indexes it with
the codebase-memory-mcp command-line tool, anchors a handful of Logic IDs, then
makes specific edits and checks that `check` gives the right verdict each time.
It removes the temporary directory and the temporary indexed project when it
finishes, even on failure.

Run it from anywhere:

```bash
tests/test_drift.sh
```

It prints `PASS:` or `FAIL:` for each assertion and ends with a line like
`RESULT: 35 passed, 0 failed`. It exits non-zero if anything failed.

### What it checks

- Content drift on a short method that the graph does not fingerprint, which
  exercises the tool's own content hash, and on a longer method.
- Symbols the graph does not model, such as class constants, which are hashed
  from their declaration line on disk.
- That a changed method signature is reported before a content change.
- That edits which should not count do not raise a false alarm: an edit that only
  adds trailing whitespace, and an edit that only changes a doc comment.
- That an unrelated comment which merely names a constant does not flag it as
  changed.
- That a documentation row listing several methods in one cell still parses, and
  that a mismatch between the declared count and the parsed count prints a
  warning.

### What you need

You need `python3` (standard library only) and the codebase-memory-mcp
command-line tool. The test finds the tool through the `CBM` environment
variable and defaults to `~/.local/bin/codebase-memory-mcp`. Override it if the
tool lives elsewhere:

```bash
CBM=/path/to/codebase-memory-mcp tests/test_drift.sh
```

### The optional real-project check (OB_DOCS, OB_PROJECT)

After the throwaway-project checks, the script can run one more check against a
real project you already have indexed. It does not modify that project; it copies
its docs into the temporary directory first. It confirms the older `fp`
fingerprint path still works (by altering a copied sidecar on purpose) and
reports how many ambiguous Logic IDs remain.

This check is off by default. To turn it on, point `OB_DOCS` at the project's
semantic docs directory and set `OB_PROJECT` to that project's
codebase-memory-mcp project name. The project must already be indexed. If either
variable is unset, or the docs path does not exist, the check is skipped, not
failed.

```bash
OB_DOCS=/path/to/project/docs/semantic OB_PROJECT=my-project tests/test_drift.sh
```
