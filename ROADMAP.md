# Roadmap

makeextreme keeps no schedule. This page says what has been released, what is still owed, what is only a candidate, and what is deliberately not planned. **It is a direction, not a commitment: nothing here has a date, and a "Candidate" item is not decided.** State: version 1.1.1 (a page cannot name the commit that contains it; the version is what the tests check).

This page is in English; the design record it points to ([ARCHITECTURE.md](ARCHITECTURE.md), decisions D1 to D20) is in Chinese. 本页使用英语，设计记录使用中文。 Diese Seite ist auf Englisch, das Entwurfsprotokoll auf Chinesisch.

## Released

- **1.1.1** (2026-11-01): fixes from the deep audit D19, which was done by an ollama model that had first been calibrated on a planted defect (deepseek-v4.1-flash:1017 found it in 3 of 3 runs; one planted defect is one sample, so a PASS means "found nothing with an auditor of measured but narrow strength", not "nothing there"). The audit found 0 blockers, 0 major, 12 minor and 9 plan items; every counterexample was replayed by the maintainer. This release fixes: a declared dependency or output that overlaps the runner's own record (`task.json`, `journal.jsonl`, `approvals.jsonl`, `lock`), the task directory or another stage's output is refused with exit 64 before anything runs (D21; it used to re-run on every run and leave an approval stage stuck at exit 5); two tests that stayed green without the mechanism they name, and a mutant that went red by a crash instead of its reason; `cron_tick.sh` started through a symlink, a missing interpreter reported as a refused task (now exit 69), and advice lines that could not be pasted into a shell; `ac10_mutants.py` on a machine without `~/ac10work`; and the documents that disagreed with the code (test counts, the README's AC10 command, exit code 64's causes, the `resolve --retry` wording). It also adds an example, `examples/audit_ladder/` (design record D22): an audit of a git range as stages with the expensive model behind an approval bound to its prompt; tested only with stand-in models.
- **1.1.0** (2026-11-01): a stage may declare `outputs`; their content is recorded after the run and checked before every skip (design record D20, acceptance AC11). It closes a measured gap: on 1.0.0, deleting the last stage's output left `run` exiting 0 with a `skip` and no file. A stage without `outputs` keeps its 1.0.0 fingerprint, so existing tasks resume unchanged.
- **1.0.0** (2026-11-01): the runner (crash resume, "done" decided from the artifact, approvals bound to the artifact and spent by one execution, one `flock`), the video-pipeline example (AC10), the Hermes host example (AC9), the cron tick launcher and the three-language [README](README.md). Published before its final independent audit (D19).

No tags and no GitHub Releases exist yet.

## Owed

- **The project's own copyright line.** `LICENSE` ends with Apache-2.0's appendix boilerplate (`Copyright [yyyy] [name of copyright owner]`), which is part of the license text and stays verbatim. The project's own copyright statement (a line in `NOTICE.md` and/or source headers) is not written yet and needs the author's choice of name.
- **Core findings of the D19 audit that 1.1.1 does not fix** (all MINOR, all replayed; each needs a design decision or is rare): `approve` is accepted for a stage that is already done or uncertain and then stays armed, so one extra execution is released after an artifact A→B→A round trip; `resolve --retry` after `"approval"` was removed from the spec while the stage was uncertain executes without an approval on record; a stage id removed from the spec while uncertain leaves the task complete with that stage still `uncertain`; SIGTERM after the last stage but before exit rewrites a finished task as `interrupted` (the next run heals it without re-executing); a `task.json` that is valid JSON of the wrong shape crashes with a traceback instead of exit 64; `resolve --done` after a spec edit stamps the new command's fingerprint so the new command never runs; `approve` takes no run lock and can bind a half-written artifact (it fails closed).
- **Findings of the second audit of 1.1.1 that are documented, not fixed** (replayed; MINOR): the overlap refusal is decided once, at load, from the symlinks that exist at that moment, so a stage that creates `ln -sfn task.json alias` after the first run makes the next `run` refuse the whole task with exit 64 (the refusal is reported, nothing is run); the check cannot know whether a stage that declares an output another stage also declares ever writes it, so it refuses both (a spec that 1.1.0 accepted).
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

The last three came from a plan shared on 2026-11-01. Only the output-verification gap in it was measured, and that became 1.1.0.

## Not planned

- A scheduler, a model router, a UI, an MCP registry, several hosts at once, parallel stages inside one task, cloud sync ([ARCHITECTURE.md](ARCHITECTURE.md) §4), and a watchdog or restart daemon (D12): a cron tick only launches the runner and reports.
- Checking that the host is isolated, and knowing who typed `approve`. Both belong to the host; `approve` cannot tell, and the [README](README.md) says so under Boundaries.
- Orchestrating reviews, re-planning on the fly, a store of lessons, hook adapters. They are not what a floor under a pipeline does; if they belong anywhere, it is the layer above.
