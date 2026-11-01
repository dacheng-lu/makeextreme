"""The run lock under real contention (found by a pre-audit probe: 13 of 25 rounds with six
simultaneous runners executed one stage twice, 5 of 25 when taking over a stale lock)."""
import json, os, subprocess, sys, unittest

from support import REPO, TaskCase

ROUNDS = 10
RUNNERS = 8
STAGE = [{"id": "s", "run": "echo x >> out; sleep 0.3", "check": "test -s out"}]


def burst(d, n=RUNNERS):
    """n runners started as close together as a process spawn allows; their exit codes."""
    procs = [subprocess.Popen([sys.executable, "-m", "makeextreme", "run", d], cwd=REPO,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(n)]
    return sorted(p.wait() for p in procs)


class LockContention(TaskCase):
    def _rounds(self, prepare):
        doubles = []
        for r in range(ROUNDS):
            d = self.task(STAGE)
            prepare(d)
            codes = burst(d)
            runs = self.lines(d, "out")
            if runs != 1:
                doubles.append((r, runs, codes))
            self.assertEqual(self.state(d)["status"], "complete", codes)
        self.assertEqual(doubles, [], "a stage ran more than once: mutual exclusion failed")

    def test_simultaneous_runners_execute_a_stage_exactly_once(self):
        self._rounds(lambda d: None)

    def test_simultaneous_takeover_of_a_dead_holders_lock_executes_a_stage_exactly_once(self):
        def stale(d):
            dead = subprocess.Popen(["true"])
            dead.wait()
            self.write(d, "lock", json.dumps({"pid": dead.pid, "start": "1"}))
        self._rounds(stale)

    def test_a_runner_that_refuses_for_a_live_holder_says_so_and_changes_nothing(self):
        d = self.task([{"id": "s", "run": "echo x >> out; sleep 2", "check": "test -s out"}])
        first = subprocess.Popen([sys.executable, "-m", "makeextreme", "run", d], cwd=REPO,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(first.wait)
        from support import wait_for
        self.assertTrue(wait_for(os.path.join(d, "out")))
        res = subprocess.run([sys.executable, "-m", "makeextreme", "run", d], cwd=REPO,
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("locked", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.lines(d, "out"), 1)


if __name__ == "__main__":
    unittest.main()
