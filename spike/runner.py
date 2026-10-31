#!/usr/bin/env python3
"""M0 spike: crash-safe stage runner. stdlib only. A feasibility proof, not the product.

Usage: runner.py run <task_dir>      (task_dir holds stages.json; run again = resume)

Known gap (by design, spike): a SIGKILL between Popen and the state save loses the
child's pgid, so that one orphan would not be reaped. Closing it is an M1 item.
"""
import json, os, signal, subprocess, sys, tempfile, time


def atomic_write(path, obj):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def starttime(pid):
    """Process start tick from /proc; guards against pid reuse. None if the pid is gone."""
    try:
        return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19]
    except OSError:
        return None


class Task:
    def __init__(self, d):
        self.d = d
        self.spec = json.load(open(os.path.join(d, "stages.json")))
        self.sp = os.path.join(d, "task.json")
        self.state = json.load(open(self.sp)) if os.path.exists(self.sp) else {"status": "new", "stages": {}}

    def save(self):
        atomic_write(self.sp, self.state)

    def log(self, ev, **kw):
        with open(os.path.join(self.d, "journal.jsonl"), "a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "ev": ev, **kw}) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def st(self, sid):
        return self.state["stages"].setdefault(sid, {"status": "pending", "attempts": 0})


def acquire(d):
    p = os.path.join(d, "lock")
    me = json.dumps({"pid": os.getpid(), "start": starttime(os.getpid())}).encode()
    for _ in range(2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, me)
            os.close(fd)
            return p
        except FileExistsError:
            try:
                h = json.load(open(p))
            except (OSError, ValueError):
                h = {}
            if h.get("pid") and starttime(h["pid"]) == h.get("start"):
                print(f"locked by live pid {h['pid']}", file=sys.stderr)
                sys.exit(3)
            os.unlink(p)  # holder is dead: stale lock
    sys.exit(3)


def run(d):
    lock = acquire(d)
    t = Task(d)
    cur = {"sid": None, "proc": None}

    def on_signal(sig, _frame):
        p = cur["proc"]
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if cur["sid"]:
            t.st(cur["sid"])["status"] = "interrupted"
        t.state["status"] = "interrupted"
        t.save()
        t.log("interrupted", stage=cur["sid"], sig=sig)
        sys.exit(128 + sig)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        for sp in t.spec:
            sid, s = sp["id"], t.st(sp["id"])
            if s["status"] == "done":
                t.log("skip", stage=sid)
                continue
            if s["status"] == "running":  # the previous runner died mid-stage
                t.log("recovered_from_crash", stage=sid)
                if s.get("pgid") and starttime(s["pgid"]) == s.get("pg_start"):
                    os.killpg(s["pgid"], signal.SIGKILL)
                    t.log("reaped", stage=sid, pgid=s["pgid"])
            s.update(status="running", attempts=s["attempts"] + 1)
            cur["sid"] = sid
            t.state["status"] = "running"
            t.save()
            t.log("start", stage=sid, attempt=s["attempts"])
            proc = subprocess.Popen(sp["run"], shell=True, cwd=d, start_new_session=True)
            cur["proc"] = proc
            s.update(pgid=proc.pid, pg_start=starttime(proc.pid))
            t.save()
            rc = proc.wait()
            chk = subprocess.run(sp["check"], shell=True, cwd=d, capture_output=True, text=True)
            ok = rc == 0 and chk.returncode == 0  # exit 0 alone is never "done"
            s.update(status="done" if ok else "failed", rc=rc, check_rc=chk.returncode,
                     check_out=chk.stdout.strip()[:200])
            s.pop("pgid", None)
            s.pop("pg_start", None)
            t.save()
            t.log("end", stage=sid, ok=ok, rc=rc, check_rc=chk.returncode)
            if not ok:
                t.state["status"] = "failed"
                t.save()
                return 2
        t.state["status"] = "complete"
        t.save()
        return 0
    finally:
        if os.path.exists(lock):
            os.unlink(lock)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "run":
        sys.exit("usage: runner.py run <task_dir>")
    sys.exit(run(sys.argv[2]))
