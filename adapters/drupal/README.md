# Drupal adapter

These are the Drupal-specific files that produce the documentation the generic
livedocs core in `core/` reads. They turn a Drupal project's service files, hooks,
plugins, routes, and entities into the Markdown that the core matches against the
code graph.

## Where these files came from

Every file under `adapters/drupal/`, except this README, was imported from the
drupal-workflow Claude Code plugin, version 2.0.1, as a verbatim copy. They are
only the documentation part of that plugin; the unrelated parts (its autopilot,
task classifier, session analysis, and hooks) were left behind on purpose. A few
files have since been rewired so the adapter runs standalone instead of inside
the plugin runtime, see "Standalone wiring" below.

- Source: drupal-workflow 2.0.1
- License: MIT, declared in the plugin's `.claude-plugin/plugin.json`. The plugin
  ships no `LICENSE` file.
- Author: Zorz (the plugin's declared author). This repo is maintained by gkastanis.

What was copied:

| Source path (drupal-workflow 2.0.1) | Adapter path |
|---|---|
| `agents/semantic-architect.md` | `agents/semantic-architect.md` |
| `commands/drupal-semantic.md` | `commands/drupal-semantic.md` |
| `skills/structural-index/` (whole) | `skills/structural-index/` |
| `skills/semantic-docs/` (whole) | `skills/semantic-docs/` |
| `skills/discover/` (whole) | `skills/discover/` |
| `scripts/project-state-check.sh` | `scripts/project-state-check.sh` |
| `scripts/staleness-check.sh` | `scripts/staleness-check.sh` |
| `scripts/validate-semantic-docs.sh` | `scripts/validate-semantic-docs.sh` |
| `scripts/validate-tech-specs.sh` | `scripts/validate-tech-specs.sh` |

At import the copy was checked with `diff -r` (every tree and file identical) and
by comparing executable bits (all `.sh` files kept at mode 775). The files rewired
for standalone use since then are listed under "Standalone wiring"; the rest stay
identical to 2.0.1.

## Standalone wiring

The copied files originally assumed the drupal-workflow plugin runtime. They have
been rewired so the adapter runs on its own, as installed by `install.sh`:

- **Script location.** `install.sh` puts the `livedocs` core on PATH (in
  `$PREFIX/bin`) and the adapter validators flat in `$PREFIX/lib/livedocs`.
  `commands/drupal-semantic.md` derives that lib dir from the binary location
  (`LIVEDOCS_LIB="$(cd "$(dirname "$(command -v livedocs)")/../lib/livedocs" && pwd)"`)
  and calls `$LIVEDOCS_LIB/validate-tech-specs.sh`. `scripts/project-state-check.sh`
  finds its sibling `validate-semantic-docs.sh` from its own directory. Neither
  needs `PLUGIN_ROOT` or `CLAUDE_PLUGIN_ROOT` any more.
- **CLAUDE.md injection.** The plugin's `inject-claude-md.sh` was never part of
  the copied feature, so the four calls to it now use the generic
  `livedocs inject <docs-dir> <project> <project-dir>` that the core ships.
- **Dead command hints.** Prose that pointed at `/drupal-refresh` and
  `/drupal-bootstrap` (commands this repo does not ship) now points at the
  structural-index generators (`generate-all.sh`).

One cross-repo step remains and is deliberately not done here: folding this
documentation feature back so the drupal-workflow plugin depends on this repo
instead of carrying its own copy. That edits the installed plugin and is a
separate, human step, tracked as item 1 in `../../docs/REWIRING-NOTES.md`.

### Things that look like problems but are not

- `skills/structural-index/scripts/generate-all.sh` finds its own location with
  `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"` and only calls the
  sibling generators that were copied. It needs no rewiring.
- `../config/sync` and `../HolidayService.php` (in `generate-entity-schemas.sh:38`
  and `skills/structural-index/SKILL.md:149,194`) are paths in the Drupal project
  being analyzed, not paths into the plugin.
- `@service`, `@plugin`, `@http`, `@queue`, and similar tokens in
  `generate-dependency-graph.sh` and `generate-service-graph.sh` are Drupal
  service names, not references to Claude agents.
- `@semantic-architect`, `/discover`, `/structural-index`, `/drupal-semantic`,
  and `/semantic-docs` all refer to assets that are present in this adapter.
