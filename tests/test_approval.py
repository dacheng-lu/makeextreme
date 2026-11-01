"""AC6 (approval bound to the artifact hash), the 'uncertain' state, and the orphan gap."""
import json, os, signal, time, unittest

from support import TaskCase, mx, mx_start, wait_for

def gone(pgid, secs=3):
    end = time.time() + secs
    while time.time() < end:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


MAKE = {"id": "make", "run": "echo made >> rm; echo report > artifact.txt", "check": "test -s artifact.txt"}


def send(sid="send", run="echo sent >> rs", **kw):
    return {"id": sid, "run": run, "check": "test -s rs", "deps": ["artifact.txt"], "approval": "required", **kw}


class Approval(TaskCase):
    def test_no_record_no_run_and_a_second_run_does_not_release_it(self):
        d = self.task([MAKE, send()])
        for _ in range(2):  # the toolkit-v2 failure: the second run used to auto-release
            res = mx("run", d)
            self.assertEqual(res.returncode, 4, res.stderr)
            self.assertEqual(self.lines(d, "rs"), 0)
        st = self.state(d)
        self.assertEqual((st["status"], st["stages"]["send"]["status"]), ("awaiting_approval",) * 2)
        self.assertIn("awaiting_approval", self.events(d))
        self.assertFalse(os.path.exists(os.path.join(d, "approvals.jsonl")), "the runner must never approve")

    def test_an_approval_releases_exactly_that_artifact(self):
        d = self.task([MAKE, send()])
        self.assertEqual(mx("run", d).returncode, 4)
        res = mx("approve", d, "send")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_an_approval_dies_with_the_artifact_it_was_given_for(self):
        d = self.task([MAKE, send()])
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.write(d, "artifact.txt", "something else\n")  # changed after approval, before the run
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(self.lines(d, "rs"), 0)

    def test_after_completion_a_changed_artifact_needs_a_new_approval(self):
        d = self.task([MAKE, send()])
        mx("run", d)
        mx("approve", d, "send")
        self.assertEqual(mx("run", d).returncode, 0)
        self.write(d, "artifact.txt", "v2\n")
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(self.lines(d, "rs"), 1)
        mx("approve", d, "send")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 2)

    def test_a_torn_or_foreign_line_in_approvals_is_not_an_approval_and_not_a_crash(self):
        # a crash during `approve` can leave half a line; anything unreadable is simply not an approval
        d = self.task([MAKE, send()])
        self.assertEqual(mx("run", d).returncode, 4)
        for junk in ('{"t": 1.5, "stage": "sen', "garbage\n", "[]\n", "1\n", "null\n", "\n"):
            self.write(d, "approvals.jsonl", junk)
            res = mx("run", d)
            self.assertEqual(res.returncode, 4, (junk, res.stderr))  # still waiting, no traceback
            self.assertNotIn("Traceback", res.stderr, junk)
            self.assertEqual(self.lines(d, "rs"), 0)
        self.assertEqual(mx("approve", d, "send").returncode, 0)  # a real approval after the junk
        with open(os.path.join(d, "approvals.jsonl")) as f:
            real = f.read()
        self.write(d, "approvals.jsonl", "garbage\n[]\n" + real)  # junk BEFORE the valid line
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_an_approval_is_bound_to_its_stage_id(self):
        d = self.task([MAKE, send("send1"), send("send2")])  # identical definitions, different ids
        mx("run", d)
        self.assertEqual(mx("approve", d, "send1").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 4)  # send1 ran, send2 still waits
        self.assertEqual(self.state(d)["stages"]["send1"]["status"], "done")
        self.assertEqual(self.state(d)["stages"]["send2"]["status"], "awaiting_approval")

    def test_approve_refuses_what_it_cannot_bind(self):
        d = self.task([MAKE, send()])
        for stage in ("nope", "make", "send"):  # unknown; no `approval`; artifact.txt does not exist yet
            res = mx("approve", d, stage)
            self.assertEqual(res.returncode, 1, (stage, res.stderr))
            self.assertIn("refused", res.stderr)
            self.assertNotIn("Traceback", res.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, "approvals.jsonl")))

    def test_an_approval_stage_without_deps_is_a_spec_error_and_nothing_runs(self):
        d = self.task([MAKE, {"id": "send", "run": "echo sent >> rs", "check": "true", "approval": "required"}])
        res = mx("run", d)
        self.assertEqual(res.returncode, 64, res.stderr)
        self.assertEqual(self.lines(d, "rm"), 0)


class Uncertain(TaskCase):
    def crashed(self):
        """An approved irreversible stage whose runner is SIGKILLed mid-stage; returns the task dir."""
        run = "echo started >> rs; if [ -f go ]; then echo ok > sent.ok; else sleep 30; fi"
        d = self.task([MAKE, {**send(run=run), "check": "test -s sent.ok"}])
        mx("run", d)
        mx("approve", d, "send")
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "rs")))
        self.pgid = self.state(d)["stages"]["send"]["pgid"]
        os.kill(r.pid, signal.SIGKILL)
        r.wait()
        return d

    def test_an_irreversible_stage_that_crashed_is_never_rerun_on_its_own(self):
        d = self.crashed()
        res = mx("run", d)
        self.assertEqual(res.returncode, 5, res.stderr)
        self.assertEqual(self.lines(d, "rs"), 1)
        self.assertEqual(self.state(d)["stages"]["send"]["status"], "uncertain")
        self.assertIn("uncertain", self.events(d))
        self.assertTrue(gone(self.pgid), "the orphan was not reaped")
        self.assertEqual(mx("run", d).returncode, 5)  # and it stays uncertain
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_sigterm_during_an_irreversible_stage_is_uncertain_too(self):
        d = self.task([MAKE, {**send(run="echo started >> rs; sleep 30; echo ok > sent.ok"), "check": "test -s sent.ok"}])
        mx("run", d)
        mx("approve", d, "send")
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "rs")))
        r.send_signal(signal.SIGTERM)
        self.assertEqual(r.wait(), 143)
        self.assertEqual(mx("run", d).returncode, 5)
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_resolve_refuses_a_stage_that_is_not_uncertain_and_changes_nothing(self):
        d = self.task([MAKE, send()])
        mx("run", d)
        mx("approve", d, "send")
        self.assertEqual(mx("run", d).returncode, 0)  # send is done
        before = self.sha(d)
        for mode in ("--retry", "--done"):
            for sid in ("send", "nope"):
                res = mx("resolve", d, sid, mode)
                self.assertEqual(res.returncode, 1, (sid, mode, res.stderr))
                self.assertIn("not uncertain", res.stderr)
                self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.sha(d), before)
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_resolve_done_needs_a_passing_check(self):
        d = self.crashed()
        mx("run", d)
        self.assertNotEqual(mx("resolve", d, "send", "--done").returncode, 0)  # sent.ok is absent
        self.assertEqual(self.state(d)["stages"]["send"]["status"], "uncertain")
        self.write(d, "sent.ok", "ok\n")
        self.assertEqual(mx("resolve", d, "send", "--done").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 1)  # never re-sent

    def test_resolve_retry_runs_the_stage_again_by_explicit_decision(self):
        d = self.crashed()
        mx("run", d)
        self.write(d, "go", "")
        self.assertEqual(mx("resolve", d, "send", "--retry").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 2)


class FailedIrreversible(TaskCase):
    """Found by a pre-audit probe: a FAILED approval stage was run again by the next plain `run`,
    with no new decision, although it may have acted before it failed."""

    def failing(self, **kw):
        d = self.task([MAKE, send(**kw)])
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        return d

    def check_never_repeated(self, d):
        res = mx("run", d)
        self.assertEqual(res.returncode, 5, res.stderr)  # not 2: a person must look at it
        st = self.state(d)
        self.assertEqual((st["status"], st["stages"]["send"]["status"]), ("uncertain",) * 2)
        self.assertEqual(self.lines(d, "rs"), 1)
        reason = [e for e in self.journal(d) if e["ev"] == "uncertain"][-1]
        self.assertIn("failed", reason.get("reason", ""))
        for _ in range(2):  # plain runs keep refusing and never repeat the action
            self.assertEqual(mx("run", d).returncode, 5)
            self.assertEqual(self.lines(d, "rs"), 1)

    def test_a_nonzero_exit_is_not_repeated_by_a_plain_run(self):
        self.check_never_repeated(self.failing(run="echo sent >> rs; exit 1"))

    def test_a_failing_check_after_exit_zero_is_not_repeated_by_a_plain_run(self):
        self.check_never_repeated(self.failing(run="echo sent >> rs", check="false"))

    def test_resolve_retry_repeats_it_by_explicit_decision_only(self):
        d = self.failing(run="echo sent >> rs; test -f go", check="test -f go")
        self.assertEqual(mx("run", d).returncode, 5)
        self.write(d, "go", "")
        self.assertEqual(mx("resolve", d, "send", "--retry").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 2)

    def test_an_ordinary_stage_that_fails_still_stops_with_exit_2_and_is_retried_by_run(self):
        d = self.task([{"id": "a", "run": "echo try >> c; test -f go", "check": "true"}])
        self.assertEqual(mx("run", d).returncode, 2)
        self.assertEqual(self.state(d)["stages"]["a"]["status"], "failed")
        self.write(d, "go", "")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "c"), 2)


class OrphanGap(TaskCase):
    def test_a_lost_pgid_does_not_lose_the_orphan(self):
        """SIGKILL between Popen and the state save: the pgid never reached task.json."""
        d = self.task([{"id": "s", "run": "echo y >> c; sleep 4; echo done >> s.done", "check": "test -s s.done"}])
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "c")))
        st = self.state(d)
        st["stages"]["s"].pop("pgid", None)
        st["stages"]["s"].pop("pg_start", None)
        self.write(d, "task.json", json.dumps(st))
        os.kill(r.pid, signal.SIGKILL)
        r.wait()
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "s.done"), 1, "the orphan survived and wrote its marker too")
        self.assertIn("reaped", self.events(d))


if __name__ == "__main__":
    unittest.main()
