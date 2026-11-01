# Roadmap

makeextreme keeps no schedule. This page says what has been released, what is still owed, what is only a candidate, and what is deliberately not planned. **It is a direction, not a commitment: nothing here has a date, and a "Candidate" item is not decided.** State of `main` at `eee8c0c` (version 1.1.0).

This page is in English; the design record it points to ([ARCHITECTURE.md](ARCHITECTURE.md), decisions D1 to D20) is in Chinese. 本页使用英语，设计记录使用中文。 Diese Seite ist auf Englisch, das Entwurfsprotokoll auf Chinesisch.

## Released

- **1.1.0** (2026-11-01): a stage may declare `outputs`; their content is recorded after the run and checked before every skip (design record D20, acceptance AC11). It closes a measured gap: on 1.0.0, deleting the last stage's output left `run` exiting 0 with a `skip` and no file. A stage without `outputs` keeps its 1.0.0 fingerprint, so existing tasks resume unchanged.
- **1.0.0** (2026-11-01): the runner (crash resume, "done" decided from the artifact, approvals bound to the artifact and spent by one execution, one `flock`), the video-pipeline example (AC10), the Hermes host example (AC9), the cron tick launcher and the three-language [README](README.md). Published before its final independent audit (D19).

No tags and no GitHub Releases exist yet.

## Owed

- **The deep audit (D19).** Version 1.0.0 was published once without its final independent audit. The audit is owed and must cover everything added after the M1 core: the examples, the cron tick, the README tests and the 1.1.0 change. The auditor is not chosen yet.
- **Authoritative trademark checks (USPTO, EUIPO, DPMA).** Only non-authoritative checks were done: no GitHub repository or user, PyPI package or npm package of the same name, `makeextreme.com` returned no whois match, and a web search found no brand of that name. The official registers were not searched. They are needed before any step that makes the name harder to change, such as a PyPI release.

## Candidate (not decided)

The order is a suggestion, not a plan.

- CI on GitHub Actions. Worth reusing from Longhaul's CI: check out the full history, and keep pytest's temporary directory off `/tmp`.
- Keep the vendored `makeextreme/secret_scan.py` in step with Longhaul's copy ([NOTICE.md](NOTICE.md)).
- A second real customer: the `grill-me` cron. The first is the video pipeline (AC10).
- A PyPI release, only after the items above and the trademark checks (D15).
- A read-only command that reports, for each finished stage, whether it is still valid and why. Not built.
- An expiry for approvals. Not built.
- A threat model and an interface contract shared with Longhaul (see [Longhaul's roadmap](https://github.com/dacheng-lu/longhaul/blob/main/ROADMAP.md)).

The last three came from a plan shared on 2026-11-01. Only the output-verification gap in it was measured, and that became 1.1.0.

## Not planned

- A scheduler, a model router, a UI, an MCP registry, several hosts at once, parallel stages inside one task, cloud sync ([ARCHITECTURE.md](ARCHITECTURE.md) §4), and a watchdog or restart daemon (D12): a cron tick only launches the runner and reports.
- Checking that the host is isolated, and knowing who typed `approve`. Both belong to the host; `approve` cannot tell, and the [README](README.md) says so under Boundaries.
- Orchestrating reviews, re-planning on the fly, a store of lessons, hook adapters. They are not what a floor under a pipeline does; if they belong anywhere, it is the layer above.
