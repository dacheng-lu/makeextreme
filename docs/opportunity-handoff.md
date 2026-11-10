# Execute a selected opportunity experiment

Longhaul's [bounded zoom-out protocol](https://github.com/dacheng-lu/longhaul/blob/main/references/zoom-out.md)
owns strategic framing. Makeextreme receives one selected, authorized experiment.
This document defines a manual handoff; it does not add a parser, scheduler,
sensor adapter or automatic three-project execution.

## Before configuring stages

Carry a task-owned experiment brief containing:

- Original goal, selected hypothesis, owner and authorized scope.
- Baseline and versioned inputs; distinguish synthetic fixtures, recorded replay
  and new measurements. Identify unknown or unavailable dependencies.
- Measurements, sample/window, predeclared continue/adjust/stop conditions.
- Resource cap, external-action boundaries and exit/rollback.
- Artifact locations and checks that can actually run on this host.

Map the selected procedure into the normal `stages.json` contract. Include the
brief and relevant fixtures/configuration in stage `deps`; name produced files in
`outputs`; keep checks deterministic where possible. A changed goal or baseline
invalidates the affected evidence: do not relabel old results to the new brief.
Use existing approval and budget mechanisms where applicable; this prose adds
neither an ACL nor automatic enforcement of experiment economics.

The [offline value-validation example](../examples/value_validation/README.md)
already demonstrates synthetic observations, revision binding and output recovery.
It is a runnable mechanics example, not a RuView adapter or proof of market value.

## Keep three outcomes separate

| Question | Possible answer | Must not be inferred |
| --- | --- | --- |
| Did configured stages finish? | complete / partial / not run | Finished means the hypothesis is true |
| What evidence exists? | synthetic / measured / missing, with scope | A hash proves observation accuracy |
| What did the experiment show? | supported within scope / rejected / inconclusive / not evaluated | A zero exit code proves a 10x effect |

Do not put an unobserved field measurement behind a check that always succeeds.
A measured failure can be a valid experiment result. Missing hardware is a blocker
for the hardware stage, not a reason to pretend a fixture is a measurement.

## Sensor-reliability example (design only)

For the [RuView/video recipe](https://github.com/dacheng-lu/flowlore/blob/main/recipes/sensor-reliability.md),
an eventual stage sequence could validate the input contract, replay each baseline,
apply the candidate policy, compare observations and package the report. Use a
fixed logical clock for deterministic freshness tests. Preserve `unknown`, source
timestamps, room mapping and failure reasons; do not treat a sensor's missing
negative as agreement. Never let a stale retained `online` value authorize action.

The video repository's interface and live compatibility were not accessible at
review time (2026-11-09). No stage command for it is specified here. No device
control, alert delivery or live surveillance is enabled by this document.

Send a changed strategic assumption back to Longhaul. Retain the scoped result
and counterexample in Flowlore; do not let the runner autonomously replace the
experiment with a larger product goal.
