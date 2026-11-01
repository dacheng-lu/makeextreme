"""AC1-AC4, AC7: the M0 acceptance probes, ported to the package CLI."""
import json, os, signal, subprocess, time, unittest

from support import TaskCase, mx, mx_start, wait_for

S3 = [
    {"id": "s1", "run": "echo x >> c1", "check": "test -s c1"},
    {"id": "s2", "run": "echo y >> c2; sleep 4; echo done >> s2.done", "check": "test -s s2.done"},
    {"id": "s3", "run": "echo z >> c3", "check": "test -s c3"},
]


class Core(TaskCase):
    def test_ac1_kill9_resume_reaps_orphan_and_redoes_only_the_crashed_stage(self):
        d = self.task(S3)
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "c2")), "stage 2 never started")
        pgid = self.state(d)["stages"]["s2"]["pgid"]
        os.kill(r.pid, signal.SIGKILL)
        r.wait()
        os.killpg(pgid, 0)  # the hazard is real: the orphan is alive
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.state(d)["status"], "complete")
        self.assertEqual((self.lines(d, "c1"), self.lines(d, "c2"), self.lines(d, "c3")), (1, 2, 1))
        self.assertEqual(self.lines(d, "s2.done"), 1, "orphan was not reaped")
        self.assertTrue({"recovered_from_crash", "reaped"} <= set(self.events(d)))

    def test_ac3_resume_of_a_complete_task_changes_nothing(self):
        d = self.task(S3[:1] + S3[2:])
        self.assertEqual(mx("run", d).returncode, 0)
        before = self.sha(d)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.sha(d), before)
        self.assertEqual((self.lines(d, "c1"), self.lines(d, "c3")), (1, 1))

    def test_ac2_exit_zero_with_failing_check_is_failed_and_stops(self):
        d = self.task([{"id": "a", "run": "echo hi", "check": "false"},
                       {"id": "b", "run": "touch b.ran", "check": "true"}])
        res = mx("run", d)
        st = self.state(d)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(st["stages"]["a"]["status"], "failed")
        self.assertFalse(os.path.exists(os.path.join(d, "b.ran")))
        self.assertNotIn("b", st["stages"])

    def test_ac7_sigterm_is_journaled_interrupted_and_resumable(self):
        d = self.task([{"id": "s", "run": "echo go >> c; sleep 3; echo done >> d", "check": "test -s d"}])
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "c")))
        r.send_signal(signal.SIGTERM)
        self.assertEqual(r.wait(), 143)
        self.assertEqual(self.state(d)["status"], "interrupted")
        self.assertIn("interrupted", self.events(d))
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual((self.lines(d, "c"), self.lines(d, "d")), (2, 1))

    def test_ac4_live_lock_refuses_dead_lock_is_taken_over(self):
        d = self.task([{"id": "s", "run": "echo ok >> c; sleep 2", "check": "test -s c"}])
        live = mx_start("run", d)  # a real runner holds the lock while its stage sleeps
        self.addCleanup(live.wait)
        self.assertTrue(wait_for(os.path.join(d, "c")))
        res = mx("run", d)
        self.assertEqual((res.returncode, self.lines(d, "c")), (3, 1), res.stderr)
        self.assertIn("locked", res.stderr)
        # a holder that dies (kill -9) leaves its lock file behind; the next runner just takes over
        os.kill(live.pid, signal.SIGKILL)
        live.wait()
        self.assertTrue(os.path.exists(os.path.join(d, "lock")))
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.state(d)["status"], "complete")


    def test_stage_ids_must_be_present_and_unique_and_nothing_runs_otherwise(self):
        ok = {"id": "a", "run": "echo a >> c", "check": "true"}
        bad = {"duplicate id": [ok, {**ok, "run": "echo again >> c"}], "missing id": [{"run": "echo x >> c", "check": "true"}],
               "empty id": [{**ok, "id": ""}], "no check": [{"id": "a", "run": "echo x >> c"}],
               "empty list": [], "not a list": {"id": "a"}}
        for label, spec in bad.items():
            d = self.task(spec)
            res = mx("run", d)
            self.assertEqual(res.returncode, 64, (label, res.stderr))
            self.assertIn("invalid stages.json", res.stderr, label)
            self.assertNotIn("Traceback", res.stderr, label)
            self.assertEqual(self.lines(d, "c"), 0, label)

    def test_a_missing_or_unreadable_stages_json_or_task_dir_is_a_clean_refusal_for_every_command(self):
        import tempfile
        broken = tempfile.TemporaryDirectory(prefix="mx-")
        self.addCleanup(broken.cleanup)
        self.write(broken.name, "stages.json", '{"id": ')
        empty = tempfile.TemporaryDirectory(prefix="mx-")  # no stages.json at all
        self.addCleanup(empty.cleanup)
        cases = {"invalid json": (broken.name, "stages.json"), "missing stages.json": (empty.name, "stages.json"),
                 "missing task dir": (os.path.join(empty.name, "no", "such", "dir"), "task directory")}
        for label, (d, word) in cases.items():
            for cmd in (("run", d), ("approve", d, "x"), ("resolve", d, "x", "--retry")):
                res = mx(*cmd)
                self.assertEqual(res.returncode, 64, (label, cmd[0], res.stderr))
                self.assertIn(word, res.stderr, (label, cmd[0]))
                self.assertNotIn("Traceback", res.stderr, (label, cmd[0]))
        self.assertEqual(os.listdir(broken.name), ["stages.json"])  # nothing created next to a bad spec
        self.assertEqual(os.listdir(empty.name), [])

    def test_a_damaged_task_json_is_refused_cleanly_and_left_alone(self):
        for damaged in ("", '{"status": "runn'):
            d = self.task([{"id": "s", "run": "echo ok >> c", "check": "test -s c"}])
            self.write(d, "task.json", damaged)
            res = mx("run", d)
            self.assertEqual(res.returncode, 64, res.stderr)
            self.assertNotIn("Traceback", res.stderr)
            self.assertIn("task.json", res.stderr)
            self.assertEqual(self.read(d, "task.json"), damaged)
            self.assertEqual(self.lines(d, "c"), 0)
            os.unlink(os.path.join(d, "task.json"))  # the message's own advice: delete it to start over
            self.assertEqual(mx("run", d).returncode, 0)  # and the lock was released


if __name__ == "__main__":
    unittest.main()
