"""A stage must not declare paths that change with every run of the runner itself, and stages must not share outputs.

Found by the D19 audit (2026-11-01): a stage that declares the runner's own record (task.json ...) or `.` as a dep or output has a new
fingerprint after every save, so an ordinary stage re-executes on EVERY run, and an approval stage sticks at exit 5 that `resolve --done`
cannot settle. Two stages that declare the same output invalidate each other's recorded hash on every run. Such specs are refused at load
(exit 64, nothing runs, nothing is created), the same way a dep that is also an output of its own stage already is.
"""
import json, os, sys, unittest

from support import REPO, TaskCase, mx

sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "examples", "video_pipeline"))
from makeextreme import core  # noqa: E402

A = {"id": "a", "run": "echo a >> ca; echo A > a.txt", "check": "test -s a.txt", "outputs": ["a.txt"]}
B = {"id": "b", "run": "echo b >> cb; echo B > b.txt", "check": "test -s b.txt", "deps": ["a.txt"], "outputs": ["b.txt"]}


def stage(sid, **kw):
    """A stage whose command really produces every output it declares (a declared output that is not produced means not done)."""
    make = "; ".join("mkdir -p $(dirname %s); echo x > %s" % (o, o) for o in kw.get("outputs", [])) or "true"
    return {"id": sid, "run": "echo %s >> c%s; %s" % (sid, sid, make), "check": "true", **kw}


class Refused(TaskCase):
    def refused(self, stages, *, needle, label):
        d = self.task(stages)
        res = mx("run", d)
        self.assertEqual(res.returncode, 64, (label, res.stdout, res.stderr))
        self.assertIn(needle, res.stderr, label)
        self.assertNotIn("Traceback", res.stderr, label)
        self.assertEqual(sorted(os.listdir(d)), ["stages.json"], (label, "nothing may be created or run for a refused spec"))

    def test_the_runners_own_record_files_cannot_be_declared_as_outputs_or_deps(self):
        for name in ("task.json", "journal.jsonl", "approvals.jsonl", "lock"):
            for key in ("outputs", "deps"):
                self.refused([stage("s", **{key: [name]})], needle="record", label=(key, name))

    def test_the_task_directory_itself_or_a_parent_contains_the_records(self):
        for path in (".", "./", "..", "sub/.."):
            for key in ("outputs", "deps"):
                self.refused([stage("s", **{key: [path]})], needle="record", label=(key, path))

    def test_the_filesystem_root_is_a_parent_of_the_task_directory_too(self):
        """Found by the audit of 1.1.1: containment was `a.startswith(b + os.sep)`, so b == "/" became "//" and nothing was ever inside it."""
        for path in ("/", "/./", "../" * 40, "../" * 40 + "."):
            for key in ("outputs", "deps"):
                self.refused([stage("s", **{key: [path]})], needle="record", label=(key, path))

    def test_a_path_that_lies_inside_a_record_file_is_refused_too(self):
        """The record loop only asked whether a record is inside the declared path; `task.json/x` has the record as a prefix, loads, and can never settle."""
        for path in ("task.json/x", "lock/y", "./journal.jsonl/a/b"):
            for key in ("outputs", "deps"):
                self.refused([stage("s", **{key: [path]})], needle="record", label=(key, path))

    def test_a_path_with_a_nul_byte_is_refused_cleanly_not_with_a_traceback(self):
        for key in ("outputs", "deps"):
            self.refused([stage("s", **{key: ["a\x00b"]})], needle="NUL", label=key)

    def test_the_same_record_spelled_differently_is_still_refused(self):
        self.refused([stage("s", outputs=["./task.json"])], needle="record", label="./task.json")
        self.refused([stage("s", outputs=["x/../task.json"])], needle="record", label="x/../task.json")

    def test_a_symlink_to_a_record_is_refused_through_its_target(self):
        d = self.task([stage("s", outputs=["alias.json"])])
        os.symlink("task.json", os.path.join(d, "alias.json"))
        res = mx("run", d)
        self.assertEqual(res.returncode, 64, res.stderr)
        self.assertIn("record", res.stderr)

    def test_two_stages_may_not_declare_the_same_output(self):
        self.refused([stage("one", outputs=["o.txt"]), stage("two", outputs=["o.txt"])], needle="overlapping outputs", label="same")
        self.refused([stage("one", outputs=["o.txt"]), stage("two", outputs=["./o.txt"])], needle="overlapping outputs", label="spelled differently")

    def test_an_output_inside_another_stages_directory_output_is_an_overlap(self):
        self.refused([stage("one", outputs=["frames"]), stage("two", outputs=["frames/x.png"])], needle="overlapping outputs", label="inside")
        self.refused([stage("one", outputs=["frames/x.png"]), stage("two", outputs=["frames"])], needle="overlapping outputs", label="contains")

    def test_one_stage_may_not_list_the_same_output_twice(self):
        self.refused([stage("one", outputs=["o.txt", "o.txt"])], needle="overlapping outputs", label="twice")

    def test_a_duplicate_inside_one_stage_is_reported_as_one_stage_not_as_two(self):
        d = self.task([stage("s", outputs=["o.txt", "./o.txt"])])
        res = mx("run", d)
        self.assertEqual(res.returncode, 64, res.stderr)
        self.assertIn("stage s ", res.stderr)
        self.assertNotIn("stages s and s", res.stderr)

    def test_a_stage_whose_dep_directory_contains_its_own_output_changes_its_own_dep(self):
        self.refused([stage("s", deps=["frames"], outputs=["frames/x.png"])], needle="overlap", label="dep contains output")
        self.refused([stage("s", deps=["frames/x.png"], outputs=["frames"])], needle="overlap", label="output contains dep")
        self.refused([stage("s", deps=["a.txt"], outputs=["./a.txt"])], needle="overlap", label="same file, spelled differently")


class StillAccepted(TaskCase):
    """Controls: the specs that were fine before stay fine (these are green before and after the change)."""

    def test_a_normal_pipeline_runs_and_is_skipped_on_the_second_run(self):
        d = self.task([A, B])
        for _ in range(2):
            self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual((self.lines(d, "ca"), self.lines(d, "cb")), (1, 1))

    def test_names_that_only_share_a_string_prefix_do_not_overlap(self):
        d = self.task([stage("one", outputs=["frames"]), stage("two", outputs=["frames2"]), stage("three", outputs=["frames.txt"])])
        self.assertEqual(mx("run", d).returncode, 0)

    def test_a_subdirectory_of_the_task_and_a_dep_that_is_another_stages_output_are_fine(self):
        d = self.task([stage("one", outputs=["sub/o1"]), stage("two", deps=["sub/o1"], outputs=["sub/o2"])])
        os.makedirs(os.path.join(d, "sub"))
        self.assertEqual(mx("run", d).returncode, 0)

    def test_the_shipped_video_pipeline_spec_is_still_valid(self):
        import new_task
        core.load_spec(self.task(new_task.stages("python3")))  # raises SpecError if refused


if __name__ == "__main__":
    unittest.main()
