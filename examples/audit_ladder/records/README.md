# Audit record stages (offline)

An optional companion to the existing audit ladder. It validates a reviewed local
bundle, writes a separate `validated.json` snapshot and derives `report.md`.
It does not run hunters, execute target code, or implement Cloudflare's schema.
The original ladder and runner are unchanged.

```bash
python examples/audit_ladder/records/new_task.py /path/to/bundle /path/to/new-task
python -m makeextreme run /path/to/new-task
python examples/audit_ladder/records/demo.py --longhaul /path/to/longhaul
python -m unittest discover -s tests -p 'test_audit_records.py'
```

The bundle contains `scope.json` (full base/head commit IDs), `records.json`
(version 1, matching scope, coverage and findings), and `evidence/`.
See `demo.py` for a complete synthetic input and `audit_records.py` for enforced
fields. Checked coverage needs evidence. Resolved findings need distinct author
and reviewer labels, evidence, and a reason. `needs_validation` has no severity.
Evidence references contain a relative path and SHA-256; missing, escaped or
changed evidence is refused. Source commits are caller-pinned labels, not fetched
or independently verified against a remote repository.

Each stage owns a different output; shared evidence, scope and checker code are
explicit dependencies. Invalid input stops the pipeline before rendering a new
report. Old outputs may remain after a failed run: never consume them without a
successful current run and handoff check. Exit 0 means record consistency, not
zero vulnerabilities or complete coverage. Reports preserve unresolved counts.

The demo kills its own runner during report creation, resumes, checks stage
start counts, checks a Longhaul handoff, mutates the report, repairs it, then
changes the source scope and requires rejection. No target/model/network access.

## Attribution and boundaries

Inspired by [Cloudflare security-audit-skill](https://github.com/cloudflare/security-audit-skill/tree/c1c8a8c1471069fb0e188eeaff69b8e8db6564a8):
coverage-led work, separate verification, three verdict states. No upstream code
is bundled; these local validators are not its validators. For a full Cloudflare
audit, use its pinned workflow and Node validators separately, with the required
OS sandbox. Reviewer strings do not authenticate identities. Local hashes do not
prove observations true. This helper assumes a trusted, quiescent local bundle;
it is not a race-resistant sandbox or a credential boundary.
