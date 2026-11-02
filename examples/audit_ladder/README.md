# Audit ladder

An audit of a git range written as makeextreme stages, so the cheapest evidence is spent first and the expensive model is called last and once.

```
scope -> tier0 -> cheap -> findings -> replay -> final_prompt -> final_audit (approval required)
```

| Stage | What it does | Model? |
|---|---|---|
| `scope` | pins `base` and `head` to 40-character commit ids | no |
| `tier0` | runs your suite on a clean checkout of the committed head; builds a pack of only the functions the diff touched (`bin/slice_diff.py`). A red suite fails the stage, and so does a green suite that ran 0 tests or whose output has no readable test count (`Ran N tests` or `N passed`), unless the task was made with `--count-optional` (a suite that ran 0 tests still fails). | no |
| `cheap` | a cheap model reads the pack (fixed rules first, so a cache can reuse the prefix) | cheap |
| `findings` | parses the report: exactly one `FINDINGS` block and one `VERDICT` (a block the model forgot to close is read up to the verdict and flagged) | no |
| `replay` | every finding needs a result you wrote in `replays.json` (`confirmed` or `not_reproduced`, with evidence). A confirmed BLOCKER or MAJOR fails the stage: the expensive model is not called on a tree known to be broken. A FAIL verdict that no BLOCKER or MAJOR finding explains also fails it (the report is in a shape the parser cannot read, or contradicts itself). A bullet that starts with a severity word in any case counts as a finding of that severity (`- major refactor ...` is a MAJOR): reading too much costs you one `not_reproduced` result, dropping a finding would cost a missed defect. | no |
| `final_prompt` | builds the final prompt from the goal, the criteria, the changed paths, the measured numbers and the checked findings, and checks that none of the cheap model's text outside the findings got in | no |
| `final_audit` | the expensive model. `approval: required`, with `final_prompt.md` in `deps`: change the prompt and the approval is void. | expensive |

Why a runner and not a script: a crash or a second cron tick skips every stage that had *finished*, so those cost no model call; a model call that was still in flight when the runner died is made again by the next run, and the runner does not stop a model command it had started; the expensive call is one execution per approval; a failed `final_audit` is `uncertain` (the call may have been paid for) and a plain `run` does not repeat it.

## Use

```
python examples/audit_ladder/new_task.py <task_dir> --repo <git repo> --base <rev> --suite "<test command>" \
    --goal "<what the change is for>" --criterion "<acceptance criterion>" \
    --cheap-cmd "<shell>" --final-cmd "<shell>"
python -m makeextreme run <task_dir>         # stops at `replay` if a finding has no replay result
# write <task_dir>/replays.json: {"F1": {"status": "not_reproduced", "evidence": "what you ran and saw"}}
python -m makeextreme run <task_dir>         # stops at the approval gate (exit 4)
python -m makeextreme approve <task_dir> final_audit
python -m makeextreme run <task_dir>         # the final report is <task_dir>/final_report.txt
```

The two model commands are plain shell. They read the prompt from `$AUDIT_PROMPT`, print the report on stdout, and get `$AUDIT_REPO`, `$AUDIT_BASE` and `$AUDIT_HEAD`. Give them a read-only view of a clean copy of the repository **without its git history** (history can contain the fix). The pipeline parses what they print and never executes it.

## What is and is not verified

`tests/test_audit_ladder.py` (33 tests) and `tests/test_slice_diff.py` (13) run the ladder against a throw-away repository with stand-in models that only count their calls and print a canned report. Mutants `L1`-`L26` (`L21` was retired as an equivalent mutant) and `S1`-`S7` in `tests/mutants.py` cover the properties above. **It has not been run with a real model yet.** The pack matches callers by name, which is noisy for common names, and no static analyzer is used. Measured on this repository's real diffs the pack is 62% and 88% of the changed Python files for two ranges (5% for a two-function change): the saving here is modest because the diffs are wide, not deep.
