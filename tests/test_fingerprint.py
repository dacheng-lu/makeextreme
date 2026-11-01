"""AC5: a stage is invalidated only when its own fingerprint (command + declared deps' content) changes."""
import json, os, unittest

from support import TaskCase, mx


def pipeline():
    # a: in.txt -> a.out (first character only)   b: a.out -> b.out   c: other.txt -> c.out (independent)
    return [
        {"id": "a", "run": "echo a >> ra; cut -c1 in.txt > a.out", "check": "test -s a.out", "deps": ["in.txt"]},
        {"id": "b", "run": "echo b >> rb; cp a.out b.out", "check": "test -s b.out", "deps": ["a.out"]},
        {"id": "c", "run": "echo c >> rc; cp other.txt c.out", "check": "test -s c.out", "deps": ["other.txt"]},
    ]


class Fingerprint(TaskCase):
    def runs(self, d):
        return tuple(self.lines(d, n) for n in ("ra", "rb", "rc"))

    def setUp(self):
        self.d = self.task(pipeline(), {"in.txt": "x1\n", "other.txt": "o\n"})
        self.assertEqual(mx("run", self.d).returncode, 0)
        self.assertEqual(self.runs(self.d), (1, 1, 1))

    def test_unchanged_deps_skip_everything(self):
        self.assertEqual(mx("run", self.d).returncode, 0)
        self.assertEqual(self.runs(self.d), (1, 1, 1))

    def test_a_changed_independent_dep_reruns_only_that_stage(self):
        self.write(self.d, "other.txt", "o2\n")
        self.assertEqual(mx("run", self.d).returncode, 0)
        self.assertEqual(self.runs(self.d), (1, 1, 2))
        self.assertIn("invalidated", self.events(self.d))

    def test_a_changed_artifact_invalidates_its_dependents_only(self):
        self.write(self.d, "in.txt", "y1\n")  # a re-runs and now produces a different a.out
        self.assertEqual(mx("run", self.d).returncode, 0)
        self.assertEqual(self.runs(self.d), (2, 2, 1))
        self.assertEqual(self.read(self.d, "b.out"), "y\n")

    def test_same_output_after_rerun_does_not_cascade(self):
        self.write(self.d, "in.txt", "x2\n")  # a re-runs, a.out is still "x"
        self.assertEqual(mx("run", self.d).returncode, 0)
        self.assertEqual(self.runs(self.d), (2, 1, 1))

    def test_a_changed_command_invalidates_the_stage(self):
        spec = pipeline()
        spec[2]["run"] += "; true"
        self.write(self.d, "stages.json", json.dumps(spec))
        self.assertEqual(mx("run", self.d).returncode, 0)
        self.assertEqual(self.runs(self.d), (1, 1, 2))

    def test_a_changed_check_invalidates_the_stage(self):
        spec = pipeline()
        spec[2]["check"] = "test -s c.out && true"  # same command, same deps, a different check
        self.write(self.d, "stages.json", json.dumps(spec))
        self.assertEqual(mx("run", self.d).returncode, 0)
        self.assertEqual(self.runs(self.d), (1, 1, 2))

    def test_a_directory_dep_is_hashed_by_content_and_not_by_file_names(self):
        d = self.task([{"id": "z", "run": "echo z >> rz; ls frames > z.out", "check": "test -f z.out",
                        "deps": ["frames"]}])
        os.mkdir(os.path.join(d, "frames"))
        self.write(d, "frames/f1", "1")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rz"), 1)
        self.write(d, "frames/f2", "2")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rz"), 2)
        self.write(d, "frames/f1", "changed")  # same names, other content, also one level down
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rz"), 3)
        self.write(d, "frames/sub/f3", "3")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rz"), 4)
        self.write(d, "frames/sub/f3", "3 changed")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rz"), 5)


if __name__ == "__main__":
    unittest.main()
