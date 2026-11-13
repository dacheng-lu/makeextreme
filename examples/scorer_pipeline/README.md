# Score a saved reply as a recoverable task

This offline example calls FlowLore's existing `local-model-baseline/scorer.py`
for **one saved reply**. It uses that scorer's deterministic digest or Longhaul
gate oracle; it does not call a model or reproduce the scoring rules. The
`score` stage checks the JSON result as well as the command exit code. This is
necessary because the scorer exits 0 even when its `score` is 0. The `report`
stage records the accepted result, the reply hash and scorer/checker source
hashes. Dependencies and outputs are declared so a changed reply or checker
invalidates the score, and unchanged completed work can be skipped.
The configuration is bound when the task is created; create a new task to
change the case or checkout paths rather than editing `config.json`.

Requires Linux, Python 3 and local checkouts of Makeextreme, FlowLore and
Longhaul. Run from Makeextreme's root; replace the two checkout paths below.
The sample replies are hand-written fixtures, not model observations.

```sh
work=$(mktemp -d)
printf '%s\n' '{"verdict":"pass","open":[]}' > "$work/reply.json"
python3 examples/scorer_pipeline/new_task.py "$work/task" \
  --flowlore ../flowlore --longhaul ../longhaul --case g-stale --reply "$work/reply.json"

python3 -m makeextreme run "$work/task"  # exit 2: scorer returned score 0
cat "$work/task/score.json"              # expected blocked, got pass
test ! -e "$work/task/accepted.json"      # report stage did not run

printf '%s\n' '{"verdict":"blocked","open":["C1"]}' > "$work/task/reply.txt"
python3 -m makeextreme run "$work/task"  # exit 0: score 1 and report
cat "$work/task/accepted.json"
python3 -m makeextreme run "$work/task"  # both stages skip unchanged work
```

The scorer's existing per-oracle subprocess timeout remains in force; the score
stage has a 240-second process-group bound and the report stage a 30-second
bound. An infrastructure error or malformed score fails the stage rather than
becoming a model score of 0. The journal and `task.json` record attempts and
stage outcomes. `score.json` is overwritten by a retry; preserve a separate
copy first if the failed reply and score are needed as lasting evidence.

Always inspect the latest runner exit and task status: after a previously
successful run, an upstream failure does **not** delete the old `accepted.json`.
Its presence alone does not prove that the current run passed. Hashes bind the
listed local bytes, not their authorship or truth; the example does not record a
model identity or prove how the reply was produced. It assumes the checkouts and
inputs do not change concurrently. A one-case score is not a benchmark and does
not validate general model quality. For a real-model interruption and the limits
of that observation, see FlowLore's `examples/local-model-baseline/recovery.py`.

The repository test below uses a stub of the scorer's CLI contract to exercise
an interrupted score stage, rejection when the scorer exits 0 with score 0,
retry, skipping, source invalidation and infrastructure failure. It does not
claim to test FlowLore's scoring logic.

```sh
python3 -m unittest discover -s tests -p 'test_scorer_pipeline.py' -v
```
