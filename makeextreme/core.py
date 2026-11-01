"""makeextreme core: crash-safe stage runner. Standard library only, Linux (uses /proc).

Exit codes of `run`: 0 complete, 2 a stage failed, 3 locked by a live runner, 4 waiting for
approval, 5 an irreversible stage crashed or failed and needs `resolve`, 6 completion refused
(secret-shaped value in task.json/journal.jsonl/approvals.jsonl), 64 invalid stages.json, an
unreadable task.json or dependency, or a missing task directory, 130/143 stopped by SIGINT/SIGTERM.
`approve` and `resolve` use 0 for done, 1 for a refusal (not an approval stage, artifact missing,
stage not uncertain, check does not pass), 64 as above (`resolve` also 3 while a runner holds the lock).
"""
import fcntl, getpass, hashlib, json, os, signal, subprocess, sys, tempfile, time

from . import secret_scan

RUN_ID_ENV = "MAKEEXTREME_RUN_ID"
EX_FAILED, EX_LOCKED, EX_AWAITING, EX_UNCERTAIN, EX_SECRET, EX_SPEC = 2, 3, 4, 5, 6, 64


class SpecError(Exception):
    pass


def atomic_write(path, obj):
    # SIGTERM/SIGINT stay pending from mkstemp until the cleanup below is in place, so a signal can
    # never land while the temp file exists and nothing is responsible for removing it
    held = signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGTERM, signal.SIGINT))
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    except BaseException:
        signal.pthread_sigmask(signal.SIG_SETMASK, held)
        raise
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, held)
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:  # incl. the SystemExit of the signal handler: leave no stray temp file
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_line(path, line):
    """Append one record. A crash can leave the file without its final newline: end that fragment
    first, in the same write, so the new record is not glued to it and lost."""
    with open(path, "a+b") as f:
        end = f.seek(0, os.SEEK_END)
        torn = False
        if end:
            f.seek(end - 1)
            torn = f.read(1) != b"\n"
        f.write((b"\n" if torn else b"") + line.encode() + b"\n")
        f.flush()
        os.fsync(f.fileno())


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


def _path_hash(p, stack, memo):
    """Content hash of one entry. A symlink counts by its text AND by what it points to now (hashed
    together, so neither a text that is not UTF-8 nor the target's size matters for display); a
    directory by its entries' names and hashes. `stack` holds the real directories on the way down
    (a link back into one of them is a cycle, not an endless walk); `memo` holds every real path
    already hashed in this call, so links that fan out to the same place are read once."""
    if os.path.islink(p):
        target = os.path.realpath(p)
        inner = _path_hash(target, stack, memo) if os.path.exists(target) else "dangling"
        text = os.readlink(p) + ">" + inner
        return hashlib.sha256(("link:" + text).encode("utf-8", "surrogateescape")).hexdigest()
    real = os.path.realpath(p)
    if os.path.isdir(p):
        if real in stack:
            return "cycle"
        if real in memo:
            return memo[real]
        try:
            names = sorted(os.listdir(p))
        except OSError as e:
            raise SpecError(f"cannot read dependency {p}: {e.strerror or e}")
        h = hashlib.sha256()
        for n in names:
            one = _path_hash(os.path.join(p, n), stack | {real}, memo)
            h.update(n.encode("utf-8", "surrogateescape") + b"\0" + one.encode() + b"\n")
        memo[real] = h.hexdigest()
        return memo[real]
    if os.path.isfile(p):
        if real not in memo:
            try:
                memo[real] = _file_hash(p)
            except OSError as e:
                raise SpecError(f"cannot read dependency {p}: {e.strerror or e}")
        return memo[real]
    return "missing" if not os.path.lexists(p) else "other"


def dep_hash(base, rel):
    """Content hash of one declared dep: a file, a directory tree, a symlink (and its target), or
    'missing' (also for a symlink that points nowhere: that is no artifact)."""
    p = os.path.join(base, rel)
    if os.path.islink(p) and not os.path.exists(p):
        return "missing"
    try:
        return _path_hash(p, frozenset(), {})
    except RecursionError:
        raise SpecError(f"dependency {rel!r} is nested too deeply to hash")


def fingerprint(d, sp, hashes=None):
    """A stage's identity: its command, its check and the content of its declared deps.
    `hashes` lets a caller that already hashed the deps (approve) bind exactly what it showed."""
    deps = hashes if hashes is not None else {x: dep_hash(d, x) for x in sp.get("deps", [])}
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


def load_spec(d):
    """The task's stages, or a SpecError that says what is wrong (nothing is created in `d`)."""
    if not os.path.isdir(d):
        raise SpecError(f"task directory does not exist: {d}")
    try:
        with open(os.path.join(d, "stages.json")) as f:
            spec = json.load(f)
    except OSError as e:
        raise SpecError(f"invalid stages.json: cannot read it ({e.strerror})")
    except ValueError as e:
        raise SpecError(f"invalid stages.json: not valid JSON ({e})")
    try:
        validate_spec(spec)
    except SpecError as e:
        raise SpecError(f"invalid stages.json: {e}")
    return spec


class Task:
    def __init__(self, d):
        self.d = d
        self.spec = load_spec(d)
        self.sp = os.path.join(d, "task.json")
        if os.path.exists(self.sp):
            try:
                with open(self.sp) as f:
                    self.state = json.load(f)
            except ValueError as e:
                raise SpecError(f"task.json is unreadable ({e}); restore it from a copy, or move task.json AND "
                                "approvals.jsonl aside to start the task over (approvals are spent by "
                                "the runs recorded in task.json, so keeping them would release the "
                                "stages again)")
        else:
            self.state = {"status": "new", "stages": {}}

    def save(self):
        atomic_write(self.sp, self.state)

    def log(self, ev, **kw):
        append_line(os.path.join(self.d, "journal.jsonl"),
                    json.dumps({"t": round(time.time(), 3), "ev": ev, **kw}))

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
        with open(p, errors="replace") as f:
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


def approved(d, sid, digest, since=0):
    """Is there an approval of exactly this stage and artifact that was written AFTER the stage last
    started (`since`)? An approval authorises one execution: it is spent when the stage starts, so an
    artifact that changes away and comes back does not bring an old approval back to life."""
    if isinstance(since, bool) or not isinstance(since, (int, float)):
        return False  # a damaged `started`: never guess that an approval is still unspent
    try:
        with open(approvals_path(d), errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return False
    for x in lines:
        try:
            r = json.loads(x)
        except ValueError:
            continue  # a line torn by a crash is not an approval (and not a reason to crash)
        if (isinstance(r, dict) and r.get("stage") == sid and r.get("digest") == digest
                and isinstance(r.get("t"), (int, float)) and r["t"] > since):
            return True
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
        running = cur["sid"] if cur["sid"] and t.st(cur["sid"])["status"] == "running" else None
        if running:  # a stage that already ended (done/failed) must not be undone by a late signal
            t.st(running)["status"] = "interrupted"
        t.state["status"] = "interrupted"
        t.save()
        t.log("interrupted", stage=running, sig=sig)
        sys.exit(128 + sig)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    for sp in t.spec:
        sid, s = sp["id"], t.st(sp["id"])
        try:
            fp = fingerprint(d, sp)
        except SpecError as e:  # a dep became unreadable between stages: say so in the record
            t.state["status"] = "refused"
            t.save()
            t.log("refused", stage=sid, reason=str(e))
            raise
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
        if s["status"] in ("running", "interrupted"):  # the previous runner died or was stopped mid-stage
            t.log("recovered_from_crash" if s["status"] == "running" else "recovered_from_interrupt", stage=sid)
            for pg in reap(s):
                t.log("reaped", stage=sid, pgid=pg)
        if sp.get("approval") and not (approved(d, sid, fp, s.get("started", 0))
                                       or (s.get("retry") is not None and s.get("retry") == fp)):
            if approved(d, sid, fp):  # one is on record, but a start has already used it
                print(f"note: the approval on record for {sid!r} was already used by a start at "
                      f"{s.get('started')}; approve again to release it once more", file=sys.stderr)
            return t.halt("awaiting_approval", sid, EX_AWAITING, "awaiting_approval", digest=fp)
        run_id = os.urandom(8).hex()
        s.update(status="running", attempts=s["attempts"] + 1, digest=fp, run_id=run_id,
                 started=round(time.time(), 3))  # spends the approval that released this run
        s.pop("retry", None)  # and the explicit retry, if that is what released it
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
        chk = subprocess.run(sp["check"], shell=True, cwd=d, capture_output=True, text=True, errors="replace")
        ok = rc == 0 and chk.returncode == 0  # exit 0 alone is never "done"
        # an approval stage that failed is `uncertain` from the first write on: a kill between two
        # writes must never leave `failed` behind (a plain run would repeat the irreversible command)
        s.update(status="done" if ok else ("uncertain" if sp.get("approval") else "failed"), rc=rc, check_rc=chk.returncode,
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
    try:
        load_spec(d)  # refuse a bad task before the lock file is created next to it
    except SpecError as e:
        print(f"refused: {e}", file=sys.stderr)
        return EX_SPEC
    lock = acquire(d)
    try:
        try:
            return fn(Task(d))
        except SpecError as e:
            print(f"refused: {e}", file=sys.stderr)
            return EX_SPEC
    finally:
        os.close(lock)


def run(d):
    return _locked(d, lambda t: _run(t, d))


def approve(d, sid):
    """Record a human's approval of the stage's artifact as it is right now. Only this command writes
    approvals.jsonl; the runner only reads it. (It cannot tell who typed it: see ARCHITECTURE D10.)"""
    try:
        t = Task(d)
        sp = next((x for x in t.spec if x["id"] == sid), None)
        if sp is None or not sp.get("approval"):
            print(f"refused: {sid!r} is not an approval stage of this task", file=sys.stderr)
            return 1
        hashes = {x: dep_hash(d, x) for x in sp["deps"]}  # hashed once: what is shown is what is bound
        if "missing" in hashes.values():
            print("refused: the artifact does not exist yet: "
                  + ", ".join(k for k, v in hashes.items() if v == "missing"), file=sys.stderr)
            return 1
        digest = fingerprint(d, sp, hashes)
    except SpecError as e:
        print(f"refused: {e}", file=sys.stderr)
        return EX_SPEC
    append_line(approvals_path(d), json.dumps({"t": round(time.time(), 3), "stage": sid, "digest": digest,
                                               "by": getpass.getuser()}))
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
            chk = subprocess.run(sp["check"], shell=True, cwd=d, capture_output=True, text=True, errors="replace")
            if chk.returncode != 0:
                print("refused: the stage's check does not pass, so it cannot be marked done", file=sys.stderr)
                return 1
            s.update(status="done", digest=fingerprint(d, sp), check_rc=0, check_out=chk.stdout.strip()[:200])
        else:
            s["status"] = "pending"
            s["retry"] = s.get("digest")  # repeats the run that failed (this artifact) once; `started` stays
        t.state["status"] = "resolved"
        t.save()
        t.log("resolved", stage=sid, mode=mode)
        return 0
    old = signal.signal(signal.SIGTERM, lambda sig, _frame: sys.exit(128 + sig))
    try:
        return _locked(d, go)
    finally:
        signal.signal(signal.SIGTERM, old)
