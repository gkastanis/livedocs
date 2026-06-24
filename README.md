# livedocs

Living documentation for codebases. livedocs generates documentation from your
code, ties every statement to the exact function or class it describes, and
keeps checking that the documentation still matches. When the code changes, it
tells you which docs went stale, so they never quietly rot.

## The problem it solves

Teams that document their code well hit the same problem over and over: the docs
go out of date and nobody notices. A function gets rewritten, renamed, or
deleted, but the paragraph that explains it stays the same. Readers keep
trusting documentation that is now wrong. livedocs ties every documented
statement to the code it describes, so a single command tells you which
statements no longer hold.

## How it works

livedocs has two parts. An adapter reads your codebase and writes the
documentation as Markdown. The core then links each documented item to the real
code and watches for drift.

To locate and track code, the core uses a code knowledge graph: a database of
every function, class, and method in the codebase, and how they connect, built
and kept current by a separate program called codebase-memory-mcp (see Install).
The graph always reflects the current code; the documentation is what drifts. So
livedocs anchors each documented item to the graph, records a fingerprint of the
code, and later reports when the two no longer agree.

The core is generic and does not depend on any language or framework. Today
there is one adapter, for Drupal. Because the core does not depend on it,
adapters for other frameworks can be added the same way.

## Words used in this project

You will see these terms throughout the tool and these docs:

- Knowledge graph: the automatically built database of code symbols described
  above.
- codebase-memory-mcp: the separate program that builds and serves that graph.
  This tool calls it for every lookup. It is a required dependency.
- Logic ID: a short label in the documentation, such as `REG-L1`, that points at
  one specific method. Each row in a doc's mapping table carries one Logic ID.
- Anchor: the record that ties one Logic ID to the real code it describes, plus
  a fingerprint of that code. "To anchor" means to create those records.
- Drift: the situation where the code an anchor points to has changed, moved, or
  been deleted, so the documentation is now wrong.
- Sidecar: the file the tool writes, named `.anchors.json`, that stores all the
  anchors next to the documentation.

## What the output looks like

The Drupal adapter writes its documentation under `docs/semantic/` in the
project being documented. There are three kinds of files. The examples below are
made up; a real run produces the same shapes from your own code.

A structural index, generated straight from the code (no AI). One file per
aspect, listing what exists. For example `docs/semantic/structural/services.md`:

```
| Service | Class | Dependencies | Module | Tags |
|---------|-------|--------------|--------|------|
| `shop.order_manager` | `Drupal\shop\OrderManager` | @entity_type.manager,@current_user | shop | - |
```

Tech specs, one per feature, each with a Logic-to-Code table. This is the part
livedocs anchors. Every row gives a Logic ID, a plain-language description, the
file, and the exact method (`docs/semantic/tech/ORD_01_Orders.md`):

```markdown
---
type: tech_spec
feature_id: ORD
feature_name: Orders
module: shop
last_updated: 2026-06-24
logic_id_count: 2
---

# ORD_01: Orders

## Logic-to-Code Mapping

| Logic ID | Description | File | Function/Method | Complexity |
|----------|-------------|------|-----------------|------------|
| ORD-L1 | Place an order and reserve stock | `src/OrderManager.php` | `OrderManager::placeOrder()` | high |
| ORD-L2 | Cancel an order and release stock | `src/OrderManager.php` | `OrderManager::cancelOrder()` | medium |
```

The sidecar, written by `livedocs anchor` into `docs/semantic/.anchors.json`.
One record per Logic ID, tying it to a graph node and a fingerprint of the code.
This is what `check` compares against (record abbreviated):

```json
{
  "logic_id": "ORD-L1",
  "declared_file": "src/OrderManager.php",
  "method": "placeOrder",
  "qualified_name": "shop.src.OrderManager.OrderManager.placeOrder",
  "content_hash": "a1b2c3d4...",
  "signature": "(OrderInterface $order, AccountInterface $account)",
  "status": "ok"
}
```

## How the documentation is generated

The two layers are produced in different ways.

The structural index is deterministic. The adapter's shell generators read the
project's YAML and PHP and write the `structural/*.md` files. No AI and no graph
are involved:

```bash
adapters/drupal/skills/structural-index/scripts/generate-all.sh /path/to/project
```

The tech specs (the Logic-to-Code tables) are written by the semantic-architect
agent, defined in `adapters/drupal/agents/semantic-architect.md`. It turns the
structural index plus the source code into the intent layer. For each feature
(one Drupal module) it:

- reads the structural index (`services.md` for dependencies, `methods.md` for
  the Logic-to-Code table, and `routes.md`, `hooks.md`, `permissions.md` for
  routing, hook, and access entries) along with the module's source code;
- writes one tech spec, giving a Logic ID (`ORD-L1`, `ORD-L2`, ...) to each
  meaningful unit of behavior: service methods, routes, hook implementations;
- checks that every method it names actually exists in the code before writing
  it.

It handles one feature per run to keep each pass focused. Logic IDs are stable:
existing ones are never renumbered, new ones are appended, and removed code is
marked deprecated rather than deleted, so the anchors stay valid across updates.

The agent and the generators are a faithful copy of the drupal-workflow plugin.
The generators run on their own today; the single `drupal-semantic` command that
orchestrates the agent needs the rewiring noted in `docs/REWIRING-NOTES.md`
before it runs end to end as one command.

## Creating, updating, and keeping docs in sync

You do not run an index command. The installer turns on codebase-memory-mcp's
auto-index, so while your coding agent is connected the graph indexes new
projects and re-indexes on git changes in the background. The graph stays current
on its own.

To create the docs the first time:

1. Generate the structural index with `generate-all.sh` (above).
2. Run the semantic-architect agent, one feature at a time, to write the tech
   specs.
3. `livedocs anchor docs/semantic my-project` records which code each Logic ID
   points to and writes the sidecar.

After that, keeping the docs honest is one step. From inside your coding agent,
run the slash command:

```
/livedocs-check
```

It runs the drift check, and if anything drifted it lists the stale Logic IDs,
regenerates only the affected tech specs with the semantic-architect agent, and
refreshes the sidecar. Running it inside the agent is also when the code graph is
current (the auto-index watcher is live in that session) and when the
regeneration step can run. The installer adds this command to your agent.

The same check is also a plain command, for scripts and CI:

```bash
livedocs check docs/semantic my-project   # exit 0 = docs match, 1 = something drifted
```

`check` prints the exact Logic IDs whose code changed, moved, or vanished. In a
headless setting (CI, or a pre-push hook) there is no coding-agent session, so the
background watcher is not running and the stored graph may be behind. Index once
before checking:

```bash
codebase-memory-mcp cli index_repository '{"repo_path":"."}'
livedocs check docs/semantic my-project
```

To look at one Logic ID, `livedocs enrich docs/semantic my-project ORD-L1` prints
the live call graph around its code. Each command takes the documentation
directory and then the codebase-memory-mcp project name. The documentation
directory must contain a `tech/` folder of Markdown files with the table shown
above. The exact format the core reads is in `core/README.md`.

## What this repo contains

The code is split into two parts so that documentation formats other than
Drupal's can be added later without touching the core.

The core (`core/livedocs.py`) is the part that does the matching and drift
detection. It has no Drupal in it and does not care what language the codebase is
written in. It works for any documentation that produces the table format the
core understands.

The Drupal adapter (`adapters/drupal/`) is the part that produces that
documentation for Drupal projects. It reads Drupal service files, hooks, plugins,
routes, and entities and writes them out as the Markdown the core reads. It was
copied from an existing Claude Code plugin called drupal-workflow. It is one
adapter; others could be written for other frameworks.

```
livedocs/
├── core/
│   ├── livedocs.py      # the matcher and drift detector: anchor, check, enrich
│   └── README.md          # how the core works and the table format it reads
├── commands/
│   └── livedocs-check.md  # the /livedocs-check slash command (check + regenerate)
├── adapters/
│   └── drupal/            # Drupal documentation generators (copied from drupal-workflow 2.0.1)
│       ├── agents/        # the agent that writes the intent docs
│       ├── commands/      # the drupal-semantic command
│       ├── skills/        # structural-index, semantic-docs, discover
│       ├── scripts/       # four validators
│       └── README.md      # where these files came from and what still needs rewiring
├── tests/
│   ├── test_drift.sh      # runs the whole pipeline against a throwaway project
│   └── README.md
├── docs/
│   └── REWIRING-NOTES.md  # work left for later
├── install.sh             # installs livedocs and the adapter assets
└── LICENSE                # MIT
```

## Install

This is an unpublished work in progress, so there is no hosted install URL yet.
Run the installer from a local checkout:

```bash
./install.sh            # ask before each step
./install.sh --dry-run  # show what it would do, without changing any files
./install.sh --uninstall
```

The installer puts `core/livedocs.py` on your PATH as `livedocs` and makes sure
codebase-memory-mcp is present (installing it if it is missing). It also sets two
codebase-memory-mcp options so you do not have to manage the graph by hand: it
turns on auto-index (so the graph re-indexes itself on git changes), and it adds
the Drupal file types such as `.module` and `.install` that the indexer skips by
default. On a machine that already has the drupal-workflow plugin, run
`./install.sh --skip-agents` to install the command-line tool without the
skills, command, and agent, because those share names with the plugin's and
would collide. Run `./install.sh --help` for the options.

## Running the tests

```bash
tests/test_drift.sh
```

This builds a small throwaway project, indexes it with codebase-memory-mcp,
anchors some Logic IDs, then edits the code and confirms that `check` reports the
right drift each time. It needs `python3` and the codebase-memory-mcp
command-line tool on your PATH. There is an optional extra check that runs
against a real project when you set `OB_DOCS` and `OB_PROJECT`. See
`tests/README.md`.

## Documentation

- `core/README.md`: how the core matches docs to code, the exact table format
  it reads, and the sidecar schema.
- `adapters/drupal/README.md`: where the Drupal adapter files came from and what
  still needs rewiring.
- `tests/README.md`: running the end-to-end drift test.
- `docs/REWIRING-NOTES.md`: the work left for later.

## Status

This is a working proof of concept. The core matching and drift detection are
tested against real projects. The Drupal
adapter is a faithful copy of the original plugin files and runs its structural
generators on their own, but a few of its files still reference the old plugin
and need rewiring before the full Drupal pipeline runs end to end. The installer
copies files from this checkout rather than from a published release. What is
left to do is listed in `docs/REWIRING-NOTES.md`.

## License

MIT, copyright gkastanis. See `LICENSE`. The Drupal adapter files were copied
from the drupal-workflow plugin (version 2.0.1), which declares MIT in its
`.claude-plugin/plugin.json` (with `Zorz` named as the plugin's author). That
plugin ships no `LICENSE` file, so this repo includes a fresh MIT text. Where
each adapter file came from is recorded in `adapters/drupal/README.md`.

codebase-memory-mcp: https://github.com/DeusData/codebase-memory-mcp
