# core: the generic engine

`livedocs.py` is the part of the tool that matches documentation to code and
detects drift. It has no Drupal in it and does not depend on what language the
codebase is written in. The Drupal documentation generators live separately in
`../adapters/drupal/`. To support a different documentation format, write an
adapter that produces the table format described below; the core does not change.

For every lookup, the core runs the codebase-memory-mcp command-line tool
(`~/.local/bin/codebase-memory-mcp cli <tool> '<json>'`). It never talks to the
graph any other way.

## How matching and drift detection work

### Finding the code for a Logic ID

Each Logic ID is matched to exactly one node in the graph using that node's
`qualified_name`, the dotted path that identifies a symbol (for example
`myproject.src.Service.OrderManager.OrderManager.createOrder`). A Logic ID can
point at a method, a function, a class, an interface, or a variable.

When a bare method name matches more than one node, the matcher narrows the
choice in this order: prefer methods and functions over other kinds, then keep
only nodes whose file name matches the file named in the docs, then keep only
nodes whose parent class matches the class named in the docs. If more than one
node still matches, the matcher does not guess. It records the Logic ID as
`ambiguous` and moves on.

### The drift signals

The core stores several pieces of information for each anchor and compares them
on the next check.

`content_hash` is the main signal. It is a SHA-256 hash of the node's real
source code, taken from `get_code_snippet`, after a small amount of cleanup in
`normalize()`: line endings are converted to `\n`, trailing whitespace is
removed from each line, and fully blank lines at the very start and end are
dropped. Nothing else is touched. Indentation, comments, and blank lines inside
the body are kept. This hash is computed for every resolved anchor, so it also
covers the cases where the graph has no fingerprint of its own.

`signature` catches changes to a method's parameter list. When both the stored
and the current signature are present and they differ, the anchor is reported as
`signature_changed`, which takes priority over a content change.

`fp` is the graph's own optional fingerprint. The core only falls back to it for
old sidecars (schema version below 2) or for anchors that have no `content_hash`.

The file fallback covers symbols the graph does not model at all, such as PHP
class constants and traits. For these the core reads the declared file from disk
and hashes only the lines that declare the named symbol, never lines that merely
mention it and never comment lines. So an unrelated comment that names the symbol
cannot trigger false drift. These anchors are marked `hash_source: "file"`.

The verdicts that `check` can print are `changed`, `signature_changed`, `moved`,
and `gone`, plus the carried-over states `ambiguous` and `not_in_graph`. `check`
exits 1 if any anchor is stale and 0 if none are.

### The documentation format the core reads

The core reads the `tech/*.md` files under the documentation directory you give
it. From each file it needs two things.

First, a `feature_id: <ID>` line in the frontmatter.

Second, a table of rows in this shape:

```
| <LOGIC-ID> | <description> | `<file>` | `<Class::method()>` | <complexity> |
```

`<LOGIC-ID>` matches the pattern `[A-Z]+-L\d+`, for example `MCP-L15`. The method
cell is reduced to a bare symbol name, so `Class::method()` becomes `method`. If
the cell lists several methods separated by commas, the first one is used. Rows
whose symbol is not a valid identifier are skipped. The file cell becomes the
`declared_file`, which is used both to narrow an ambiguous match and to drive the
file fallback. If a file's frontmatter declares a `logic_id_count` that does not
match the number of rows actually parsed, the core prints a warning, so rows that
fail to parse cannot disappear silently.

### The sidecar file

`anchor` writes `<docs>/.anchors.json`. It is meant to be committed to git. It
uses `schema: 2` and holds an array of records. Each record carries `logic_id`,
`feature`, `spec`, `declared_file`, `method`, `qualified_name`, `fp`,
`signature`, `content_hash`, `hash_source` (`snippet`, `file`, or null),
`start_end`, `parent_class`, `status`, and `verified_at`. `check` reads this file
back and compares it against the current graph. Running `anchor` writes this file
next to your docs; it is meant to be committed to git.

## Commands

```
livedocs anchor <docs> <project>             find the node for each Logic ID, write .anchors.json
livedocs check  <docs> <project>             report drift; exit 1 if any anchor is stale
livedocs enrich <docs> <project> <logic_id>  print the live call graph for one Logic ID
```

codebase-memory-mcp: https://github.com/DeusData/codebase-memory-mcp
