"""A platform the runner cannot support is refused in one line, not by an ImportError.

Measured on Windows: `python -m makeextreme run <dir>` died with
`ModuleNotFoundError: No module named 'fcntl'` and exit 1 — a traceback, not one of the
documented exit codes, and no statement that the task was never started.
"""
import io
import sys
import unittest
from unittest import mock

from support import REPO

sys.path.insert(0, REPO)
from makeextreme import __main__  # noqa: E402


class PlatformGuard(unittest.TestCase):
    def test_posix_is_not_refused(self):
        with mock.patch("os.name", "posix"):
            self.assertIsNone(__main__.platform_refusal())

    def test_a_non_posix_platform_is_refused_before_core_is_imported(self):
        err = io.StringIO()
        with mock.patch("os.name", "nt"), mock.patch("sys.stderr", err):
            self.assertEqual(__main__.platform_refusal(), __main__.PLATFORM_REFUSAL)
            code = __main__.main(["run", "some-task-dir"])
        self.assertEqual(code, 64)
        message = err.getvalue()
        self.assertIn("Linux-only", message)
        self.assertIn("Nothing was started", message)
        self.assertNotIn("some-task-dir", message, "the refusal is not a task error")


if __name__ == "__main__":
    unittest.main()
