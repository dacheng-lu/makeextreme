"""A stage's declared timeout is a real bound on the whole process group.

The tests prove the group stops, not only the direct child: a stage that leaves a
background `sleep` behind is the normal shape of a model call that forks a runner.
Everything here is a real subprocess and a real SIGKILL; no model is called.
"""
import json
import os
import sys
import time
import unittest

from support import REPO, TaskCase, mx


def alive(pid):
    """True while /proc/<pid> exists (a zombie still counts: it has not been reaped)."""
    return os.path.exists(f"/proc/{pid}")


class Timeout(TaskCase):
    def test_a_stage_over_its_bound_is_killed_with_its_child_and_never_completes(self):
        d = self.task([{"id": "s1", "run": "sh -c 'sleep 30 & echo $! > child.pid; wait'",
                        "check": "test -s out.txt", "timeout": 1}])
        started = time.monotonic()
        res = mx("run", d, timeout=30)
        elapsed = time.monotonic() - started
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertLess(elapsed, 15, "the declared bound did not bound the run")
        self.assertEqual(self.state(d)["status"], "failed")
        stage = self.state(d)["stages"]["s1"]
        self.assertEqual(stage["status"], "failed")
        self.assertEqual(stage["failure"], "timeout")
        self.assertIn("timeout", self.events(d))
        child = int(self.read(d, "child.pid"))
        for _ in range(40):
            if not alive(child):
                break
            time.sleep(0.05)
        self.assertFalse(alive(child), "the stage's child survived the timeout")
        self.assertFalse(os.path.exists(os.path.join(d, "out.txt")))

    def test_a_stage_under_its_bound_is_untouched(self):
        d = self.task([{"id": "s1", "run": "echo done > out.txt", "check": "test -s out.txt",
                        "outputs": ["out.txt"], "timeout": 30}])
        self.assertEqual(mx("run", d, timeout=30).returncode, 0)
        self.assertEqual(self.state(d)["status"], "complete")
        self.assertNotIn("failure", self.state(d)["stages"]["s1"])

    def test_a_timed_out_stage_can_be_retried_by_a_new_run(self):
        d = self.task([{"id": "s1", "run": "sleep 30", "check": "true", "timeout": 1}])
        self.assertEqual(mx("run", d, timeout=30).returncode, 2)
        # the same spec would time out again; changing the command is a new fingerprint and runs
        spec = json.loads(self.read(d, "stages.json"))
        spec[0].update(run="echo ok > out.txt", check="test -s out.txt", outputs=["out.txt"], timeout=30)
        self.write(d, "stages.json", json.dumps(spec))
        self.assertEqual(mx("run", d, timeout=30).returncode, 0)
        self.assertEqual(self.state(d)["stages"]["s1"]["attempts"], 2)

    def test_an_approval_stage_that_times_out_is_uncertain_not_done(self):
        d = self.task([{"id": "push", "run": "sleep 30", "check": "true",
                        "deps": ["artifact.txt"], "approval": "required", "timeout": 1}],
                      {"artifact.txt": "x\n"})
        self.assertEqual(mx("approve", d, "push", timeout=30).returncode, 0)
        self.assertEqual(mx("run", d, timeout=30).returncode, 5)
        self.assertEqual(self.state(d)["stages"]["push"]["status"], "uncertain")
        self.assertNotEqual(self.state(d)["status"], "complete")
        self.assertIn("timed out", json.dumps(self.journal(d)))

    def test_invalid_timeouts_are_refused_before_anything_runs(self):
        for bad in (0, -1, True, "5"):
            d = self.task([{"id": "s1", "run": "touch out.txt", "check": "true", "timeout": bad}])
            res = mx("run", d, timeout=30)
            self.assertEqual(res.returncode, 64, (bad, res.stderr))
            self.assertIn("'timeout' must be a positive number", res.stderr)
            self.assertFalse(os.path.exists(os.path.join(d, "out.txt")))


if __name__ == "__main__":
    unittest.main()
