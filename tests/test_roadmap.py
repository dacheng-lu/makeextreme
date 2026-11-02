"""ROADMAP.md stays true to the repository: the current version is listed as released, the sections that keep it
honest exist, and every relative link points at a real file. Standard library only."""
import os
import re
import sys
import unittest

from support import REPO

sys.path.insert(0, REPO)
from makeextreme import __version__  # noqa: E402

SECTIONS = ["Released", "Owed", "Candidate", "Not planned"]


def roadmap():
    with open(os.path.join(REPO, "ROADMAP.md"), encoding="utf-8") as f:
        return f.read()


def section(name):
    parts = re.split(r"(?m)^## ", roadmap())
    hit = [p for p in parts if p.startswith(name)]
    assert hit, "no '## %s' section" % name
    return hit[0]


class Roadmap(unittest.TestCase):
    def test_the_sections_that_keep_it_honest_exist_in_order(self):
        heads = re.findall(r"(?m)^## (\w+(?: \w+)?)", roadmap())
        order = [h for h in heads if any(h.startswith(s) for s in SECTIONS)]
        self.assertEqual([next(s for s in SECTIONS if h.startswith(s)) for h in order], SECTIONS)

    def test_the_current_version_is_listed_as_released(self):
        self.assertRegex(section("Released"), r"(?m)^- \*\*%s\*\* " % re.escape(__version__),
                         "the roadmap does not list %s under Released" % __version__)

    def test_a_release_that_refuses_what_the_previous_one_accepted_is_not_called_a_patch(self):
        entry = next(l for l in section("Released").splitlines() if l.startswith("- **%s**" % __version__))
        self.assertRegex(entry, r"(?i)tighten")
        self.assertRegex(entry, r"accepted by 1\.1\.0")
        self.assertNotRegex(__version__, r"^\d+\.\d+\.[1-9]")

    def test_nothing_after_the_current_version_is_listed_as_released(self):
        listed = re.findall(r"(?m)^- \*\*(\d+\.\d+\.\d+)\*\*", section("Released"))
        newest = max(listed, key=lambda v: tuple(map(int, v.split("."))))
        self.assertEqual(newest, __version__, "the roadmap lists a released version the code does not have")

    def test_the_readme_links_to_the_roadmap(self):
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
            self.assertIn("](ROADMAP.md)", f.read())

    def test_every_relative_link_in_the_roadmap_points_at_a_file_that_exists(self):
        targets = [t for t in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", roadmap()) if "://" not in t]
        self.assertGreater(len(targets), 3)
        for target in targets:
            self.assertTrue(os.path.exists(os.path.join(REPO, target)), "the roadmap links to missing %s" % target)


if __name__ == "__main__":
    unittest.main()
