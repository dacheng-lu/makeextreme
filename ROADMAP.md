# Roadmap

makeextreme keeps no schedule. This page says what has been released, what is still owed, what is only a candidate, and what is deliberately not planned. **It is a direction, not a commitment: nothing here has a date, and a "Candidate" item is not decided.** State: version 1.2.0 (a page cannot name the commit that contains it; the version is what the tests check).

This page is in English; the design record it points to ([ARCHITECTURE.md](ARCHITECTURE.md), decisions D1 to D20) is in Chinese. 本页使用英语，设计记录使用中文。 Diese Seite ist auf Englisch, das Entwurfsprotokoll auf Chinesisch.

## Released

- **1.2.0** (2026-11-02): **a release that tightens what a task may declare, which is why it is a minor and not a patch version: two stages that declare the same output, or an output inside another stage's output, were accepted by 1.1.0 and now exit 64 (a task in which only one of those stages ever writes the file ran correctly under 1.1.0; the check cannot know which stage writes, so it refuses both; the maintainer chose to keep the refusal and the version number on 2026-11-02).** Fixes from the deep audit D19, which was first calibrated on a planted defect (the defect was found in 3 of 3 runs; one planted defect is one sample, so a PASS means "found nothing with an auditor of measured but narrow strength", not "nothing there"). The audit found 0 blockers, 0 major, 12 minor and 9 plan items; every counterexample was replayed by the maintainer. This release fixes: a declared dependency or output that overlaps the runner's own record (`task.json`, `journal.jsonl`, `approvals.jsonl`, `lock`), the task directory or another stage's output is refused with exit 64 before anything runs (D21; it used to re-run on every run and leave an approval stage stuck at exit 5); two tests that stayed green without the mechanism they name, and a mutant that went red by a crash instead of its reason; `cron_tick.sh` started through a symlink, a missing interpreter reported as a refused task (now exit 69), and advice lines that could not be pasted into a shell; `ac10_mutants.py` on a machine without `~/ac10work`; and the documents that disagreed with the code (test counts, the README's AC10 command, exit code 64's causes, the `resolve --retry` wording). It also adds an example, `examples/audit_ladder/` (design record D22): an audit of a git range as stages with the expensive model behind an approval bound to its prompt; tested only with stand-in models. A second review round (14 findings, followed by a delta review with 4 findings that was not calibrated on a planted defect) fixed: the filesystem root and a path inside a record file as declared paths, a NUL byte in a declared path, a MAJOR written as `- **MAJOR**:` or behind an invisible character that the ladder's parser dropped, a suite that ran 0 tests failing with no message, and bidi or zero-width characters reaching the final prompt.
- **1.1.0** (2026-11-01): a stage may declare `outputs`; their content is recorded after the run and checked before every skip (design record D20, acceptance AC11). It closes a measured gap: on 1.0.0, deleting the last stage's output left `run` exiting 0 with a `skip` and no file. A stage without `outputs` keeps its 1.0.0 fingerprint, so existing tasks resume unchanged.
- **1.0.0** (2026-11-01): the runner (crash resume, "done" decided from the artifact, approvals bound to the artifact and spent by one execution, one `flock`), the video-pipeline example (AC10), the Hermes host example (AC9), the cron tick launcher and the three-language [README](README.md). Published before its final independent audit (D19).

No tags and no GitHub Releases exist yet.

## In development on main

The `resolve` hardening refuses `--done` when the uncertain stage's fingerprint or
declared dependencies changed, or when its check changes those dependencies.
Removing an approval requirement before resolving or after a retry decision is
refused. Restore the requirement and, for `--done`, the original fingerprint.
These changes are not yet part of a numbered release. The fingerprint checks do
not prevent concurrent edits after the check, and they cannot prove external effects.

## Owed

- **The project's own copyright line.** `LICENSE` ends with Apache-2.0's appendix boilerplate (`Copyright [yyyy] [name of copyright owner]`), which is part of the license text and stays verbatim. The project's own copyright statement (a line in `NOTICE.md` and/or source headers) is not written yet and needs the author's choice of name.
- **Core findings of the D19 audit that 1.2.0 does not fix** (all MINOR, all replayed; each needs a design decision or is rare): `approve` is accepted for a stage that is already done or uncertain and then stays armed, so one extra execution is released after an artifact A→B→A round trip; a stage id removed from the spec while uncertain leaves the task complete with that stage still `uncertain`; SIGTERM after the last stage but before exit rewrites a finished task as `interrupted` (the next run heals it without re-executing); a `task.json` that is valid JSON of the wrong shape crashes with a traceback instead of exit 64; `approve` takes no run lock and can bind a half-written artifact (it fails closed).
- **Finding of the second audit that is documented, not fixed** (replayed; MINOR): the overlap refusal is decided once, at load, from the symlinks that exist at that moment, so a stage that creates `ln -sfn task.json alias` after the first run makes the next `run` refuse the whole task with exit 64 (the refusal is reported, nothing is run).
- **Authoritative trademark checks (USPTO, EUIPO, DPMA).** Only non-authoritative checks were done: no GitHub repository or user, PyPI package or npm package of the same name, `makeextreme.com` returned no whois match, and a web search found no brand of that name. The official registers were not searched. They are needed before any step that makes the name harder to change, such as a PyPI release.

## Candidate (not decided)

The order is a suggestion, not a plan.

- CI on GitHub Actions. Worth reusing from Longhaul's CI: check out the full history, and keep pytest's temporary directory off `/tmp`.
- Keep the vendored `makeextreme/secret_scan.py` in step with Longhaul's copy ([NOTICE.md](NOTICE.md)).
- A second real customer: the `grill-me` cron. The first is the video pipeline (AC10).
- A PyPI release, only after the items above and the trademark checks (D15).
- A read-only command that reports, for each finished stage, whether it is still valid and why. Not built.
- An expiry for approvals. Not built.
- A threat model and an interface contract shared with Longhaul. [Longhaul's roadmap](https://github.com/dacheng-lu/longhaul/blob/main/ROADMAP.md) plans a threat model and a host adapter contract of its own and does not mention makeextreme; whether the two meet is undecided.
- **A 2.0 direction: a sandbox provider and per-stage capabilities.** Proposed, not decided, not scheduled; design only, no code. [docs/proposals/trust-substrate-2.0.md](docs/proposals/trust-substrate-2.0.md) describes the provider interface, capability declarations, effect classes, a credential broker, leases and shadow mode. It is conditional on Longhaul's v1.3 measurement: if that shows no benefit, the direction is withdrawn.

The last three came from a plan shared on 2026-11-01. Only the output-verification gap in it was measured, and that became 1.1.0.

## Not planned

- A scheduler, a model router, a UI, an MCP registry, several hosts at once, parallel stages inside one task, cloud sync ([ARCHITECTURE.md](ARCHITECTURE.md) §4), and a watchdog or restart daemon (D12): a cron tick only launches the runner and reports.
- Checking that the host is isolated, and knowing who typed `approve`. Both belong to the host; `approve` cannot tell, and the [README](README.md) says so under Boundaries.
- Orchestrating reviews, re-planning on the fly, a store of lessons, hook adapters. They are not what a floor under a pipeline does; if they belong anywhere, it is the layer above.
