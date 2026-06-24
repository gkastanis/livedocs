---
description: Check whether the semantic docs still match the code, and regenerate any that drifted.
argument-hint: "[docs-dir] [project]"
---

Keep this project's livedocs documentation in sync with the code, end to end.

Inputs (from the arguments, with defaults):

- Docs directory: the first argument, or `docs/semantic` if none is given.
- codebase-memory-mcp project: the second argument. If none is given, run
  `codebase-memory-mcp cli list_projects '{}'` and pick the project whose root
  path is this repository.

Steps:

1. Run the drift check:
   `livedocs check <docs-dir> <project>`
   The graph is kept current by auto-index during this session, so there is no
   need to re-index first.

2. If it exits 0 (prints `0 stale`), tell the user the documentation is in sync
   and stop.

3. If it reports drift, it lists each stale Logic ID with a status (CHANGED,
   SIGNATURE_CHANGED, MOVED, or GONE) and the spec file it appears in. Group the
   stale Logic IDs by spec file.

4. For each affected spec under `<docs-dir>/tech/`, regenerate just that feature
   with this project's doc generator. For the Drupal adapter, act as the
   `semantic-architect` agent: read the module's current source plus the
   structural index and rewrite the drifted rows. Preserve every existing Logic
   ID (never renumber), append new ones, and mark removed code as deprecated
   rather than deleting its row. Update `last_updated` and `logic_id_count`.

5. Refresh the sidecar so it matches the updated docs:
   `livedocs anchor <docs-dir> <project>`

6. Report which Logic IDs had drifted, which spec files you updated, and confirm
   that `livedocs check` is now clean.

Do not modify specs whose Logic IDs were not flagged.
