"""AC11: a finished stage is only trusted while the outputs it declared are still what it produced.

Version 1.0.0 skipped a done stage without looking at its output again (measured: delete the last stage's output,
`run` exits 0 with a `skip` and no file). A stage may now declare `"outputs": [...]`: their content is recorded after
the run and checked before every skip. Ordinary stages are run again; an approval stage becomes `uncertain`
(an irreversible action is never repeated on its own). Stages that declare nothing behave exactly as before.
"""
import json, os, shutil, unittest

from support import REPO, TaskCase, mx

import sys
sys.path.insert(0, REPO)
from makeextreme import core  # noqa: E402

MAKE = {"id": "make", "run": "echo made >> rm; echo data > out.txt", "check": "test -s out.txt", "outputs": ["out.txt"]}
USE = {"id": "use", "run": "echo used >> ru; cp out.txt use.out", "check": "test -s use.out", "deps": ["out.txt"],
       "outputs": ["use.out"]}
SEND = {"id": "send", "run": "echo sent >> rs; echo receipt > receipt.txt", "check": "test -s rs",
        "deps": ["artifact.txt"], "approval": "required", "outputs": ["receipt.txt"]}


def last(events, name):
    return [e for e in events if e["ev"] == name][-1]


class DeclaredOutputs(TaskCase):
    def pipe(self):
        d = self.task([MAKE, USE])
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual((self.lines(d, "rm"), self.lines(d, "ru")), (1, 1))
        return d

    def test_unchanged_outputs_skip_everything_even_a_stage_that_rewrites_its_own_output(self):
        d = self.pipe()
        for _ in range(2):
            self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual((self.lines(d, "rm"), self.lines(d, "ru")), (1, 1))
        self.assertEqual(self.events(d).count("skip"), 4)

    def test_a_deleted_output_is_made_again_and_the_journal_says_why(self):
        d = self.pipe()
        os.remove(os.path.join(d, "out.txt"))
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read(d, "out.txt"), "data\n")
        self.assertEqual(self.lines(d, "rm"), 2)
        ev = last(self.journal(d), "invalidated")
        self.assertEqual(ev["stage"], "make")
        self.assertEqual(ev["outputs"], ["out.txt"])
        self.assertIn("output", ev["reason"])

    def test_an_edited_output_is_made_again(self):
        d = self.pipe()
        self.write(d, "out.txt", "tampered\n")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.read(d, "out.txt"), "data\n")
        self.assertEqual(self.lines(d, "rm"), 2)

    def test_the_same_bytes_again_do_not_cascade_to_the_stages_that_read_them(self):
        d = self.pipe()
        os.remove(os.path.join(d, "out.txt"))
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual((self.lines(d, "rm"), self.lines(d, "ru")), (2, 1))

    def test_regenerated_bytes_that_differ_do_cascade_to_the_stages_that_read_them(self):
        """The other direction of the test above: with a producer whose bytes change on every run, a reader that is not run again
        would mean the content of its dep is not part of its fingerprint (the audit found the test above green in that case)."""
        growing = dict(MAKE, run="echo made >> rm; cp rm out.txt")
        d = self.task([growing, USE])
        self.assertEqual(mx("run", d).returncode, 0)
        os.remove(os.path.join(d, "out.txt"))
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual((self.lines(d, "rm"), self.lines(d, "ru")), (2, 2))

    def test_a_deleted_last_output_is_noticed_although_no_later_stage_reads_it(self):
        d = self.pipe()
        os.remove(os.path.join(d, "use.out"))
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(d, "use.out")))
        self.assertEqual((self.lines(d, "rm"), self.lines(d, "ru")), (1, 2))

    def test_a_directory_output_counts_by_content(self):
        stage = {"id": "frames", "run": "echo f >> rf; rm -rf frames; mkdir frames; echo 1 > frames/a; echo 2 > frames/b",
                 "check": "test -s frames/b", "outputs": ["frames"]}
        d = self.task([stage])
        self.assertEqual(mx("run", d).returncode, 0)
        os.remove(os.path.join(d, "frames", "b"))
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rf"), 2)
        self.assertEqual(sorted(os.listdir(os.path.join(d, "frames"))), ["a", "b"])
        # deleting a file also changes the list of names; the content is what counts when the names stay the same
        self.write(d, "frames/a", "tampered\n")
        self.assertEqual(sorted(os.listdir(os.path.join(d, "frames"))), ["a", "b"])
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rf"), 3, "an edited file inside a declared directory output was not noticed")
        self.assertEqual(self.read(d, "frames/a"), "1\n")

    def test_a_declared_output_that_the_run_did_not_produce_is_not_done(self):
        d = self.task([{"id": "x", "run": "true", "check": "true", "outputs": ["never.txt"]}])
        res = mx("run", d)
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertNotEqual(self.state(d)["stages"]["x"]["status"], "done")
        self.assertEqual(last(self.journal(d), "end")["missing"], ["never.txt"])

    def test_a_stage_that_fails_after_a_change_keeps_no_record_of_its_old_outputs(self):
        d = self.pipe()
        self.write(d, "stages.json", json.dumps([{**MAKE, "run": "echo broken >> rm; false"}, USE]))
        self.assertEqual(mx("run", d).returncode, 2)
        rec = self.state(d)["stages"]["make"]
        self.assertEqual(rec["status"], "failed")
        self.assertNotIn("sha256", rec, "the record of a failed stage must not show the hashes of an older run")

    def test_a_task_record_without_the_recorded_outputs_is_not_trusted(self):
        d = self.pipe()
        st = self.state(d)
        del st["stages"]["make"]["sha256"]
        self.write(d, "task.json", json.dumps(st))
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rm"), 2)

    def test_declaring_outputs_later_or_changing_the_list_invalidates_the_stage(self):
        plain = {k: v for k, v in MAKE.items() if k != "outputs"}
        d = self.task([plain])
        self.assertEqual(mx("run", d).returncode, 0)
        self.write(d, "stages.json", json.dumps([MAKE]))
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rm"), 2)  # a new declaration is a new stage identity
        self.write(d, "stages.json", json.dumps([{**MAKE, "outputs": ["out.txt", "rm"]}]))
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rm"), 3)

    def test_an_output_that_cannot_be_read_after_the_run_means_not_done(self):
        stage = {"id": "x", "run": "echo go >> rx; ln -s /proc/self/mem unreadable", "check": "true",
                 "outputs": ["unreadable"]}  # a link whose read fails with EIO for every uid
        d = self.task([stage])
        res = mx("run", d)
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertNotEqual(self.state(d)["stages"]["x"]["status"], "done")

    def test_an_output_that_becomes_unreadable_later_is_a_clean_refusal_and_nothing_runs_again(self):
        d = self.pipe()
        os.remove(os.path.join(d, "out.txt"))
        os.symlink("/proc/self/mem", os.path.join(d, "out.txt"))
        res = mx("run", d)
        self.assertEqual(res.returncode, 64, res.stderr)
        self.assertIn("refused", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.state(d)["status"], "refused")
        self.assertEqual((self.lines(d, "rm"), self.lines(d, "ru")), (1, 1))

    def test_a_stage_that_declares_no_outputs_is_skipped_as_before(self):
        plain = {k: v for k, v in MAKE.items() if k != "outputs"}
        d = self.task([plain])
        self.assertEqual(mx("run", d).returncode, 0)
        os.remove(os.path.join(d, "out.txt"))
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(d, "out.txt")), "documented limit: undeclared outputs are not verified")
        self.assertEqual(self.lines(d, "rm"), 1)

    def test_the_fingerprint_of_a_stage_without_outputs_is_what_version_1_0_0_computed(self):
        d = self.task([MAKE], {"x": "1\n"})
        self.assertEqual(core.fingerprint(d, {"run": "echo hi", "check": "true", "deps": ["x"]}),
                         "8cdf0cecf76db8f646e936bfdce8d901f941ce040528f702d644772939523253")
        self.assertEqual(core.fingerprint(d, {"run": "echo hi", "check": "true"}),
                         "855c40717ff72df73903a52fee43e6d39706f9c0f3a8057a74c2bf93ee0e625d")


PREP = {"id": "make", "run": "echo report > artifact.txt", "check": "test -s artifact.txt"}


class OutputsOfAnIrreversibleStage(TaskCase):
    def done(self):
        d = self.task([PREP, SEND])
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 1)
        return d

    def test_a_changed_output_makes_it_uncertain_and_never_runs_it_again(self):
        d = self.done()
        os.remove(os.path.join(d, "receipt.txt"))
        res = mx("run", d)
        self.assertEqual(res.returncode, 5, res.stderr)
        self.assertEqual(self.lines(d, "rs"), 1)
        self.assertEqual(self.state(d)["stages"]["send"]["status"], "uncertain")
        ev = last(self.journal(d), "uncertain")
        self.assertEqual(ev["outputs"], ["receipt.txt"])
        self.assertIn("output", ev["reason"])
        self.assertEqual(mx("run", d).returncode, 5)  # and it stays so
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_resolve_done_is_refused_while_a_declared_output_is_missing_and_then_takes_the_current_state(self):
        d = self.done()
        os.remove(os.path.join(d, "receipt.txt"))
        mx("run", d)
        res = mx("resolve", d, "send", "--done")
        self.assertEqual(res.returncode, 1)
        self.assertIn("receipt.txt", res.stderr)
        self.assertEqual(self.state(d)["stages"]["send"]["status"], "uncertain")
        self.write(d, "receipt.txt", "restored by hand\n")
        self.assertEqual(mx("resolve", d, "send", "--done").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 1)
        self.write(d, "receipt.txt", "changed again\n")  # the decision took THIS content, not any content
        self.assertEqual(mx("run", d).returncode, 5)

    def test_resolve_retry_repeats_the_run_once_and_records_the_new_outputs(self):
        d = self.done()
        os.remove(os.path.join(d, "receipt.txt"))
        mx("run", d)
        self.assertEqual(mx("resolve", d, "send", "--retry").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 2)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 2)
        os.remove(os.path.join(d, "receipt.txt"))
        self.assertEqual(mx("run", d).returncode, 5)

    def test_changing_the_declared_outputs_of_an_approved_stage_voids_its_approval(self):
        d = self.done()  # the declaration is part of the stage's identity, like its command and its check
        self.write(d, "stages.json", json.dumps([PREP, {**SEND, "outputs": ["receipt.txt", "rs"]}]))
        res = mx("run", d)
        self.assertEqual(res.returncode, 4, res.stderr)  # asks again; it is not "uncertain" and it does not run
        self.assertEqual(self.lines(d, "rs"), 1)
        self.assertEqual(self.state(d)["stages"]["send"]["status"], "awaiting_approval")

    def test_a_record_without_the_recorded_outputs_is_uncertain_not_run_again(self):
        d = self.done()
        st = self.state(d)
        del st["stages"]["send"]["sha256"]
        self.write(d, "task.json", json.dumps(st))
        self.assertEqual(mx("run", d).returncode, 5)
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_an_irreversible_run_that_leaves_a_declared_output_missing_is_uncertain(self):
        stage = {**SEND, "run": "echo sent >> rs"}  # acts, but writes no receipt
        d = self.task([PREP, stage])
        mx("run", d)
        mx("approve", d, "send")
        res = mx("run", d)
        self.assertEqual(res.returncode, 5, res.stderr)
        self.assertEqual(self.lines(d, "rs"), 1)
        self.assertEqual(last(self.journal(d), "end")["missing"], ["receipt.txt"])


class OutputsInTheSpec(TaskCase):
    def refused(self, stage, *needles):
        d = self.task([stage])
        for cmd in ("run", "approve"):
            res = mx(cmd, d, *(["x"] if cmd == "approve" else []))
            self.assertEqual(res.returncode, 64, (cmd, res.stdout, res.stderr))
            self.assertNotIn("Traceback", res.stderr)
            for n in needles:
                self.assertIn(n, res.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, "task.json")), "nothing may run for a refused spec")

    def test_outputs_must_be_a_list_of_paths(self):
        for bad in ("out.txt", [""], [1], {"a": 1}):
            self.refused({"id": "x", "run": "echo hi > a", "check": "true", "outputs": bad}, "outputs")

    def test_a_path_that_is_both_a_dep_and_an_output_is_refused(self):
        self.refused({"id": "x", "run": "echo hi >> a", "check": "true", "deps": ["a"], "outputs": ["a"]},
                     "overlap", "a")

    def test_validate_spec_without_a_task_directory_refuses_a_path_that_is_both_a_dep_and_an_output(self):
        """Since 1.1.1 the loader also compares real paths; the public function without a directory keeps the string-level guard."""
        from makeextreme import core
        stage = {"id": "x", "run": "true", "check": "true", "deps": ["a"], "outputs": ["a"]}
        with self.assertRaisesRegex(core.SpecError, "overlap"):
            core.validate_spec([stage])
        core.validate_spec([dict(stage, outputs=["b"])])  # control: the same stage with distinct paths is fine


if __name__ == "__main__":
    unittest.main()
