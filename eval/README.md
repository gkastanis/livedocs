# livedocs context-quality eval

Does livedocs help an AI coding agent that already has a code-graph and grep? This
directory holds the harness and the pilot results. `FINDINGS.md` is the writeup.

## What this is, and is not

The tasks were run on a real Drupal codebase. Every symbol name here is a pseudonym:
a private testbed was renamed consistently across all files, with the numbers and the
models' reasoning left intact. The testbed itself is not public, so the dataset and
rubrics are a worked example of the method, not a suite you can run as-is. The numbers
are a pilot (n=1 per cell), not a reproducible benchmark. To get your own numbers,
point the three arms at a repo you control and rewrite the gold.

## Method

Three arms differing only in the capability under test:

- `G`  grep and read only
- `GG` plus a codebase-memory code-graph
- `L`  plus livedocs docs, read as targeted slices

Each arm produces a change plan for a downstream task. The plan is scored for
context-completeness: did it surface the load-bearing files and the constraints
(gates, rules, the right abstraction) a correct change depends on? Scored two
independent ways that agree:

1. A deterministic `must_contain_any` rubric (`score.py`, dogfooding ai_eval's
   `rubric.schema.json`).
2. An independent judge, Codex / gpt-5.5, constrained by `verdict.schema.json`. The
   judge is a different model family from the plan authors, so there is no
   self-preference.

Result: L 87% > GG 82% > G 72% (Codex). The code-graph does most of the lift over
raw grep; livedocs adds a small, consistent increment on top. See `FINDINGS.md`.

## Files

| File | What |
|------|------|
| `FINDINGS.md` | The writeup: question, setup, three lenses, conclusion, caveats. |
| `change_dataset.yaml` | 6 change-plan tasks (ai_eval `dataset.schema.json`). |
| `rubrics/ctx_*.yaml` | Per-task context-completeness rubrics (`rubric.schema.json`). |
| `score.py` | Deterministic scorer and rubric source of truth. `emit-rubrics` regenerates `rubrics/`. |
| `judge_codex.py` | Codex-as-independent-judge driver. Reusable. |
| `verdict.schema.json` | Output schema enforced on the judge. |
| `codex_verdicts.json`, `verdicts/` | The judge's per-(arm, task) verdicts. |
| `judge_run.log` | Judge run log with the aggregate table. |
| `dataset.yaml` | An earlier localization dataset (the correctness and efficiency lenses). |
| `CLAUDE.base.md` | The control project instructions: doc-pointer sections stripped, so the no-doc arms cannot cheat. |

## Reproduce on your own repo

1. Replace the task `input`, gold, and rubric terms (`score.py` `TASKS`) with symbols
   from your codebase. Run `python3 score.py emit-rubrics rubrics` to regenerate the
   rubric YAML.
2. Run each task three times (G, GG, L), capturing the agent transcripts. Strip any
   doc-pointer sections from the project instructions for the no-doc arms.
3. Point `judge_codex.py` at your transcripts (`LIVEDOCS_EVAL_TRANSCRIPTS=...`) and run
   it. It extracts the plans, scores them with Codex, and prints the arm table.
4. Cross-check against `python3 score.py score <plans_dir>`. The two methods should
   land within a few points; that agreement is the confidence, not any single cell.
