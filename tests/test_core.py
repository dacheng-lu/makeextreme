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
        d = self.task([{"id": "s", "run": "echo ok >> c", "check": "test -s c"}])
        with open(f"/proc/{os.getpid()}/stat") as f:
            start = f.read().rsplit(")", 1)[1].split()[19]
        self.write(d, "lock", json.dumps({"pid": os.getpid(), "start": start}))
        res = mx("run", d)
        self.assertEqual((res.returncode, self.lines(d, "c")), (3, 0))
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.write(d, "lock", json.dumps({"pid": dead.pid, "start": "1"}))
        res = mx("run", d)
        self.assertEqual((res.returncode, self.lines(d, "c")), (0, 1))


if __name__ == "__main__":
    unittest.main()
