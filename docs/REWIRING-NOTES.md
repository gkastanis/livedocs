# Rewiring notes (work left for later)

This file lists cross-repo work that is deliberately not being done yet. The
adapter itself has been rewired to run standalone (item 2 below is done); what
remains is the plugin-side consolidation and checksum-verified release archives
for the installer (it currently fetches the `main` branch tarball). The
adapter started as a verbatim copy of the drupal-workflow 2.0.1 documentation
feature; the files changed since are listed in `adapters/drupal/README.md` under
"Standalone wiring".

## 1. Make drupal-workflow depend on this repo

The intended end state (decided by gkastanis on 2026-06-24) is for there to be one
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

## 2. Rewire the copied adapter files (done)

Done. The adapter no longer assumes the drupal-workflow plugin runtime: it
resolves its validators from the installed `livedocs` lib dir, injects the
`## Codebase` section via the generic `livedocs inject`, and points its prose at
`generate-all.sh` instead of the unshipped `/drupal-refresh` and
`/drupal-bootstrap` commands. The full `drupal-semantic` command now runs
standalone. The exact per-file changes are in `adapters/drupal/README.md` under
"Standalone wiring".

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

`install.sh` self-bootstraps: from a checkout it copies files out of the working
tree, and when piped from `curl` it downloads the `main` branch tarball
(`https://github.com/$SLUG/archive/$REF.tar.gz`) into a temp dir and installs
from there. The remaining work is to point it at tagged, signed **release**
archives and verify them against a published `SHA256` (a `checksums.txt`), the
way codebase-memory-mcp does for its binary, instead of fetching an unpinned
branch tarball.
