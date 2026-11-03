# Value validation: offline example

This example packages **synthetic** observations into a report with a denominator, unknowns
and human minutes. It is not customer, payment, demand or profitability evidence. It sends
nothing, calls no model, never contacts people and makes no investment decision. Longhaul may
help a human decide what to do with actual, scoped evidence; no automatic adapter is provided.

From the repository root on a supported Linux host:

```sh
python3 examples/value_validation/new_task.py /tmp/value-validation-demo
python3 -m makeextreme run /tmp/value-validation-demo
cat /tmp/value-validation-demo/report.json
python3 -m makeextreme run /tmp/value-validation-demo
```

The second run skips the unchanged stage. Delete `report.json` and rerun to rebuild it.
Change `offer.json`'s revision alone and the next run fails: observations belong to the old
offer. Update the synthetic fixture's revision too and rerun to regenerate the report. This
shows dependency invalidation and a limited revision check; it cannot establish whether old
observations are applicable, authenticate their source or verify the content. Never simply
relabel real observations after a changed offer. Record the cost of real failures and human
work outside this demonstration; protect private data in a suitable location.
