# Does livedocs help an AI on coding tasks?

Eval date 2026-06-25. Run on a real Drupal codebase; all symbol names here are
pseudonyms (consistently renamed, numbers and reasoning preserved). The testbed is
not public, so these numbers are a pilot, not a reproducible benchmark. Reproduce
the method on your own corpus with the harness in this directory.

## Question

Not "can an agent find code with docs" (the docs contain the answer, so that is
rigged). The honest question: on an unfamiliar codebase, does livedocs help an agent
that ALREADY has the same code-graph and grep the control has? And does it help on
cost, on correctness, or on the quality of the context it loads?

## Setup

- 6 grep-hostile tasks across 3 documented modules. Gold derived from CODE only, so
  doc quality cannot bias it. Dataset is valid against ai_eval's Layer-1
  dataset.schema.json.
- Arms isolated by git worktree, differing only in the capability under test:
  - G  = grep + read only (no graph, no docs)
  - GG = + codebase-memory code-graph
  - L  = + livedocs docs (read as targeted slices, not whole files)
- Harness hardened against context leaks (stripped the project CLAUDE.md's existing
  doc-pointer sections from the no-doc arms; forbade search_code because the graph had
  indexed the docs; forbade the drupal-workflow doc skills; isolated worktree parents).

## Results, three lenses

**1. Correctness (localization, graph+grep baseline vs +livedocs).** ~Tied. A first
trial looked like a large docs win (6/6 vs 4/6); a second trial did not replicate it
(blind arm got 6/6). Over both trials 11/12 vs 10/12. n=1 was misleading.

**2. Efficiency.** livedocs cut tool operations ~13%. Token cost depended entirely on
ACCESS PATTERN: reading whole doc files cost about what it saved (a wash); accessing
docs as targeted slices (grep the matching row) was ~10-16% cheaper and beat even the
no-docs baseline. So docs only "pay for themselves" on cost when queried as rows.

**3. Context quality (the metric that matters most).** A downstream change-PLAN task,
scored for context-completeness: did the plan surface the load-bearing files AND the
constraints (gates, rules, the right abstraction)? Scored two independent ways that
agree:

| arm            | Codex judge (gpt-5.5) | deterministic rubric |
|----------------|-----------------------|----------------------|
| G  (grep)      | 72%                   | 72%                  |
| GG (+graph)    | 82%                   | 86%                  |
| L  (+livedocs) | 87%                   | 87%                  |

The judge is a different model family from the Claude plan-authors, so there is no
self-preference. Discriminator-only elements (intent the code does not name): G 75%,
GG 83%, L 83%.

## Conclusion

Context-quality ranking: livedocs > graph-only > grep-only. But the magnitude is the
real finding:

- The CODE-GRAPH does most of the lift over raw grep (+10 points). It is the workhorse.
- livedocs adds a small, real increment ON TOP of the graph (+5 points) and never hurt;
  it even recovered context the graph-only arm got wrong on one task.
- livedocs did NOT beat the graph on the intent/discriminator elements (tied at 83%).
  For these tasks the graph already exposes most of what the docs encode.

Throughline across all three lenses: against a graph-backed agent, livedocs is
consistently small-but-positive and never negative. Its decisive edge, if it has one,
must come from what a graph structurally cannot hold: business intent the code does not
encode, and drift-checking that keeps docs from misleading.

A concrete contamination caught along the way doubles as evidence: without a graph or
docs, a grep-only agent twice searched the WRONG project entirely (the session's working
dir), loading completely wrong context. Both a graph and docs anchor the agent to the
right code.

## Caveats

n=1 per cell (high variance); 2 of 6 tasks saturate (every arm scores full); one task's
rubric did not match what its change elicited and dragged all arms. The consistent
ordering across two scoring methods is what gives confidence, not any single cell.

## Next

The one untested arm is the real differentiator: fresh-docs vs STALE-docs. Keep arm L,
add an arm whose docs point at pre-refactor symbols, and measure how far
context-completeness drops. That isolates the value of drift detection, the thing
livedocs uniquely provides and the only frame where it should decisively beat the graph.
Also: more trials for confidence intervals, and a synthetic PUBLIC testbed so results
are publishable.

## Artifacts (this directory)

- change_dataset.yaml          Layer-1 dataset (6 change-plan tasks)
- rubrics/ctx_*.yaml           6 context-completeness rubrics (rubric.schema.json)
- dataset.yaml                 the earlier localization dataset
- score.py / score_*           deterministic must_contain_any scorer
- judge_codex.py               Codex-as-independent-judge driver (reusable)
- verdict.schema.json          output schema enforced on the judge
- codex_verdicts.json          per-(arm,task) judge verdicts
