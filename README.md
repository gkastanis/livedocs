# semantic-graph-bridge

This tool checks whether written documentation about a codebase still matches
the code it describes. When the code that a piece of documentation points to has
changed or been deleted, the tool flags that documentation as out of date. That
way nobody has to hunt for stale docs by hand.

## The problem it solves

Teams that document their code well hit the same problem over and over: the docs
go out of date and nobody notices. A function gets rewritten, renamed, or
deleted, but the paragraph that explains it stays the same. Readers keep
trusting documentation that is now wrong.

This tool sits between two things you already have:

1. A code knowledge graph. This is a database of every function, class, and
   method in a codebase, and how they connect. It is built automatically by a
   separate program called codebase-memory-mcp (see the link at the bottom). It
   stays current because it is rebuilt from the code itself, but it only knows
   the shape of the code, not what any of it is for.
2. Written documentation. These are Markdown files that explain what each
   feature does and which method implements it. They capture meaning and intent,
   but they are written once and then slowly drift away from the code.

semantic-graph-bridge connects the two. It reads the documentation, finds the
real code each documented item points to, and records a fingerprint of that
code. Later it checks again. If the code has changed, moved, or disappeared, it
tells you exactly which documented items are now stale.

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

## How you use it

There are three commands. Each takes two arguments, in this order: the
documentation directory, then the name of the codebase-memory-mcp project for
that codebase.

```bash
# 1. anchor: for every Logic ID, find the code it points to, record a
#    fingerprint, and write the sidecar (<docs>/.anchors.json).
cbm_bridge anchor docs/semantic my-project

# 2. check: look up each anchored Logic ID again and compare. Print any that
#    changed, moved, or vanished. Exit code is 0 when everything matches and 1
#    when anything is stale, so you can use it as a pre-push or CI gate.
cbm_bridge check docs/semantic my-project

# 3. enrich: show the live call graph around the code for one Logic ID.
cbm_bridge enrich docs/semantic my-project REG-L1
```

`check` prints the exact Logic IDs that are stale. You can feed that list into
whatever process regenerates the affected docs, so you only redo the parts that
actually drifted.

The documentation directory must contain a `tech/` folder of Markdown files,
each holding a table that maps Logic IDs to methods. The exact table format is
described in `core/README.md`.

## What this repo contains

The code is split into two parts so that documentation formats other than
Drupal's can be added later without touching the core.

The core (`core/cbm_bridge.py`) is the part that does the matching and drift
detection. It has no Drupal in it and does not care what language the codebase is
written in. It works for any documentation that produces the table format the
core understands.

The Drupal adapter (`adapters/drupal/`) is the part that produces that
documentation for Drupal projects. It reads Drupal service files, hooks, plugins,
routes, and entities and writes them out as the Markdown the core reads. It was
copied from an existing Claude Code plugin called drupal-workflow. It is one
adapter; others could be written for other frameworks.

```
semantic-graph-bridge/
├── core/
│   ├── cbm_bridge.py      # the matcher and drift detector: anchor, check, enrich
│   └── README.md          # how the core works and the table format it reads
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
├── install.sh             # installs cbm_bridge and the adapter assets
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

The installer puts `core/cbm_bridge.py` on your PATH as `cbm_bridge`, makes sure
codebase-memory-mcp is present (installing it if it is missing), and tells
codebase-memory-mcp to index Drupal file types such as `.module` and `.install`,
which it skips by default. On a machine that already has the drupal-workflow
plugin, install the command-line tool only and skip the agent and skill wiring,
because those would collide with the plugin's. Run `./install.sh --help` for the
options.

## Running the tests

```bash
tests/test_drift.sh
```

This builds a small throwaway project, indexes it with codebase-memory-mcp,
anchors some Logic IDs, then edits the code and confirms that `check` reports the
right drift each time. It needs `python3` and the codebase-memory-mcp
command-line tool on your PATH. There is an optional extra check that runs
against a real project when the `OB_DOCS` variable points at it. See
`tests/README.md`.

## Status

This is a working proof of concept, kept in this repo only and not published. The
core matching and drift detection are tested against real projects. The Drupal
adapter is a faithful copy of the original plugin files and runs its structural
generators on their own, but a few of its files still reference the old plugin
and need rewiring before the full Drupal pipeline runs end to end. The installer
copies files from this checkout rather than from a published release. What is
left to do is listed in `docs/REWIRING-NOTES.md`.

## License

MIT. See `LICENSE`. The Drupal adapter files were copied from the drupal-workflow
plugin (version 2.0.1), which declares MIT in its `.claude-plugin/plugin.json`
and names Zorz, the owner of this repo, as author. That plugin ships no `LICENSE`
file, so this repo includes a fresh MIT text. Where each adapter file came from
is recorded in `adapters/drupal/README.md`.

codebase-memory-mcp: https://github.com/DeusData/codebase-memory-mcp
