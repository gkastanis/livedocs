# Rewiring notes (work left for later)

This file lists work that is deliberately not being done yet. None of it is in
scope right now. Today the repo is a faithful, byte-for-byte copy of the
drupal-workflow 2.0.1 documentation feature, plus the generic bridge core.
Nothing below has been rewired.

## 1. Make drupal-workflow depend on this repo

The intended end state (decided by George on 2026-06-24) is for there to be one
copy of these files, not two that drift apart. The drupal-workflow plugin would
keep only its build, review, and verify parts, and get the documentation feature
from this repo instead of carrying its own copy.

This is deferred because it means changing the installed drupal-workflow plugin,
which the rules for this repo currently forbid. It is a separate step, done by a
person, after this repo is published.

Rough shape of the eventual change (do not do this now):

- Remove the documentation feature (the agent, the `structural-index`,
  `semantic-docs`, and `discover` skills, and the four validators) from
  drupal-workflow, and have its installer pull this repo instead.
- Leave drupal-workflow's autopilot, task classifier, session analysis, and
  hooks alone. Those were never part of the copy.

## 2. Rewire the copied adapter files

The Drupal adapter files were copied as-is, so they still contain references that
assume the drupal-workflow plugin is running. These are written down, per file
and per line, in `adapters/drupal/README.md` under "What still needs rewiring".
That README is the single source for the list, so it is not repeated here. In
short, running the adapter on its own will eventually require:

- pointing `PLUGIN_ROOT` (now `CLAUDE_PLUGIN_ROOT` or the
  `/tmp/drupal-workflow-plugin-root` temp file) at the adapter root;
- providing or removing the calls to `inject-claude-md.sh`, which was not part of
  the copied feature and is genuinely missing here;
- deciding what to do with text that mentions the `/drupal-refresh` command,
  which this repo does not ship.

Until that work is done, the adapter scripts are kept for provenance and
reference. The structural generators do run on their own, but the full Drupal
pipeline driven by the `drupal-semantic` command does not yet.

## 3. Keeping the copy in sync with upstream

Because the adapter is a copy, it can fall behind the drupal-workflow plugin.
When this work is picked up:

- Record the copied version (now 2.0.1) and re-run `diff -r` against the upstream
  documentation feature to find upstream changes before re-syncing.
- Keep the boundary the same: copy only the documentation feature (the agent, the
  three skills, the four validators), never the workflow-engine files.
- Once item 1 is done, this repo becomes the source of truth and the sync
  reverses (the plugin pulls from this repo), which retires this note.

## 4. Installer release path

`install.sh` currently copies files out of this working checkout. Before
publishing, change it to download a release archive and check it against a
published `SHA256` (a `checksums.txt`), the way codebase-memory-mcp does for its
binary. This is marked inline in `install.sh` as `TODO(release)`.
