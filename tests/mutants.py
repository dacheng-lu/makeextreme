#!/usr/bin/env python3
"""One-mutant-at-a-time replay for makeextreme's tests (stdlib only).

usage:  python tests/mutants.py list
        python tests/mutants.py all                  every mutant, controls cached per selector (foreground, ~3 min)
        python tests/mutants.py <name> [--control]   one mutant; --control runs its selectors on an UNMUTATED copy

Each call copies the repository WITH .git into a temporary directory whose name does not contain the
project name, applies the edit by exact string replacement (the replacement count is asserted, so a
harness that no longer matches the code says so instead of testing nothing), runs the selected tests in
the FOREGROUND and prints one RESULT line. A mutant counts as caught only when its control is green and
the mutant is red; a red control means the environment, not the test, is at fault.
"""
import os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = "makeextreme/core.py"
SCAN = "makeextreme/secret_scan.py"
M = {}


def mut(name, rel, old, new, selector, what):
    """selector = (test file, -k pattern or None)"""
    M[name] = (rel, old, new, selector, what)


CORE_T, FP, APP, SEC, LOCK = ("test_core.py", "test_fingerprint.py", "test_approval.py",
                              "test_secrets.py", "test_lock.py")

mut("C1_exit0_is_done", CORE, 'ok = rc == 0 and chk.returncode == 0', 'ok = rc == 0', (CORE_T, "ac2"),
    "exit code 0 alone counts as done (the check is ignored)")
mut("C2_skip_always", CORE, 'if s.get("digest") == fp:\n                t.log("skip"', 'if True:\n                t.log("skip"',
    (FP, None), "a done stage is skipped whatever changed")
mut("C3_fp_ignores_deps", CORE, '"check": sp["check"], "deps": deps}', '"check": sp["check"], "deps": {}}',
    (FP, None), "the stage fingerprint ignores the content of its deps")
mut("C4_fp_ignores_check", CORE, '"check": sp["check"], "deps": deps}', '"check": "", "deps": deps}',
    (FP, None), "the stage fingerprint ignores the check command")
mut("C5_fp_ignores_run", CORE, 'doc = {"run": sp["run"],', 'doc = {"run": "",', (FP, None),
    "the stage fingerprint ignores the run command")
mut("C6_dir_dep_by_name", CORE, 'one = _path_hash(os.path.join(p, n), stack | {real}, memo)',
    'one = "x"', (FP, "directory"),
    "a directory dep is hashed by file names, not content")
mut("A1_approval_any_digest", CORE, 'and r.get("digest") == digest:', 'and True:', (APP, "artifact"),
    "an approval is not bound to the artifact digest")
mut("A2_approval_any_stage", CORE, 'isinstance(r, dict) and r.get("stage") == sid and',
    'isinstance(r, dict) and r.get("stage") is not None and', (APP, "stage_id"),
    "an approval is not bound to the stage id")
mut("A3_no_approval_needed", CORE, '        if sp.get("approval") and not approved(d, sid, fp):', '        if False:',
    (APP, "no_record"), "an approval stage runs without any approval record")
mut("A4_crash_reruns", CORE, '        if s["status"] in ("running", "interrupted") and sp.get("approval"):',
    '        if False:', (APP, "never_rerun"), "a crashed irreversible stage is re-run on its own")
mut("A5_uncertain_forgotten", CORE, '        if s["status"] == "uncertain":\n            return t.halt',
    '        if False:\n            return t.halt', (APP, "never_rerun"), "an uncertain stage stops being uncertain on the next run")
mut("A6_failed_irreversible_retried", CORE, '        if not ok and sp.get("approval"):', '        if False:',
    (APP, "FailedIrreversible"), "a failed approval stage is run again by a plain run")
mut("A7_approve_missing_artifact", CORE, '    if "missing" in hashes.values():', '    if False:',
    (APP, "cannot_bind"), "approve records an approval for an artifact that does not exist")
mut("A8_approve_ordinary_stage", CORE, '    if sp is None or not sp.get("approval"):', '    if sp is None:',
    (APP, "cannot_bind"), "approve accepts a stage that has no approval")
mut("A9_no_deps_accepted", CORE, '        if sp.get("approval") and not deps:', '        if False:',
    (APP, "without_deps"), "an approval stage without deps is accepted")
mut("A10_torn_approval_line_crashes", CORE, '            continue  # a line torn by a crash is not an approval (and not a reason to crash)',
    '            raise', (APP, "torn_or_foreign"), "a torn line in approvals.jsonl crashes the runner instead of being ignored")
mut("A11_nondict_line_crashes", CORE, '        if isinstance(r, dict) and r.get("stage") == sid and r.get("digest") == digest:',
    '        if r.get("stage") == sid and r.get("digest") == digest:', (APP, "torn_or_foreign"),
    "a non-object line in approvals.jsonl crashes the runner")
mut("R1_resolve_done_unchecked", CORE, '            if chk.returncode != 0:\n                print("refused: the stage\'s check',
    '            if False:\n                print("refused: the stage\'s check', (APP, "resolve_done"),
    "resolve --done does not require the check to pass")
mut("R2_resolve_any_stage", CORE, '        if s is None or sp is None or s["status"] != "uncertain":',
    '        if s is None or sp is None:', (APP, "resolve"), "resolve accepts a stage that is not uncertain")
mut("O1_reap_by_env_off", CORE, '                if needle not in f.read().split(b"\\0"):\n                    continue',
    '                continue', (APP, "lost_pgid"), "orphans are no longer found by the run id")
mut("T1_sigterm_leaves_child", CORE, '                os.killpg(p.pid, signal.SIGTERM)', '                pass',
    (CORE_T, "ac7"), "SIGTERM does not stop the stage's process group")
mut("S1_no_secret_refusal", CORE, '    if hits:  # F10', '    if False:  # F10', (SEC, "refuses_completion"),
    "a credential in the record does not refuse completion")
mut("S2_journal_not_scanned", CORE, '("task.json", "journal.jsonl", "approvals.jsonl")', '("task.json", "approvals.jsonl")',
    (SEC, "journal"), "the journal is not scanned")
mut("L1_shared_lock", CORE, 'fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)', 'fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)',
    (LOCK, None), "the run lock is shared, so nothing is excluded")
mut("L2_no_lock", CORE, '        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n    except BlockingIOError:',
    '        pass\n    except BlockingIOError:', (LOCK, None), "the run lock is never taken")
mut("D1_damaged_state_traceback", CORE, '            except ValueError as e:\n                raise SpecError(f"task.json',
    '            except KeyError as e:\n                raise SpecError(f"task.json', (CORE_T, "damaged"),
    "a damaged task.json escapes as a traceback")
mut("D2_invalid_json_traceback", CORE, '    except ValueError as e:\n        raise SpecError(f"invalid stages.json: not valid JSON',
    '    except KeyError as e:\n        raise SpecError(f"invalid stages.json: not valid JSON', (CORE_T, "clean_refusal"),
    "an invalid stages.json escapes as a traceback")
mut("D3_missing_dir_traceback", CORE, '    if not os.path.isdir(d):\n        raise SpecError(f"task directory', '    if False:\n        raise SpecError(f"task directory',
    (CORE_T, "clean_refusal"), "a missing task directory escapes as a traceback")
mut("D4_lock_file_beside_bad_spec", CORE, '        load_spec(d)  # refuse a bad task before the lock file is created next to it', '        pass',
    (CORE_T, "clean_refusal"), "a lock file is created next to a task that is refused anyway")
mut("V1_duplicate_ids", CORE, 'if not (isinstance(sid, str) and sid) or sid in seen:', 'if not (isinstance(sid, str) and sid):',
    (CORE_T, "stage_ids"), "duplicate stage ids are accepted")

FIND = "test_audit_findings.py"
mut("E1_signal_undoes_done_stage", CORE,
    'running = cur["sid"] if cur["sid"] and t.st(cur["sid"])["status"] == "running" else None',
    'running = cur["sid"]', (FIND, "SigtermBetweenStages"),
    "a SIGTERM between two stages marks the stage that just finished as interrupted")
mut("E2_interrupted_not_reaped", CORE,
    'if s["status"] in ("running", "interrupted"):  # the previous runner died or was stopped mid-stage',
    'if s["status"] == "running":  # the previous runner died or was stopped mid-stage',
    (FIND, "InterruptedStageIsReaped"), "what an interrupted ordinary stage left behind is not killed before the rerun")
mut("E3a_check_utf8_in_run", CORE, 'text=True, errors="replace")\n        ok =', 'text=True)\n        ok =',
    (FIND, "NonUtf8Check"), "non-UTF-8 check output crashes the runner")
mut("E3b_check_utf8_in_resolve", CORE, 'text=True, errors="replace")\n            if chk.returncode != 0:',
    'text=True)\n            if chk.returncode != 0:', (FIND, "NonUtf8Check"), "non-UTF-8 check output crashes resolve --done")
mut("E4a_symlink_by_text_only", CORE, 'inner = _path_hash(target, stack, memo) if os.path.exists(target) else "dangling"',
    'inner = ""', (FIND, "SymlinkDeps"), "a symlink is hashed by its text, not by what it points to")
mut("E4b_symlink_cycle_unguarded", CORE, '        if real in stack:\n            return "cycle"',
    '        if False:\n            return "cycle"', (FIND, "SymlinkDeps"), "a symlink cycle recurses without end")
mut("E4c_dangling_link_is_an_artifact", CORE, '    if os.path.islink(p) and not os.path.exists(p):\n        return "missing"',
    '    if False:\n        return "missing"', (FIND, "SymlinkDeps"), "a dangling symlink can be approved as an artifact")
mut("E5_torn_tail_glues_next_entry", CORE, 'torn = f.read(1) != b"\\n"', 'torn = False', (FIND, "TornTails"),
    "an entry appended after a torn line is glued to the fragment and lost")
mut("E8a_unreadable_file_traceback", CORE, '                memo[real] = _file_hash(p)\n            except OSError as e:',
    '                memo[real] = _file_hash(p)\n            except KeyError as e:', (FIND, "UnreadableDep"),
    "an unreadable dep file escapes as a traceback")
mut("E8b_spec_error_escapes_run", CORE, '            return fn(Task(d))\n        except SpecError as e:',
    '            return fn(Task(d))\n        except KeyError as e:', (FIND, "UnreadableDep"),
    "a SpecError raised while running escapes as a traceback")
mut("E9_approve_hashes_twice", CORE, 'digest = fingerprint(d, sp, hashes)', 'digest = fingerprint(d, sp)',
    (FIND, "ApproveHashesOnce"), "approve binds a second hash instead of the one it showed")
mut("X1_approvals_not_scanned", CORE, '("task.json", "journal.jsonl", "approvals.jsonl")', '("task.json", "journal.jsonl")',
    (FIND, "x1"), "approvals.jsonl is not scanned for credentials")
mut("X2_pgid_reuse_guard_off", CORE, 'if pg and pg not in killed and starttime(pg) == s.get("pg_start"):',
    'if pg and pg not in killed:', (FIND, "x2"), "a recorded pgid is killed even when the pid was reused")
mut("X3_pgid_fallback_off", CORE, 'if pg and pg not in killed and starttime(pg) == s.get("pg_start"):', 'if False:',
    (FIND, "x3"), "a stage that cleared its environment escapes the reaper")
mut("X4_attempts_constant", CORE, 's.update(status="running", attempts=s["attempts"] + 1,', 's.update(status="running", attempts=1,',
    (FIND, "x4"), "the attempts counter never counts")
mut("W1_atomic_write_leaves_temp", CORE, '            os.unlink(tmp)', '            pass', (FIND, "AtomicWriteCleanup"),
    "a failed atomic write leaves its temp file behind")

mut("N1_failed_approval_saved_as_failed", CORE, '("uncertain" if sp.get("approval") else "failed")', '"failed"',
    (FIND, "FailedApprovalIsNeverPersisted"), "a failed approval stage is first written as failed (a kill then repeats it)")
mut("N12_atomic_write_signal_window", CORE, 'held = signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGTERM, signal.SIGINT))',
    'held = signal.pthread_sigmask(signal.SIG_SETMASK, ())', (FIND, "AtomicWriteSignalWindow"),
    "a signal right after mkstemp leaves the temp file behind")
mut("N2a_link_text_strict_utf8", CORE, '("link:" + text).encode("utf-8", "surrogateescape")', '("link:" + text).encode("utf-8")',
    (FIND, "LinkTextAndDisplay"), "a symlink text that is not UTF-8 crashes the hashing")
mut("N2b_link_shown_as_text", CORE, 'return hashlib.sha256(("link:" + text).encode("utf-8", "surrogateescape")).hexdigest()',
    'return "link:" + text', (FIND, "LinkTextAndDisplay"), "a symlink is shown and bound by its text only")
mut("N3_recursion_unguarded", CORE, '    except RecursionError:\n        raise SpecError(f"dependency {rel!r} is nested too deeply to hash")',
    '    except KeyError:\n        raise SpecError(f"dependency {rel!r} is nested too deeply to hash")', (FIND, "n3_a_dep"),
    "a very deep dep tree escapes as a traceback")
mut("N4_no_memo", CORE, '        if real in memo:\n            return memo[real]', '        if False:\n            return memo[real]',
    (FIND, "n4_links"), "links fanning out to the same directories are hashed once per path (exponential)")
mut("Y2_interrupt_event_name", CORE, '"recovered_from_crash" if s["status"] == "running" else "recovered_from_interrupt"',
    '"recovered_from_crash"', (FIND, "InterruptedStageIsReaped"), "recovery after an interrupt is logged as a crash")
mut("Y3_cycle_guard_parent_only", CORE, 'stack | {real}, memo)\n            h.update', 'frozenset({real}), memo)\n            h.update',
    (FIND, "y3"), "the cycle guard remembers only the parent directory")
mut("Y7_name_encode_strict", CORE, 'h.update(n.encode("utf-8", "surrogateescape")', 'h.update(n.encode("utf-8")',
    (FIND, "y7"), "a file name that is not UTF-8 crashes the hashing")
mut("N5_refusal_not_recorded", CORE, '            t.state["status"] = "refused"\n            t.save()\n            t.log("refused", stage=sid, reason=str(e))\n            raise',
    '            raise', (FIND, "UnreadableDep"), "a dep that turns unreadable mid-run leaves a silent `running`")
mut("N6b_approvals_strict_utf8", CORE, 'with open(approvals_path(d), errors="replace") as f:', 'with open(approvals_path(d)) as f:',
    (FIND, "RecordFilesWith"), "foreign bytes in approvals.jsonl crash the runner")
mut("N6c_records_strict_utf8", CORE, 'with open(p, errors="replace") as f:\n            text = f.read()', 'with open(p) as f:\n            text = f.read()',
    (FIND, "RecordFilesWith"), "foreign bytes in journal.jsonl crash the completion scan")

_controls = {}


def run(name, control, verbose=True):
    rel, old, new, (test_file, pattern), what = M[name]
    work = tempfile.mkdtemp(prefix="mxm-%s-" % name.lower())
    try:
        tree = os.path.join(work, "tree")
        shutil.copytree(REPO, tree, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
        if not control:
            path = os.path.join(tree, rel)
            text = open(path, encoding="utf-8").read()
            if text.count(old) != 1:
                print("RESULT %s SUBSTITUTION FAILED: %r occurs %d times (want 1) in %s"
                      % (name, old[:60], text.count(old), rel))
                return 3, ""
            open(path, "w", encoding="utf-8").write(text.replace(old, new))
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", test_file, "-f"]
        if pattern:
            cmd += ["-k", pattern]
        r = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, timeout=240,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        out = (r.stdout + r.stderr).splitlines()
        red = next((l[:110] for l in out if l.startswith(("FAIL:", "ERROR:"))), "")
        tail = next((l for l in reversed(out) if l.startswith(("OK", "FAILED", "Ran"))), "")
        if verbose:
            print("RESULT %s %s rc=%d | %s | %s" % (name, "CONTROL" if control else "MUTANT", r.returncode, tail, red))
        return r.returncode, red
    except subprocess.TimeoutExpired:
        print("RESULT %s %s TIMEOUT (>240 s)" % (name, "CONTROL" if control else "MUTANT"))
        return 124, "timeout"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv):
    if not argv or argv[0] == "list":
        for n, (rel, _o, _n, sel, what) in M.items():
            print("%-30s %s  [%s%s]" % (n, what, sel[0], " -k " + sel[1] if sel[1] else ""))
        return 0
    if argv[0] == "all":
        rows, bad = [], []
        for name in M:
            sel = M[name][3]
            if sel not in _controls:
                _controls[sel] = run(name, True, verbose=False)[0]
            mrc, red = run(name, False, verbose=False)
            ctl = _controls[sel]
            verdict = "RED" if (ctl == 0 and mrc == 1) else ("SURVIVES" if (ctl == 0 and mrc == 0) else "CHECK")
            rows.append("TABLE %-30s control rc=%s mutant rc=%s %s%s" % (name, ctl, mrc, verdict, "  | " + red if red else ""))
            if verdict != "RED":
                bad.append(name)
        print("\n".join(rows))
        print("TABLE SUMMARY: %d mutants, %d red, not red: %s" % (len(rows), len(rows) - len(bad), bad or "none"))
        return 0
    name = argv[0]
    if name not in M:
        print("unknown mutant %r (try: list)" % name)
        return 2
    run(name, "--control" in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
