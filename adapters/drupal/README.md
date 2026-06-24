# Drupal adapter

These are the Drupal-specific files that produce the documentation the generic
livedocs core in `core/` reads. They turn a Drupal project's service files, hooks,
plugins, routes, and entities into the Markdown that the core matches against the
code graph.

## Where these files came from

Every file under `adapters/drupal/`, except this README, was copied without
changes from the drupal-workflow Claude Code plugin, version 2.0.1. Each one is
byte-for-byte identical to its source. They are only the documentation part of
that plugin. The unrelated parts of the plugin (its autopilot, task classifier,
session analysis, and hooks) were left behind on purpose.

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

The copy was checked with `diff -r` (every tree and file identical) and by
comparing executable bits (all `.sh` files kept at mode 775).

## What still needs rewiring

Some of the copied files refer to things outside `adapters/drupal/` or assume
they are running inside the drupal-workflow plugin. They are listed here but left
unchanged, because this repo keeps the files as a faithful copy. They will need
fixing before the full Drupal pipeline runs on its own.

### 1. PLUGIN_ROOT assumes the plugin runtime

`scripts/project-state-check.sh:9`

```
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
```

This falls back to `CLAUDE_PLUGIN_ROOT`, which only the Claude Code plugin loader
sets. The `$(dirname)/..` fallback happens to resolve to the adapter root here,
so the call on line 41 to `$PLUGIN_ROOT/scripts/validate-semantic-docs.sh` does
find the copied validator. But the environment-variable path is a plugin
assumption that does not hold in this standalone repo.

`commands/drupal-semantic.md:31`

```
PLUGIN_ROOT=$(cat /tmp/drupal-workflow-plugin-root 2>/dev/null || echo "${CLAUDE_PLUGIN_ROOT:-}")
```

This reads a temp file written by the plugin's startup, or `CLAUDE_PLUGIN_ROOT`.
Neither exists here, so `PLUGIN_ROOT` ends up empty and every
`"$PLUGIN_ROOT/scripts/..."` call below it breaks.

### 2. A referenced script that was not copied

`commands/drupal-semantic.md` calls `"$PLUGIN_ROOT/scripts/inject-claude-md.sh"`
at lines 114, 147, 261, and 308. That script exists in the source plugin but is
not part of the documentation feature, so it was not copied and is absent here.
These calls will fail until the script is provided or the calls are removed.

### 3. Commands referenced but not copied

`commands/drupal-semantic.md:43,191` and `agents/semantic-architect.md:39`
mention `/drupal-refresh`. That is a separate drupal-workflow command outside the
copied set. The references are prose pointing at a command this repo does not
ship.

### 4. Validator cross-calls that depend on PLUGIN_ROOT

`commands/drupal-semantic.md` calls `"$PLUGIN_ROOT/scripts/validate-tech-specs.sh"`
at lines 104, 251, 285, and 291, and `project-state-check.sh:41` calls
`"$PLUGIN_ROOT/scripts/validate-semantic-docs.sh"`. Both target scripts were
copied into `scripts/`, so these work as long as `PLUGIN_ROOT` is set to the
adapter root (see item 1).

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
