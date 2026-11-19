# Design the shortest useful stage sequence

Use this check when a repeated workflow, measured bottleneck, or proposed stage
sequence has unnecessary-looking work. A straightforward local task need not go
through a separate optimization exercise. Start with the user's requested result,
authorized scope and acceptance criteria; if the goal or procedure is unknown,
return to exploration instead of inventing stages.

For each proposed stage, name its independent contribution: a required artifact,
dependency, transformation, verification, recovery checkpoint or external
action. Ask what would fail if it were removed, and whether another stage already
fulfils that role. A stage with no remaining role is a candidate for removal or
merging, not automatically safe to delete. Compare one explicit metric, such as
stage starts or elapsed time, while holding the input and acceptance criteria
fixed. An ideal lower bound is a thought experiment; a feasible path must still
respect actual permissions, data integrity, checks and recovery needs.

Before changing a sequence, check what the change does to:

- Declared `deps` and `outputs`, invalidation and reproducibility.
- Failure isolation, retry cost, idempotency and the loss of a recovery checkpoint.
- Required approval, its artifact binding, external effects and uncertain outcomes.
- The final artifact and its acceptance check. Do not weaken the check to make a
  shorter sequence pass.

Record what was simplified, the limitation accepted, and the condition that
requires revisiting it. Prefer a small reversible trial; compare the same inputs
and checks, and report measured results separately from estimates. A hash binds
content but does not establish its correctness or the approver's identity. The
runner executes the stage definitions supplied to it; it does not remove stages
or decide whether an optimization is safe.

## Example: remove a disposable copy stage

This is a **design-only local-file example**, not a measured performance claim.
Suppose `input.txt` is already a suitable, stable input and no consumer needs an
intermediate copy. Both alternatives must produce `report.txt` byte-for-byte
equal to `input.txt` and pass `cmp -s input.txt report.txt`.

Before, one stage copies `input.txt` to `working.txt` and checks that copy; a
second copies `working.txt` to `report.txt` and checks the final equality. After,
one stage copies `input.txt` directly to `report.txt` and runs the same final
check. The latter declares `input.txt` as a dependency and `report.txt` as an
output. It removes one configured stage and the intermediate file, not a proven
amount of runtime. Both commands must be independently safe to retry.

This is valid only if the intermediate copy provides no required snapshot,
inspection, consumer, permission boundary or separate recovery point. The
original has a resumable intermediate checkpoint; the shorter version gives that
up. Revisit the choice if any such need appears or if inputs may change while a
stage runs. A side effect requiring approval must retain its own appropriate
approval and artifact binding; this example has no external effect or approval.
To claim an actual speedup, run both alternatives with the same representative
input and environment, retain the same final check, and report measurements and
failures. See [first recovery](first-recovery.md) for a runnable output-recovery
example and [opportunity handoff](opportunity-handoff.md) for experiment scope.
