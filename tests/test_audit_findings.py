"""Findings of the M1 milestone audit (Sonnet, 2026-11-01), each with the test that was red first.

E1 a SIGTERM between two stages undid the stage that had just finished
E2 a child that ignores SIGTERM kept running while the next run started the stage again
E3 non-UTF-8 bytes in a check's output crashed the runner for good
E4 symlinks in `deps` were hashed by their text, so a changed target left an approval valid
E5 a torn last line in approvals.jsonl / journal.jsonl swallowed the next entry
E8 an unreadable dep was a traceback
E9 `approve` hashed twice: the hash shown could differ from the one bound
X1-X4 four mutants that survived the harness
"""
import contextlib, io, json, os, signal, subprocess, sys, time, unittest
from unittest import mock

from support import REPO, TaskCase, gone, mx, mx_start, wait_for

sys.path.insert(0, REPO)
from makeextreme import core  # noqa: E402

KEY = "sk-" + "a1B2c3D4" * 4


def sparse(d, name, gib):
    with open(os.path.join(d, name), "wb") as f:
        f.truncate(gib << 30)


def wait_event(case, d, ev, secs=15):
    end = time.time() + secs
    while time.time() < end:
        if ev in case.events(d):
            return True
        time.sleep(0.02)
    return False


class SigtermBetweenStages(TaskCase):
    """E1: the runner is hashing stage b's 2 GiB dep when SIGTERM arrives; stage a is done."""

    def go(self, a_extra, prepare=lambda d: None):
        spec = [{"id": "a", "run": "echo a >> a.out", "check": "test -s a.out", **a_extra},
                {"id": "b", "run": "echo b >> b.out", "check": "test -s b.out", "deps": ["big"]}]
        d = self.task(spec, {"art": "v1\n"})
        sparse(d, "big", 2)
        prepare(d)
        r = mx_start("run", d)
        self.assertTrue(wait_event(self, d, "end"), "stage a never finished")
        time.sleep(0.3)
        r.send_signal(signal.SIGTERM)
        self.assertEqual(r.wait(), 143)
        return d

    def test_a_finished_ordinary_stage_stays_done_and_is_not_repeated(self):
        d = self.go({})
        self.assertEqual(self.state(d)["stages"]["a"]["status"], "done")
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.lines(d, "a.out"), self.lines(d, "b.out")), (1, 1))

    def test_a_finished_irreversible_stage_does_not_become_uncertain(self):
        def approve(d):
            self.assertEqual(mx("run", d).returncode, 4)
            self.assertEqual(mx("approve", d, "a").returncode, 0)
        d = self.go({"deps": ["art"], "approval": "required"}, approve)
        self.assertEqual(self.state(d)["stages"]["a"]["status"], "done")
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)  # not 5
        self.assertEqual(self.lines(d, "a.out"), 1)


class InterruptedStageIsReaped(TaskCase):
    """E2: after a SIGTERM the stage is `interrupted`; whatever of it still lives is killed before it re-runs."""

    def test_an_orphan_of_an_interrupted_ordinary_stage_is_reaped_before_the_rerun(self):
        d = self.task([{"id": "s", "run": "echo ok >> out", "check": "test -s out"}])
        orphan = subprocess.Popen(["sleep", "60"], start_new_session=True,
                                  env={**os.environ, core.RUN_ID_ENV: "deadbeefdeadbeef"})
        self.addCleanup(lambda: (orphan.poll() is None and orphan.kill(), orphan.wait()))
        self.write(d, "task.json", json.dumps({"status": "interrupted", "stages": {
            "s": {"status": "interrupted", "attempts": 1, "digest": "x", "run_id": "deadbeefdeadbeef"}}}))
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        try:  # it is our child: waiting reaps the zombie, and -9 says it was killed, not that it ended
            code = orphan.wait(timeout=3)
        except subprocess.TimeoutExpired:
            code = None
        self.assertEqual(code, -signal.SIGKILL, "the orphan of the interrupted stage was left running")
        self.assertIn("reaped", self.events(d))
        self.assertEqual(self.lines(d, "out"), 1)

    def test_a_child_that_ignores_sigterm_does_not_run_beside_the_rerun(self):
        run = "trap '' TERM; echo start >> out; sleep 2; echo done >> out"
        d = self.task([{"id": "s", "run": run, "check": "grep -q done out"}])
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "out")))
        r.send_signal(signal.SIGTERM)
        self.assertEqual(r.wait(), 143)
        self.assertEqual(self.state(d)["stages"]["s"]["status"], "interrupted")
        self.assertEqual(mx("run", d).returncode, 0)
        time.sleep(2.6)  # long enough for a surviving first child to write its own `done`
        self.assertEqual(self.read(d, "out").split(), ["start", "start", "done"])


class NonUtf8Check(TaskCase):
    """E3"""

    def test_a_check_that_prints_non_utf8_bytes_still_completes(self):
        d = self.task([{"id": "s", "run": "echo x >> c", "check": "printf '\\377\\376'; test -s c"}])
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.state(d)["stages"]["s"]["status"], "done")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertIn("skip", self.events(d))
        self.assertEqual(self.lines(d, "c"), 1)

    def test_resolve_done_survives_non_utf8_check_output(self):
        run = "echo started >> rs; if [ -f go ]; then echo ok > sent.ok; else sleep 30; fi"
        spec = [{"id": "send", "run": run, "check": "printf '\\377'; test -s sent.ok", "deps": ["art"],
                 "approval": "required"}]
        d = self.task(spec, {"art": "v1\n"})
        mx("run", d)
        mx("approve", d, "send")
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "rs")))
        os.kill(r.pid, signal.SIGKILL)
        r.wait()
        self.assertEqual(mx("run", d).returncode, 5)
        self.write(d, "sent.ok", "ok\n")
        res = mx("resolve", d, "send", "--done")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Traceback", res.stderr)


def send_spec(dep="link.txt"):
    return [{"id": "send", "run": "echo sent >> rs", "check": "test -s rs", "deps": [dep], "approval": "required"}]


class SymlinkDeps(TaskCase):
    """E4: a symlink counts by what it points to now, not only by its text."""

    def runs_after(self, d, change):
        self.assertEqual(mx("run", d).returncode, 0)
        before = self.lines(d, "r")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "r"), before, "an unchanged tree must skip")
        change()
        self.assertEqual(mx("run", d).returncode, 0)
        return self.lines(d, "r") - before

    SPEC = [{"id": "z", "run": "echo z >> r", "check": "test -s r", "deps": ["dep"]}]

    def test_a_file_symlink_dep_follows_its_target(self):
        d = self.task(self.SPEC, {"real.txt": "1\n"})
        os.symlink("real.txt", os.path.join(d, "dep"))
        self.assertEqual(self.runs_after(d, lambda: self.write(d, "real.txt", "2\n")), 1)

    def test_a_symlink_inside_a_dep_directory_follows_its_target(self):
        d = self.task(self.SPEC, {"outside/f": "1\n", "dep/own": "x\n"})
        os.symlink(os.path.join(d, "outside", "f"), os.path.join(d, "dep", "link"))
        self.assertEqual(self.runs_after(d, lambda: self.write(d, "outside/f", "2\n")), 1)

    def test_a_directory_symlink_inside_a_dep_directory_follows_its_target(self):
        d = self.task(self.SPEC, {"other/f": "1\n", "dep/own": "x\n"})
        os.symlink(os.path.join(d, "other"), os.path.join(d, "dep", "more"))
        self.assertEqual(self.runs_after(d, lambda: self.write(d, "other/f", "2\n")), 1)

    def test_a_symlink_cycle_does_not_hang_or_crash(self):
        d = self.task(self.SPEC, {"dep/f": "1\n"})
        os.symlink(".", os.path.join(d, "dep", "loop"))
        os.symlink(os.path.join(d, "dep"), os.path.join(d, "dep", "again"))
        self.assertEqual(self.runs_after(d, lambda: self.write(d, "dep/f", "2\n")), 1)

    def test_an_approval_does_not_survive_a_change_behind_a_symlink(self):
        d = self.task(send_spec(), {"real.txt": "v1\n"})
        os.symlink("real.txt", os.path.join(d, "link.txt"))
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.write(d, "real.txt", "v2, something else\n")
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(self.lines(d, "rs"), 0)

    def test_a_dangling_symlink_is_a_missing_artifact(self):
        d = self.task(send_spec())
        os.symlink("nowhere.txt", os.path.join(d, "link.txt"))
        res = mx("approve", d, "send")
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("does not exist", res.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, "approvals.jsonl")))


class TornTails(TaskCase):
    """E5: a crash can leave a record file without its final newline; the next entry must not be glued to it."""

    def test_an_approval_after_a_torn_approvals_line_is_not_lost(self):
        d = self.task([{"id": "make", "run": "echo v > art", "check": "test -s art"},
                       {"id": "send", "run": "echo sent >> rs", "check": "test -s rs", "deps": ["art"],
                        "approval": "required"}])
        self.assertEqual(mx("run", d).returncode, 4)
        with open(os.path.join(d, "approvals.jsonl"), "a") as f:
            f.write('{"t": 1.5, "stage": "sen')  # no newline
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0, "the approval was glued to the torn fragment and lost")
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_a_journal_entry_after_a_torn_journal_line_is_not_lost(self):
        d = self.task([{"id": "s", "run": "echo x >> c", "check": "test -s c"}])
        self.write(d, "journal.jsonl", '{"t": 1.5, "ev": "sta')  # no newline
        self.assertEqual(mx("run", d).returncode, 0)
        parsed, bad = [], 0
        for line in self.read(d, "journal.jsonl").splitlines():
            try:
                parsed.append(json.loads(line)["ev"])
            except ValueError:
                bad += 1
        self.assertEqual(bad, 1, "exactly the torn fragment may be unreadable")
        self.assertEqual(parsed, ["start", "end"])


class UnreadableDep(TaskCase):
    """E8"""

    def test_an_unreadable_dep_is_a_clean_refusal_for_run_and_approve(self):
        if os.geteuid() == 0:
            self.skipTest("root reads everything; an unreadable file cannot be built")
        d = self.task(send_spec("secret.txt"), {"secret.txt": "x\n"})
        os.chmod(os.path.join(d, "secret.txt"), 0)
        for cmd in (("run", d), ("approve", d, "send")):
            res = mx(*cmd)
            self.assertEqual(res.returncode, 64, (cmd[0], res.stderr))
            self.assertIn("secret.txt", res.stderr)
            self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.lines(d, "rs"), 0)


class ApproveHashesOnce(TaskCase):
    """E9: the hash a person is shown is the hash that is bound."""

    def test_approve_reads_each_dep_once_and_binds_what_it_printed(self):
        d = self.task(send_spec("art"), {"art": "v1\n"})
        with mock.patch.object(core, "dep_hash", wraps=core.dep_hash) as spy, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(core.approve(d, "send"), 0)
        self.assertEqual(spy.call_count, 1)
        bound = json.loads(self.read(d, "approvals.jsonl"))["digest"]
        self.assertEqual(bound, core.fingerprint(d, send_spec("art")[0]))


class MoreSurvivors(TaskCase):
    """X1-X4: behaviours the harness could change without any test noticing."""

    def test_x1_a_credential_in_approvals_refuses_completion(self):
        d = self.task([{"id": "s", "run": "echo ok > ok", "check": "test -s ok"}])
        self.write(d, "approvals.jsonl", json.dumps({"stage": "other", "digest": "d", "by": KEY}) + "\n")
        res = mx("run", d)
        self.assertEqual(res.returncode, 6, res.stderr)
        self.assertNotIn(KEY, res.stdout + res.stderr)
        self.assertEqual([h["file"] for h in self.state(d)["secret_hits"]], ["approvals.jsonl"])

    def test_x2_a_recorded_pgid_that_is_not_ours_any_more_is_never_killed(self):
        bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (bystander.poll() is None and bystander.kill(), bystander.wait()))
        d = self.task([{"id": "s", "run": "echo ok >> out", "check": "test -s out"}])
        self.write(d, "task.json", json.dumps({"status": "running", "stages": {"s": {
            "status": "running", "attempts": 1, "digest": "x", "run_id": "0" * 16,
            "pgid": bystander.pid, "pg_start": "1"}}}))  # same pid, wrong start tick: pid reuse
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertIsNone(bystander.poll(), "an unrelated process group was killed")

    def test_x3_a_stage_that_clears_its_environment_is_still_reaped_by_its_pgid(self):
        run = "env -i /bin/sh -c 'echo started >> out; sleep 2; echo done >> out'"
        d = self.task([{"id": "s", "run": run, "check": "grep -q done out"}])
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "out")))
        pgid = self.state(d)["stages"]["s"]["pgid"]
        os.kill(r.pid, signal.SIGKILL)
        r.wait()
        os.killpg(pgid, 0)  # the orphan lives, and no process of it carries the run id
        self.assertEqual(mx("run", d).returncode, 0)
        time.sleep(2.6)
        self.assertEqual(self.read(d, "out").split(), ["started", "started", "done"])

    def test_x4_attempts_counts_every_execution(self):
        d = self.task([{"id": "s", "run": "echo try >> c; test -f go", "check": "true"}])
        self.assertEqual(mx("run", d).returncode, 2)
        self.assertEqual(self.state(d)["stages"]["s"]["attempts"], 1)
        self.write(d, "go", "")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.state(d)["stages"]["s"]["attempts"], 2)


class AtomicWriteCleanup(TaskCase):
    def test_a_failed_atomic_write_leaves_no_temp_file_and_keeps_the_old_content(self):
        d = self.task([{"id": "s", "run": "true", "check": "true"}])
        path = os.path.join(d, "task.json")
        core.atomic_write(path, {"v": 1})
        before = sorted(os.listdir(d))
        for exc in (OSError("disk full"), SystemExit(143)):
            with mock.patch.object(os, "replace", side_effect=exc):
                with self.assertRaises(type(exc)):
                    core.atomic_write(path, {"v": 2})
            self.assertEqual(sorted(os.listdir(d)), before)
            self.assertEqual(json.loads(self.read(d, "task.json")), {"v": 1})


if __name__ == "__main__":
    unittest.main()
