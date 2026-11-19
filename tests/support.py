"""Shared helpers for the makeextreme tests. Standard library only."""
import hashlib, json, os, signal, subprocess, sys, tempfile, time, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mx(*args, **kw):
    """Run `python -m makeextreme <args>` and wait."""
    return subprocess.run([sys.executable, "-m", "makeextreme", *map(str, args)], cwd=REPO,
                          capture_output=True, text=True, **kw)


def mx_start(*args):
    return subprocess.Popen([sys.executable, "-m", "makeextreme", *map(str, args)], cwd=REPO,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for(path, secs=8):
    end = time.time() + secs
    while time.time() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


def wait_for_value(fn, secs=8):
    """The first truthy value `fn` returns within `secs`, else None. The runner records a
    stage's pgid right after it starts the stage, so a stage can print before that record
    is on disk: read the record by waiting for it, never by assuming it is already there."""
    end = time.time() + secs
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    return None


def gone(pgid, secs=3):
    """True once no process of the group is left (polls: SIGKILL delivery is not instantaneous)."""
    end = time.time() + secs
    while time.time() < end:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


class TaskCase(unittest.TestCase):
    def task(self, stages, files=None):
        tmp = tempfile.TemporaryDirectory(prefix="mx-")
        self.addCleanup(tmp.cleanup)
        d = tmp.name
        with open(os.path.join(d, "stages.json"), "w") as f:
            json.dump(stages, f)
        for name, text in (files or {}).items():
            self.write(d, name, text)
        return d

    @staticmethod
    def write(d, name, text):
        os.makedirs(os.path.dirname(os.path.join(d, name)), exist_ok=True)
        with open(os.path.join(d, name), "w") as f:
            f.write(text)

    @staticmethod
    def read(d, name):
        with open(os.path.join(d, name)) as f:
            return f.read()

    def lines(self, d, name):
        return len(self.read(d, name).splitlines()) if os.path.exists(os.path.join(d, name)) else 0

    def state(self, d):
        return json.loads(self.read(d, "task.json"))

    def journal(self, d):
        return [json.loads(x) for x in self.read(d, "journal.jsonl").splitlines()] \
            if os.path.exists(os.path.join(d, "journal.jsonl")) else []

    def events(self, d):
        return [e["ev"] for e in self.journal(d)]

    @staticmethod
    def sha(d, name="task.json"):
        with open(os.path.join(d, name), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
