# Recovery budget admission and paired experiment

Run from the repository root:

```bash
python -m makeextreme.budget examples/recovery_budget/plan.json
python examples/recovery_budget/compare.py
python -m unittest discover -s tests -p 'test_budget.py'
```

The optional checker exits 0 for admission, 2 for insufficient/unknown resources
or exhausted attempts, and 64 for malformed input. For EACH resource separately:

`required = attempt * (1 + retry_reserve) + recovery + verification`

Admission also requires `attempts_used + 1 + retry_reserve <= max_attempts`.
Use nonnegative integer units (seconds, calls, or a declared currency's smallest
unit); never combine money, time and quality into one score. Null means unknown
and blocks admission. Retry reserve is the number of additional attempts to
budget now, not permission to retry an uncertain external effect.

## Integration boundary

This is a preflight on caller-supplied estimates, not a new runner budget ledger.
The host must refresh remaining resources and attempts before each invocation,
serialize competing admissions or atomically reserve funds, and measure actual
spend. The checker deliberately neither edits the plan nor calls a model.
Do not rely on two concurrent successful checks to reserve the same budget.
Actual API spending and wall-clock enforcement remain host responsibilities.

For a reviewed stage, place the checker at the start of its `run` command using
`python /absolute/path/to/makeextreme/budget.py budget.json && YOUR_COMMAND`.
Declare `budget.json` and the checker file in `deps`. Recheck on every attempt;
do not put the admission decision in a separately cached stage. Plan changes
invalidate that stage fingerprint; keep the budget for the intended stage only.
This check cannot approve an irreversible stage, reconcile an uncertain action,
or guarantee that YOUR_COMMAND stays within its estimate.

## Measured synthetic result

The paired example exhaustively enumerates 16 four-attempt boolean traces with
budget 10, cost 2 per attempt and verification cost 3. Both strategies stop on
first success; baseline only checks ability to pay the next attempt. Reserve
also checks ability to pay verification. All values are abstract units.

| Metric | Baseline | Reserve |
| --- | ---: | ---: |
| Verified completions | 14/16 | 14/16 |
| Total cost across traces | 102 | 98 |
| Outputs without affordable verification | 1 | 0 |
| Cost of four consecutive failures | 8 | 6 |

Three identical all-failure traces additionally illustrate correlated workers:
adding workers does not make that shared failure disappear. This is not an
empirical model of agent correlations. There are no model calls, measured real
API fees or measured recovery actions. `recovery` is tested by the checker, not
simulated as an actual repair process. Overestimated reserves can prevent useful
work; underestimated costs can still overrun. No universal 25% rule or Kelly
optimality is claimed. Promote only after paired real-task evaluations.
