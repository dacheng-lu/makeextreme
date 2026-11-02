# Crash, recover, and verify a report

This is a **local demonstration**, not an integration adapter. Makeextreme runs
three stages; the example kills its own runner in the middle stage and resumes.
It verifies the report itself, records a Longhaul observation, then changes the
report to demonstrate stale-evidence rejection and a new observation. Neither a
successful stage nor a bookkeeping gate independently proves semantic correctness.

Requirements: Linux with `/proc` mounted in the current PID namespace, Python 3,
and checkouts of both repositories. The runner uses only temporary files and makes
no network requests; downloading the repositories requires network access.

```bash
git clone https://github.com/dacheng-lu/makeextreme.git
git clone https://github.com/dacheng-lu/longhaul.git
cd makeextreme
python3 examples/longhaul_recovery/demo.py --longhaul ../longhaul
```

Expected result: the runner is killed during `build`; the `prepare`, `build`, and
`report` stages start 1, 2, and 1 times respectively, and the report contents
match. Longhaul's gate passes, refuses stale evidence after the report changes,
and passes again only after the example checks the new content and records a new
observation. The temporary directory is deleted after the demo.

`pass` is supplied by the example after its explicit content check; it is not an
authenticated receipt and the Longhaul helper does not execute that check.
This does not test external effects, approval identity, a cross-session host
handoff, or an automatic adapter. If `/proc` cannot safely identify processes in
the current PID namespace, the example refuses rather than running recovery.

For Makeextreme alone, see [the output-deletion example](../../docs/first-recovery.md).
