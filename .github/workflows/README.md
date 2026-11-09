# CI workflows

Four workflow files live in `.github/workflows/`. GitHub only executes `.yml`/`.yaml`
files there, so this Markdown file documents them and triggers nothing.

## The four files

| File | Triggers | Purpose |
| --- | --- | --- |
| [verify-recovery.yml](./verify-recovery.yml) | `push` to `main` and `fix/refuse-mismatched-proc`; `pull_request` with a path filter on `makeextreme/**`, `tests/**`, `examples/longhaul_recovery/**`, `README.md` and `.github/workflows/verify-recovery.yml`; `workflow_dispatch` | `ubuntu-latest`, `timeout-minutes: 20`, matrix Python `3.11` and `3.14`. Second checkout of `dacheng-lu/longhaul` at commit `22e9a19c99e9b9daf05a88a0efae05b565d6469a` into `_longhaul_demo`, a `/proc/self` namespace check, the full test suite (`python -m unittest discover -s tests -p 'test_*.py'`), then `examples/longhaul_recovery/demo.py --longhaul _longhaul_demo`. |
| [platform.yml](./platform.yml) | `push` to `main`; `pull_request` without a path filter | Matrix `ubuntu-latest` and `windows-latest` x Python `3.11` and `3.13`. Only `tests/test_platform.py`, plus one CLI abort check that expects exit code 64 (single-line `Linux-only` refusal on Windows, `task directory does not exist` on POSIX). Its own comment states that the full Linux suite is deliberately not run there. |
| [joint-audit.yml](./joint-audit.yml) | `pull_request` with a path filter on `examples/audit_ladder/records/**`, `tests/test_audit_records.py` and `.github/workflows/joint-audit.yml`; `workflow_dispatch` | `ubuntu-latest`, `timeout-minutes: 5`, Python `3.11`. Second checkout of `dacheng-lu/longhaul` at commit `33226119dbaec9c0432911e25389a451af9ad83d` into `_longhaul_audit`, then `tests/test_audit_records.py` and `examples/audit_ladder/records/demo.py --longhaul _longhaul_audit`. |
| [ci.yml](./ci.yml) | `push` (all branches) and `pull_request` | The canonical CI: `ubuntu-latest`, `timeout-minutes: 20`, matrix Python `3.11` and `3.14`, `fetch-depth: 0`, `permissions: contents: read`. Sets `TMPDIR`/`TEMP`/`TMP` to `${{ github.workspace }}/../mx-tmp` (outside the checkout, not the shared system temp directory), creates that directory before the tests and refuses to run if `TMPDIR` is empty, relative, `/tmp` or inside the checkout. Then the full suite: `python -m unittest discover -s tests -p 'test_*.py'`. No `continue-on-error`, no `|| true`. |

## Duplicate run

`verify-recovery.yml` already runs the full suite on both `push` and `pull_request`
(plus `workflow_dispatch`), so the same suite is covered twice for the pushes and pull
requests that hit both sets of triggers. `ci.yml` is the canonical CI. `verify-recovery.yml`
stays unchanged, because it additionally runs the Longhaul demo
(`examples/longhaul_recovery/demo.py`) against its pinned checkout, which the canonical
CI does not do. Whether `verify-recovery.yml` is trimmed back to paths that only it can
test is left to the owner.

## Measured on 2026-11-09

All four observations below are local measurements taken for this document under WSL or
on the Windows host. None of them is a CI run time, and no workflow run is implied by them.

- 244 tests, OK. LF clone (fresh `git clone` of the reference repository; `file` reports
  no CRLF line terminators), WSL Ubuntu, Python 3.14.4, `TMPDIR` outside the checkout:
  `Ran 244 tests in 102.092s` followed by `OK`, exit 0.
- 14 failures in the CRLF working tree. The suite started directly from the CRLF working
  copy over `/mnt/c`, `TMPDIR` outside the checkout: `Ran 244 tests in 144.618s` followed
  by `FAILED (failures=14)`, exit 1. The cause is CRLF: `examples/cron_tick.sh` line 15
  holds the bytes `set -u\r\n`, and the failures read
  `examples/cron_tick.sh: 15: set: Illegal option -`.
- 108 collected tests with 53 failures and 11 errors, native Windows run, host Python
  3.11.16, working tree copied from the reference outside the repository:
  `Ran 108 tests in 140.255s` followed by `FAILED (failures=53, errors=11)`, exit 1.
- TMPDIR recursion when `HOME` lies inside the checkout. The same LF clone with `TMPDIR`
  inside the checkout: `Ran 244 tests in 97.220s` followed by `FAILED (failures=1)`,
  exit 1, failing test
  `test_the_mutant_harness_creates_its_work_directory_instead_of_crashing`. The cause was
  reproduced directly with `HOME=<checkout>/.tmp/h TMPDIR=<checkout>/.tmp python3
  examples/video_pipeline/ac10_mutants.py --source /nonexistent/x.mp4`, which ends in
  `RecursionError: maximum recursion depth exceeded` inside `shutil.copytree` ->
  `fnmatch.filter`.

## Open decisions

1. Should `verify-recovery.yml` be trimmed back now that `ci.yml` is the canonical CI?
2. Should a `.gitattributes` with `eol=lf` be introduced so working trees stay LF?
3. Should the ROADMAP candidate for this CI work be marked done after the merge?
