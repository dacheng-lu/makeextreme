"""slice_diff.py against throw-away git repos. Stdlib only."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "examples", "audit_ladder", "bin"))
import slice_diff  # noqa: E402

BIG = "def unrelated_%d():\n    return %d\n\n\n"


class Repo:
    def __init__(self):
        self.d = tempfile.mkdtemp(prefix="slice-")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")

    def git(self, *a):
        return subprocess.run(["git", "-C", self.d, *a], capture_output=True, text=True, check=True).stdout.strip()

    def write(self, rel, text):
        p = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")


class SliceCase(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.r.d]))

    def pack(self, base, head="HEAD", **kw):
        return slice_diff.build(self.r.d, base, head, **kw)

    def two_commits(self, before, after, extra=None):
        for rel, t in (extra or {}).items():
            self.r.write(rel, t)
        self.r.write("m.py", before)
        base = self.r.commit("base")
        self.r.write("m.py", after)
        self.r.commit("change")
        return base


class Units(SliceCase):
    def test_the_changed_function_is_in_the_pack_and_an_unrelated_one_is_not(self):
        body = "".join(BIG % (i, i) for i in range(30))
        before = body + "def target():\n    return 'OLD'\n"
        base = self.two_commits(before, before.replace("'OLD'", "'NEW'"))
        p = self.pack(base)
        self.assertIn("def target():", p["markdown"])
        self.assertIn("'NEW'", p["markdown"])
        self.assertNotIn("unrelated_7", p["markdown"])
        self.assertEqual([u["name"] for u in p["units"]], ["target"])

    def test_a_change_inside_a_method_names_the_method_with_its_class(self):
        before = "class K:\n    def a(self):\n        return 1\n\n    def b(self):\n        return 2\n"
        base = self.two_commits(before, before.replace("return 2", "return 3"))
        p = self.pack(base)
        self.assertEqual([u["name"] for u in p["units"]], ["K.b"])
        self.assertNotIn("return 1", p["markdown"])

    def test_a_change_inside_a_nested_function_names_the_inner_one(self):
        before = "def outer():\n    x = 1\n\n    def inner():\n        return 'OLD'\n\n    return inner\n"
        base = self.two_commits(before, before.replace("'OLD'", "'NEW'"))
        self.assertEqual([u["name"] for u in self.pack(base)["units"]], ["outer.inner"])

    def test_a_module_level_change_is_its_own_unit(self):
        before = "LIMIT = 1\n\n\ndef f():\n    return LIMIT\n"
        base = self.two_commits(before, before.replace("LIMIT = 1", "LIMIT = 2"))
        p = self.pack(base)
        self.assertEqual([u["name"] for u in p["units"]], ["<module>"])
        self.assertIn("LIMIT = 2", p["markdown"])

    def test_a_new_file_contributes_every_function(self):
        self.r.write("keep.py", "x = 1\n")
        base = self.r.commit("base")
        self.r.write("new.py", "def a():\n    return 1\n\n\ndef b():\n    return 2\n")
        self.r.commit("add")
        names = sorted(u["name"] for u in self.pack(base)["units"])
        self.assertEqual(names, ["a", "b"])

    def test_a_syntax_error_falls_back_to_the_whole_file_and_says_so(self):
        base = self.two_commits("def f():\n    return 1\n", "def f(:\n    return 1\n")
        p = self.pack(base)
        self.assertEqual([u["name"] for u in p["units"]], ["<whole file: not parseable>"])
        self.assertIn("def f(:", p["markdown"])


class Neighbours(SliceCase):
    def test_callers_are_found_by_plain_and_attribute_calls_and_unrelated_code_is_not(self):
        extra = {"other.py": "from m import f\n\n\ndef g():\n    return f()\n\n\ndef h(o):\n    return o.f()\n\n\ndef k():\n    return 0\n"}
        base = self.two_commits("def f():\n    return 1\n", "def f():\n    return 2\n", extra)
        c = {(x["file"], x["caller"]) for x in self.pack(base)["callers"]}
        self.assertEqual(c, {("other.py", "g"), ("other.py", "h")})

    def test_a_changed_function_that_calls_another_changed_one_is_not_listed_as_a_caller(self):
        before = "def a():\n    return b()\n\n\ndef b():\n    return 'OLD'\n"
        base = self.two_commits(before, before.replace("return b()", "return b() or 1").replace("'OLD'", "'NEW'"))
        p = self.pack(base)
        self.assertEqual(sorted(u["name"] for u in p["units"]), ["a", "b"])
        self.assertEqual(p["callers"], [], "a is already in the pack; listing it as a caller of b only adds noise")

    def test_tests_that_mention_a_changed_name_are_listed_by_path(self):
        extra = {"tests/test_m.py": "from m import f\n\n\ndef test_f():\n    assert f() == 1\n", "tests/test_other.py": "def test_x():\n    assert True\n"}
        base = self.two_commits("def f():\n    return 1\n", "def f():\n    return 2\n", extra)
        self.assertEqual(self.pack(base)["tests"], ["tests/test_m.py"])

    def test_non_python_files_are_listed_and_deleted_files_are_marked(self):
        self.r.write("README.md", "a\n")
        self.r.write("gone.py", "def old():\n    return 1\n")
        base = self.r.commit("base")
        self.r.write("README.md", "b\n")
        os.remove(os.path.join(self.r.d, "gone.py"))
        self.r.commit("edit")
        p = self.pack(base)
        self.assertEqual(p["units"], [])
        self.assertIn(("README.md", "modified"), [(o["file"], o["status"]) for o in p["other"]])
        self.assertIn(("gone.py", "deleted"), [(o["file"], o["status"]) for o in p["other"]])


class Size(SliceCase):
    def test_the_pack_is_much_smaller_than_the_changed_file_and_the_ratio_is_reported(self):
        body = "".join(BIG % (i, i) for i in range(200))
        before = body + "def target():\n    return 'OLD'\n"
        base = self.two_commits(before, before.replace("'OLD'", "'NEW'"))
        p = self.pack(base)
        self.assertGreater(p["full_chars"], 5000)
        self.assertLess(p["pack_chars"] * 10, p["full_chars"])
        self.assertAlmostEqual(p["ratio"], p["pack_chars"] / p["full_chars"], places=6)
        self.assertIn("estimate", p["markdown"])

    def test_max_chars_truncates_and_says_what_was_left_out(self):
        body = "".join("def f%d():\n    return %d\n\n\n" % (i, i) for i in range(40))
        base = self.two_commits(body, body.replace("return", "return 1 +"))
        p = self.pack(base, max_chars=600)
        self.assertLessEqual(len(p["markdown"]), 900)
        self.assertRegex(p["markdown"], r"left out: \d+ unit")


if __name__ == "__main__":
    unittest.main()
