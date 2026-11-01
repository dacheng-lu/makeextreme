"""makeextreme core: crash-safe stage runner. Standard library only, Linux (uses /proc).

Exit codes of `run`: 0 complete, 2 a stage failed, 3 locked by a live runner, 4 waiting for
approval, 5 an irreversible stage crashed or failed and needs `resolve`, 6 completion refused
(secret-shaped value in task.json/journal.jsonl/approvals.jsonl), 64 invalid stages.json or an
unreadable task.json.
"""
import fcntl, getpass, hashlib, json, os, signal, subprocess, sys, tempfile, time

from . import secret_scan

RUN_ID_ENV = "MAKEEXTREME_RUN_ID"
EX_FAILED, EX_LOCKED, EX_AWAITING, EX_UNCERTAIN, EX_SECRET, EX_SPEC = 2, 3, 4, 5, 6, 64


class SpecError(Exception):
    pass


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
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[19]
    except OSError:
        return None


def _file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dep_hash(base, rel):
    """Content hash of one declared dep: a file, a directory tree, or 'missing'."""
    p = os.path.join(base, rel)
    if os.path.islink(p):
        return "link:" + os.readlink(p)
    if os.path.isdir(p):
        h = hashlib.sha256()
        for root, dirs, files in os.walk(p):
            dirs.sort()
            for n in sorted(files):
                fp = os.path.join(root, n)
                one = "link:" + os.readlink(fp) if os.path.islink(fp) else (
                    _file_hash(fp) if os.path.isfile(fp) else "other")
                h.update(os.path.relpath(fp, p).encode() + b"\0" + one.encode() + b"\n")
        return h.hexdigest()
    if os.path.isfile(p):
        return _file_hash(p)
    return "missing" if not os.path.exists(p) else "other"


def fingerprint(d, sp):
    """A stage's identity: its command, its check and the content of its declared deps."""
    deps = {x: dep_hash(d, x) for x in sp.get("deps", [])}
    doc = {"run": sp["run"], "check": sp["check"], "deps": deps}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def validate_spec(spec):
    if not isinstance(spec, list) or not spec:
        raise SpecError("stages.json must be a non-empty list")
    seen = set()
    for sp in spec:
        if not isinstance(sp, dict):
            raise SpecError("every stage must be an object")
        sid = sp.get("id")
        if not (isinstance(sid, str) and sid) or sid in seen:
            raise SpecError(f"stage id missing or duplicated: {sid!r}")
        seen.add(sid)
        for k in ("run", "check"):
            if not (isinstance(sp.get(k), str) and sp[k]):
                raise SpecError(f"stage {sid}: '{k}' must be a non-empty string")
        deps = sp.get("deps", [])
        if not (isinstance(deps, list) and all(isinstance(x, str) and x for x in deps)):
            raise SpecError(f"stage {sid}: 'deps' must be a list of paths")
        if sp.get("approval", "required") != "required":
            raise SpecError(f"stage {sid}: 'approval' can only be \"required\"")
        if sp.get("approval") and not deps:
            raise SpecError(f"stage {sid}: an approval stage must declare the artifact it approves in 'deps'")


class Task:
    def __init__(self, d):
        self.d = d
        with open(os.path.join(d, "stages.json")) as f:
            self.spec = json.load(f)
        try:
            validate_spec(self.spec)
        except SpecError as e:
            raise SpecError(f"invalid stages.json: {e}")
        self.sp = os.path.join(d, "task.json")
        if os.path.exists(self.sp):
            try:
                with open(self.sp) as f:
                    self.state = json.load(f)
            except ValueError as e:
                raise SpecError(f"task.json is unreadable ({e}); restore it from a copy, or delete it "
                                "to start the task over")
        else:
            self.state = {"status": "new", "stages": {}}

    def save(self):
        atomic_write(self.sp, self.state)

    def log(self, ev, **kw):
        with open(os.path.join(self.d, "journal.jsonl"), "a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "ev": ev, **kw}) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def st(self, sid):
        return self.state["stages"].setdefault(sid, {"status": "pending", "attempts": 0})

    def halt(self, stage_status, sid, code, ev, **kw):
        self.st(sid)["status"] = stage_status
        self.state["status"] = stage_status
        self.save()
        self.log(ev, stage=sid, **kw)
        return code


def acquire(d):
    """Take the run lock: an exclusive flock on <task>/lock, held by the open descriptor until
    this runner ends (the kernel drops it on any death, so there is no stale lock to judge and no
    pid reuse to guard against). The file is never deleted: unlinking a flock file lets a second
    runner lock the old inode while a third creates a new one. Its content is only a note for
    the refusal message. Returns the descriptor; keep it open."""
    fd = os.open(os.path.join(d, "lock"), os.O_CREAT | os.O_RDWR, 0o644)  # not inheritable
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            holder = json.loads(os.pread(fd, 200, 0) or b"{}").get("pid")
        except ValueError:
            holder = None
        os.close(fd)
        print(f"locked by a live runner" + (f" (pid {holder})" if holder else ""), file=sys.stderr)
        sys.exit(EX_LOCKED)
    os.ftruncate(fd, 0)
    os.pwrite(fd, json.dumps({"pid": os.getpid(), "start": starttime(os.getpid())}).encode(), 0)
    return fd


def reap(s):
    """Kill what a crashed runner left behind: every process carrying the stage's run id
    (found via /proc, so it works even if the pgid never reached task.json), then its pgid."""
    killed = set()
    needle = f"{RUN_ID_ENV}={s['run_id']}".encode() if s.get("run_id") else None
    for name in os.listdir("/proc") if needle else ():
        if not name.isdigit() or int(name) == os.getpid():
            continue
        try:
            with open(f"/proc/{name}/environ", "rb") as f:
                if needle not in f.read().split(b"\0"):
                    continue
            pg = os.getpgid(int(name))
            if pg == os.getpgrp():
                os.kill(int(name), signal.SIGKILL)
            else:
                os.killpg(pg, signal.SIGKILL)
                killed.add(pg)
        except OSError:
            continue
    pg = s.get("pgid")
    if pg and pg not in killed and starttime(pg) == s.get("pg_start"):
        try:
            os.killpg(pg, signal.SIGKILL)
            killed.add(pg)
        except ProcessLookupError:
            pass
    return sorted(killed)


def secret_hits(d):
    """[{file, path, kind}] for every secret-shaped value in the task's own record files (never the value)."""
    hits = []
    for name in ("task.json", "journal.jsonl", "approvals.jsonl"):
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            text = f.read()
        for n, chunk in enumerate([text] if name == "task.json" else text.splitlines(), 1):
            if not chunk.strip():
                continue
            try:
                found = secret_scan.scan_state(json.loads(chunk))
            except ValueError:  # a line torn by a crash: scan it as plain text
                found = [("$", k) for k in secret_scan.scan_text(chunk)[:1]]
            where = "" if name == "task.json" else f" line {n}"
            hits += [{"file": name, "path": path + where, "kind": kind} for path, kind in found]
    return hits


def approvals_path(d):
    return os.path.join(d, "approvals.jsonl")


def approved(d, sid, digest):
    try:
        with open(approvals_path(d)) as f:
            return any((r := json.loads(x)).get("stage") == sid and r.get("digest") == digest
                       for x in f if x.strip())
    except OSError:
        return False


def _run(t, d):
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
    for sp in t.spec:
        sid, s = sp["id"], t.st(sp["id"])
        fp = fingerprint(d, sp)
        if s["status"] == "done":
            if s.get("digest") == fp:
                t.log("skip", stage=sid)
                continue
            t.log("invalidated", stage=sid)  # command or a declared dep changed
        if s["status"] in ("running", "interrupted") and sp.get("approval"):
            # an irreversible action may or may not have happened: never repeat it on our own
            for pg in reap(s):
                t.log("reaped", stage=sid, pgid=pg)
            return t.halt("uncertain", sid, EX_UNCERTAIN, "uncertain")
        if s["status"] == "uncertain":
            return t.halt("uncertain", sid, EX_UNCERTAIN, "uncertain")
        if s["status"] == "running":  # the previous runner died mid-stage
            t.log("recovered_from_crash", stage=sid)
            for pg in reap(s):
                t.log("reaped", stage=sid, pgid=pg)
        if sp.get("approval") and not approved(d, sid, fp):
            return t.halt("awaiting_approval", sid, EX_AWAITING, "awaiting_approval", digest=fp)
        run_id = os.urandom(8).hex()
        s.update(status="running", attempts=s["attempts"] + 1, digest=fp, run_id=run_id)
        s.pop("pgid", None)
        s.pop("pg_start", None)
        cur["sid"] = sid
        t.state["status"] = "running"
        t.save()
        t.log("start", stage=sid, attempt=s["attempts"])
        proc = subprocess.Popen(sp["run"], shell=True, cwd=d, start_new_session=True,
                                env={**os.environ, RUN_ID_ENV: run_id})
        cur["proc"] = proc
        s.update(pgid=proc.pid, pg_start=starttime(proc.pid))
        t.save()
        rc = proc.wait()
        chk = subprocess.run(sp["check"], shell=True, cwd=d, capture_output=True, text=True)
        ok = rc == 0 and chk.returncode == 0  # exit 0 alone is never "done"
        s.update(status="done" if ok else "failed", rc=rc, check_rc=chk.returncode,
                 check_out=chk.stdout.strip()[:200])
        for k in ("pgid", "pg_start", "run_id"):
            s.pop(k, None)
        t.save()
        t.log("end", stage=sid, ok=ok, rc=rc, check_rc=chk.returncode)
        if not ok and sp.get("approval"):
            # it may have acted before it failed (or acted and left no evidence): not ours to repeat
            return t.halt("uncertain", sid, EX_UNCERTAIN, "uncertain",
                          reason=f"failed: rc={rc} check_rc={chk.returncode}")
        if not ok:
            t.state["status"] = "failed"
            t.save()
            return EX_FAILED
    hits = secret_hits(d)
    if hits:  # F10: a credential in the record means the task is not complete
        t.state.update(status="refused_secret", secret_hits=hits)
        t.save()
        t.log("refused_secret", hits=len(hits))
        for h in hits:
            print(f"refused: {h['kind']} in {h['file']} at {h['path']}", file=sys.stderr)
        return EX_SECRET
    t.state["status"] = "complete"
    t.state.pop("secret_hits", None)
    t.save()
    return 0


def _locked(d, fn):
    lock = acquire(d)
    try:
        try:
            t = Task(d)
        except SpecError as e:
            print(f"refused: {e}", file=sys.stderr)
            return EX_SPEC
        return fn(t)
    finally:
        os.close(lock)


def run(d):
    return _locked(d, lambda t: _run(t, d))


def approve(d, sid):
    """Record a human's approval of the stage's artifact as it is right now. Only this command writes
    approvals.jsonl; the runner only reads it. (It cannot tell who typed it: see ARCHITECTURE D10.)"""
    try:
        t = Task(d)
    except SpecError as e:
        print(f"refused: {e}", file=sys.stderr)
        return EX_SPEC
    sp = next((x for x in t.spec if x["id"] == sid), None)
    if sp is None or not sp.get("approval"):
        print(f"refused: {sid!r} is not an approval stage of this task", file=sys.stderr)
        return 1
    hashes = {x: dep_hash(d, x) for x in sp["deps"]}
    if "missing" in hashes.values():
        print("refused: the artifact does not exist yet: "
              + ", ".join(k for k, v in hashes.items() if v == "missing"), file=sys.stderr)
        return 1
    digest = fingerprint(d, sp)
    with open(approvals_path(d), "a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), "stage": sid, "digest": digest,
                            "by": getpass.getuser()}) + "\n")
        f.flush()
        os.fsync(f.fileno())
    print(f"approved {sid} @ {digest[:12]}")
    for k, v in hashes.items():
        print(f"  {k}  {v[:12]}")
    return 0


def resolve(d, sid, mode):
    """Settle an 'uncertain' stage by an explicit human decision: --done (only if its check passes) or --retry."""
    def go(t):
        s = t.state["stages"].get(sid)
        sp = next((x for x in t.spec if x["id"] == sid), None)
        if s is None or sp is None or s["status"] != "uncertain":
            print(f"refused: {sid!r} is not uncertain", file=sys.stderr)
            return 1
        if mode == "--done":
            chk = subprocess.run(sp["check"], shell=True, cwd=d, capture_output=True, text=True)
            if chk.returncode != 0:
                print("refused: the stage's check does not pass, so it cannot be marked done", file=sys.stderr)
                return 1
            s.update(status="done", digest=fingerprint(d, sp), check_rc=0, check_out=chk.stdout.strip()[:200])
        else:
            s["status"] = "pending"
        t.state["status"] = "resolved"
        t.save()
        t.log("resolved", stage=sid, mode=mode)
        return 0
    return _locked(d, go)
