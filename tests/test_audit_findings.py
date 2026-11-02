"""Findings of the M1 milestone audit (Sonnet, 2026-11-01), each with the test that was red first.

E1 a SIGTERM between two stages undid the stage that had just finished
E2 a child that ignores SIGTERM kept running while the next run started the stage again
E3 non-UTF-8 bytes in a check's output crashed the runner for good
E4 symlinks in `deps` were hashed by their text, so a changed target left an approval valid
E5 a torn last line in approvals.jsonl / journal.jsonl swallowed the next entry
E8 an unreadable dep was a traceback
E9 `approve` hashed twice: the hash shown could differ from the one bound
X1-X4 four mutants that survived the harness
"""
import contextlib, io, json, os, signal, subprocess, sys, time, unittest
from unittest import mock

from support import REPO, TaskCase, gone, mx, mx_start, wait_for

sys.path.insert(0, REPO)
from makeextreme import core  # noqa: E402

KEY = "sk-" + "a1B2c3D4" * 4


class ProcNamespaceGuard(unittest.TestCase):
    def test_matching_mismatching_and_missing_proc(self):
        with mock.patch.object(core.os, 'getpid', return_value=42), \
             mock.patch.object(core.os, 'readlink', return_value='42'), \
             mock.patch('builtins.open', mock.mock_open(read_data='NSpid:\t42\n')), \
             mock.patch.object(core, '_locked', return_value=17) as locked:
            self.assertEqual(core.run('task'), 17)
            locked.assert_called_once()
        cases = [('999', 'NSpid:\t999 42\n'),
                 ('42', 'NSpid:\t42 42\n'),  # equal IDs in different namespaces
                 ('42', 'Name:\tpython\n'),
                 (OSError('no proc'), '')]
        for link, status in cases:
            with self.subTest(link=link, status=status), \
                 mock.patch.object(core.os, 'getpid', return_value=42), \
                 mock.patch.object(core.os, 'readlink', side_effect=link if isinstance(link, OSError) else None,
                                   return_value=link if isinstance(link, str) else None), \
                 mock.patch('builtins.open', mock.mock_open(read_data=status)), \
                 mock.patch.object(core, '_locked') as locked, \
                 mock.patch.object(core.os, 'killpg') as killpg, \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(core.run('task'), core.EX_SPEC)
                with self.assertRaises(core.SpecError):
                    core.reap({'run_id': 'x'})
                locked.assert_not_called()
                killpg.assert_not_called()



def sparse(d, name, gib):
    with open(os.path.join(d, name), "wb") as f:
        f.truncate(gib << 30)


def wait_event(case, d, ev, secs=15):
    end = time.time() + secs
    while time.time() < end:
        if ev in case.events(d):
            return True
        time.sleep(0.02)
    return False


class SigtermBetweenStages(TaskCase):
    """E1: the runner is hashing stage b's 2 GiB dep when SIGTERM arrives; stage a is done."""

    def go(self, a_extra, prepare=lambda d: None):
        spec = [{"id": "a", "run": "echo a >> a.out", "check": "test -s a.out", **a_extra},
                {"id": "b", "run": "echo b >> b.out", "check": "test -s b.out", "deps": ["big"]}]
        d = self.task(spec, {"art": "v1\n"})
        sparse(d, "big", 2)
        prepare(d)
        r = mx_start("run", d)
        self.assertTrue(wait_event(self, d, "end"), "stage a never finished")
        time.sleep(0.3)
        r.send_signal(signal.SIGTERM)
        self.assertEqual(r.wait(), 143)
        return d

    def test_a_finished_ordinary_stage_stays_done_and_is_not_repeated(self):
        d = self.go({})
        self.assertEqual(self.state(d)["stages"]["a"]["status"], "done")
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.lines(d, "a.out"), self.lines(d, "b.out")), (1, 1))

    def test_a_finished_irreversible_stage_does_not_become_uncertain(self):
        def approve(d):
            self.assertEqual(mx("run", d).returncode, 4)
            self.assertEqual(mx("approve", d, "a").returncode, 0)
        d = self.go({"deps": ["art"], "approval": "required"}, approve)
        self.assertEqual(self.state(d)["stages"]["a"]["status"], "done")
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)  # not 5
        self.assertEqual(self.lines(d, "a.out"), 1)


class InterruptedStageIsReaped(TaskCase):
    """E2: after a SIGTERM the stage is `interrupted`; whatever of it still lives is killed before it re-runs."""

    def test_an_orphan_of_an_interrupted_ordinary_stage_is_reaped_before_the_rerun(self):
        d = self.task([{"id": "s", "run": "echo ok >> out", "check": "test -s out"}])
        orphan = subprocess.Popen(["sleep", "60"], start_new_session=True,
                                  env={**os.environ, core.RUN_ID_ENV: "deadbeefdeadbeef"})
        self.addCleanup(lambda: (orphan.poll() is None and orphan.kill(), orphan.wait()))
        self.write(d, "task.json", json.dumps({"status": "interrupted", "stages": {
            "s": {"status": "interrupted", "attempts": 1, "digest": "x", "run_id": "deadbeefdeadbeef"}}}))
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        try:  # it is our child: waiting reaps the zombie, and -9 says it was killed, not that it ended
            code = orphan.wait(timeout=3)
        except subprocess.TimeoutExpired:
            code = None
        self.assertEqual(code, -signal.SIGKILL, "the orphan of the interrupted stage was left running")
        self.assertIn("reaped", self.events(d))
        self.assertIn("recovered_from_interrupt", self.events(d))  # named for what happened (not a crash)
        self.assertNotIn("recovered_from_crash", self.events(d))
        self.assertEqual(self.lines(d, "out"), 1)

    def test_a_child_that_ignores_sigterm_does_not_run_beside_the_rerun(self):
        run = "trap '' TERM; echo start >> out; sleep 2; echo done >> out"
        d = self.task([{"id": "s", "run": run, "check": "grep -q done out"}])
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "out")))
        r.send_signal(signal.SIGTERM)
        self.assertEqual(r.wait(), 143)
        self.assertEqual(self.state(d)["stages"]["s"]["status"], "interrupted")
        self.assertEqual(mx("run", d).returncode, 0)
        time.sleep(2.6)  # long enough for a surviving first child to write its own `done`
        self.assertEqual(self.read(d, "out").split(), ["start", "start", "done"])


class NonUtf8Check(TaskCase):
    """E3"""

    def test_a_check_that_prints_non_utf8_bytes_still_completes(self):
        d = self.task([{"id": "s", "run": "echo x >> c", "check": "printf '\\377\\376'; test -s c"}])
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.state(d)["stages"]["s"]["status"], "done")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertIn("skip", self.events(d))
        self.assertEqual(self.lines(d, "c"), 1)

    def test_resolve_done_survives_non_utf8_check_output(self):
        run = "echo started >> rs; if [ -f go ]; then echo ok > sent.ok; else sleep 30; fi"
        spec = [{"id": "send", "run": run, "check": "printf '\\377'; test -s sent.ok", "deps": ["art"],
                 "approval": "required"}]
        d = self.task(spec, {"art": "v1\n"})
        mx("run", d)
        mx("approve", d, "send")
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "rs")))
        os.kill(r.pid, signal.SIGKILL)
        r.wait()
        self.assertEqual(mx("run", d).returncode, 5)
        self.write(d, "sent.ok", "ok\n")
        res = mx("resolve", d, "send", "--done")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Traceback", res.stderr)


def send_spec(dep="link.txt"):
    return [{"id": "send", "run": "echo sent >> rs", "check": "test -s rs", "deps": [dep], "approval": "required"}]


class SymlinkDeps(TaskCase):
    """E4: a symlink counts by what it points to now, not only by its text."""

    def runs_after(self, d, change):
        self.assertEqual(mx("run", d).returncode, 0)
        before = self.lines(d, "r")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "r"), before, "an unchanged tree must skip")
        change()
        self.assertEqual(mx("run", d).returncode, 0)
        return self.lines(d, "r") - before

    SPEC = [{"id": "z", "run": "echo z >> r", "check": "test -s r", "deps": ["dep"]}]

    def test_a_file_symlink_dep_follows_its_target(self):
        d = self.task(self.SPEC, {"real.txt": "1\n"})
        os.symlink("real.txt", os.path.join(d, "dep"))
        self.assertEqual(self.runs_after(d, lambda: self.write(d, "real.txt", "2\n")), 1)

    def test_a_symlink_inside_a_dep_directory_follows_its_target(self):
        d = self.task(self.SPEC, {"outside/f": "1\n", "dep/own": "x\n"})
        os.symlink(os.path.join(d, "outside", "f"), os.path.join(d, "dep", "link"))
        self.assertEqual(self.runs_after(d, lambda: self.write(d, "outside/f", "2\n")), 1)

    def test_a_directory_symlink_inside_a_dep_directory_follows_its_target(self):
        d = self.task(self.SPEC, {"other/f": "1\n", "dep/own": "x\n"})
        os.symlink(os.path.join(d, "other"), os.path.join(d, "dep", "more"))
        self.assertEqual(self.runs_after(d, lambda: self.write(d, "other/f", "2\n")), 1)

    def test_a_symlink_cycle_does_not_hang_or_crash(self):
        d = self.task(self.SPEC, {"dep/f": "1\n"})
        os.symlink(".", os.path.join(d, "dep", "loop"))
        os.symlink(os.path.join(d, "dep"), os.path.join(d, "dep", "again"))
        self.assertEqual(self.runs_after(d, lambda: self.write(d, "dep/f", "2\n")), 1)

    def test_an_approval_does_not_survive_a_change_behind_a_symlink(self):
        d = self.task(send_spec(), {"real.txt": "v1\n"})
        os.symlink("real.txt", os.path.join(d, "link.txt"))
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.write(d, "real.txt", "v2, something else\n")
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(self.lines(d, "rs"), 0)

    def test_a_dangling_symlink_is_a_missing_artifact(self):
        d = self.task(send_spec())
        os.symlink("nowhere.txt", os.path.join(d, "link.txt"))
        res = mx("approve", d, "send")
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("does not exist", res.stderr)
        self.assertFalse(os.path.exists(os.path.join(d, "approvals.jsonl")))


class TornTails(TaskCase):
    """E5: a crash can leave a record file without its final newline; the next entry must not be glued to it."""

    def test_an_approval_after_a_torn_approvals_line_is_not_lost(self):
        d = self.task([{"id": "make", "run": "echo v > art", "check": "test -s art"},
                       {"id": "send", "run": "echo sent >> rs", "check": "test -s rs", "deps": ["art"],
                        "approval": "required"}])
        self.assertEqual(mx("run", d).returncode, 4)
        with open(os.path.join(d, "approvals.jsonl"), "a") as f:
            f.write('{"t": 1.5, "stage": "sen')  # no newline
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0, "the approval was glued to the torn fragment and lost")
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_a_journal_entry_after_a_torn_journal_line_is_not_lost(self):
        d = self.task([{"id": "s", "run": "echo x >> c", "check": "test -s c"}])
        self.write(d, "journal.jsonl", '{"t": 1.5, "ev": "sta')  # no newline
        self.assertEqual(mx("run", d).returncode, 0)
        parsed, bad = [], 0
        for line in self.read(d, "journal.jsonl").splitlines():
            try:
                parsed.append(json.loads(line)["ev"])
            except ValueError:
                bad += 1
        self.assertEqual(bad, 1, "exactly the torn fragment may be unreadable")
        self.assertEqual(parsed, ["start", "end"])


def unreadable_dep(d, name="unreadable"):
    """A dep that cannot be read by ANY uid (root included): its read fails with EIO."""
    os.symlink("/proc/self/mem", os.path.join(d, name))
    return name


class UnreadableDep(TaskCase):
    """E8"""

    def test_an_unreadable_dep_is_a_clean_refusal_for_run_and_approve(self):
        d = self.task(send_spec("unreadable"))
        unreadable_dep(d)
        for cmd in (("run", d), ("approve", d, "send")):
            res = mx(*cmd)
            self.assertEqual(res.returncode, 64, (cmd[0], res.stderr))
            self.assertIn("cannot read dependency", res.stderr)
            self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.lines(d, "rs"), 0)
        self.assertFalse(os.path.exists(os.path.join(d, "approvals.jsonl")))

    def test_a_dep_that_turns_unreadable_mid_run_leaves_a_refused_task_and_no_repeat_later(self):
        """N5: stage a is done, stage b's dep cannot be read: not a silent `running`, and a is not repeated."""
        spec = [{"id": "a", "run": "echo a >> a.out", "check": "test -s a.out"},
                {"id": "b", "run": "echo b >> b.out", "check": "test -s b.out", "deps": ["dep"]}]
        d = self.task(spec)
        unreadable_dep(d, "dep")
        res = mx("run", d)
        self.assertEqual(res.returncode, 64, res.stderr)
        st = self.state(d)
        self.assertEqual((st["status"], st["stages"]["a"]["status"]), ("refused", "done"))
        self.assertIn("refused", self.events(d))
        os.unlink(os.path.join(d, "dep"))
        self.write(d, "dep", "fixed\n")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual((self.lines(d, "a.out"), self.lines(d, "b.out")), (1, 1))


class ApproveHashesOnce(TaskCase):
    """E9: the hash a person is shown is the hash that is bound."""

    def test_approve_reads_each_dep_once_and_binds_what_it_printed(self):
        d = self.task(send_spec("art"), {"art": "v1\n"})
        with mock.patch.object(core, "dep_hash", wraps=core.dep_hash) as spy, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(core.approve(d, "send"), 0)
        self.assertEqual(spy.call_count, 1)
        bound = json.loads(self.read(d, "approvals.jsonl"))["digest"]
        self.assertEqual(bound, core.fingerprint(d, send_spec("art")[0]))


class MoreSurvivors(TaskCase):
    """X1-X4: behaviours the harness could change without any test noticing."""

    def test_x1_a_credential_in_approvals_refuses_completion(self):
        d = self.task([{"id": "s", "run": "echo ok > ok", "check": "test -s ok"}])
        self.write(d, "approvals.jsonl", json.dumps({"stage": "other", "digest": "d", "by": KEY}) + "\n")
        res = mx("run", d)
        self.assertEqual(res.returncode, 6, res.stderr)
        self.assertNotIn(KEY, res.stdout + res.stderr)
        self.assertEqual([h["file"] for h in self.state(d)["secret_hits"]], ["approvals.jsonl"])

    def test_x2_a_recorded_pgid_that_is_not_ours_any_more_is_never_killed(self):
        bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (bystander.poll() is None and bystander.kill(), bystander.wait()))
        d = self.task([{"id": "s", "run": "echo ok >> out", "check": "test -s out"}])
        self.write(d, "task.json", json.dumps({"status": "running", "stages": {"s": {
            "status": "running", "attempts": 1, "digest": "x", "run_id": "0" * 16,
            "pgid": bystander.pid, "pg_start": "1"}}}))  # same pid, wrong start tick: pid reuse
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertIsNone(bystander.poll(), "an unrelated process group was killed")

    def test_x3_a_stage_that_clears_its_environment_is_still_reaped_by_its_pgid(self):
        run = "env -i /bin/sh -c 'echo started >> out; sleep 2; echo done >> out'"
        d = self.task([{"id": "s", "run": run, "check": "grep -q done out"}])
        r = mx_start("run", d)
        self.assertTrue(wait_for(os.path.join(d, "out")))
        pgid = self.state(d)["stages"]["s"]["pgid"]
        os.kill(r.pid, signal.SIGKILL)
        r.wait()
        os.killpg(pgid, 0)  # the orphan lives, and no process of it carries the run id
        self.assertEqual(mx("run", d).returncode, 0)
        time.sleep(2.6)
        self.assertEqual(self.read(d, "out").split(), ["started", "started", "done"])

    def test_x4_attempts_counts_every_execution(self):
        d = self.task([{"id": "s", "run": "echo try >> c; test -f go", "check": "true"}])
        self.assertEqual(mx("run", d).returncode, 2)
        self.assertEqual(self.state(d)["stages"]["s"]["attempts"], 1)
        self.write(d, "go", "")
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.state(d)["stages"]["s"]["attempts"], 2)


class AtomicWriteCleanup(TaskCase):
    def test_a_failed_atomic_write_leaves_no_temp_file_and_keeps_the_old_content(self):
        d = self.task([{"id": "s", "run": "true", "check": "true"}])
        path = os.path.join(d, "task.json")
        core.atomic_write(path, {"v": 1})
        before = sorted(os.listdir(d))
        for exc in (OSError("disk full"), SystemExit(143)):
            with mock.patch.object(os, "replace", side_effect=exc):
                with self.assertRaises(type(exc)):
                    core.atomic_write(path, {"v": 2})
            self.assertEqual(sorted(os.listdir(d)), before)
            self.assertEqual(json.loads(self.read(d, "task.json")), {"v": 1})


class FailedApprovalIsNeverPersistedAsFailed(TaskCase):
    """N1 (MAJOR of audit #2): between `failed` being saved and `uncertain` being saved a signal or a kill
    made the next plain run repeat the irreversible command. It must be `uncertain` in the FIRST write."""

    def test_the_first_write_after_a_failed_approval_stage_already_says_uncertain(self):
        d = self.task([{"id": "send", "run": "echo pay >> pay.out; exit 1", "check": "true", "deps": ["art"],
                        "approval": "required"}], {"art": "v1\n"})
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        seen = []
        real_log = core.Task.log

        def spy(task, ev, **kw):
            if ev == "end":  # the stage has just ended; what is on disk right now is what a kill would leave
                seen.append(json.loads(self.read(d, "task.json"))["stages"]["send"]["status"])
            return real_log(task, ev, **kw)

        saved = {n: signal.getsignal(n) for n in (signal.SIGTERM, signal.SIGINT)}
        self.addCleanup(lambda: [signal.signal(n, h) for n, h in saved.items()])
        with mock.patch.object(core.Task, "log", spy), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(core.run(d), core.EX_UNCERTAIN)
        self.assertEqual(seen, ["uncertain"])
        self.assertEqual(mx("run", d).returncode, 5)
        self.assertEqual(self.lines(d, "pay.out"), 1)


class AtomicWriteSignalWindow(TaskCase):
    """N12a: a signal that lands right after mkstemp must not leave the temp file behind."""

    def test_a_signal_right_after_mkstemp_leaves_no_temp_file(self):
        d = self.task([{"id": "s", "run": "true", "check": "true"}])
        path = os.path.join(d, "task.json")
        core.atomic_write(path, {"v": 1})
        before = sorted(os.listdir(d))

        def stop(sig, frame):
            raise SystemExit(128 + sig)

        saved = signal.signal(signal.SIGTERM, stop)
        self.addCleanup(lambda: signal.signal(signal.SIGTERM, saved))
        real = core.tempfile.mkstemp

        def mkstemp_then_sigterm(*a, **kw):
            made = real(*a, **kw)
            os.kill(os.getpid(), signal.SIGTERM)  # arrives while the temp file exists and is not ours yet
            return made

        with mock.patch.object(core.tempfile, "mkstemp", mkstemp_then_sigterm):
            with self.assertRaises(SystemExit):
                core.atomic_write(path, {"v": 2})
        self.assertEqual(sorted(os.listdir(d)), before)
        self.assertEqual(json.loads(self.read(d, "task.json")), {"v": 1})


class LinkTextAndDisplay(TaskCase):
    """N2/N8: a link text that is not valid UTF-8 is no reason to crash, and approve shows what it binds."""

    def undecodable_link(self, where, target=b"\xff-target"):
        os.symlink(os.fsdecode(target), where)  # the bad byte sits in the first characters approve prints

    def test_a_symlink_dep_with_undecodable_text_is_hashed_not_a_traceback(self):
        d = self.task(send_spec("art"), {"art/own": "1\n"})
        self.undecodable_link(os.path.join(d, "art", "ln"))
        res = mx("approve", d, "send")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(mx("run", d).returncode, 0)

    def test_a_top_level_symlink_dep_with_undecodable_text_is_hashed_not_a_traceback(self):
        d = self.task(send_spec("ln"))
        self.undecodable_link(os.path.join(d, "ln"))
        os.makedirs(os.path.join(d, os.fsdecode(b"\xff-target")))
        res = mx("approve", d, "send")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_approve_shows_a_value_that_covers_the_content_behind_a_symlink(self):
        d = self.task(send_spec(), {"real.txt": "one\n"})
        os.symlink("real.txt", os.path.join(d, "link.txt"))
        first = mx("approve", d, "send").stdout.splitlines()[1]
        self.write(d, "real.txt", "two\n")
        second = mx("approve", d, "send").stdout.splitlines()[1]
        self.assertNotEqual(first, second, "the shown value did not change with the target's content")


class DeepAndWideDeps(TaskCase):
    SPEC = [{"id": "z", "run": "echo z >> r", "check": "test -s r", "deps": ["dep"]}]

    def test_n3_a_dep_nested_too_deeply_is_a_clean_refusal(self):
        d = self.task(self.SPEC)
        os.mkdir(os.path.join(d, "dep"))
        fd = os.open(os.path.join(d, "dep"), os.O_RDONLY | os.O_DIRECTORY)
        for _ in range(1500):  # one level at a time through a descriptor: makedirs itself would recurse
            os.mkdir("d", dir_fd=fd)
            nxt = os.open("d", os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = nxt
        os.close(fd)

        def remove_deep():  # shutil.rmtree recurses too: take the chain down from the bottom
            for depth in range(1500, 0, -1):
                os.rmdir(os.path.join(d, "dep", *["d"] * depth))
        self.addCleanup(remove_deep)  # runs before the temporary directory's own cleanup
        res = mx("run", d)
        self.assertEqual(res.returncode, 64, res.stderr[-300:])
        self.assertIn("nested too deeply", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_n4_links_fanning_out_to_the_same_directories_are_hashed_in_linear_time(self):
        d = self.task(self.SPEC, {"dep/leaf": "x\n"})
        previous = "dep"
        for level in range(12):  # each level holds 4 links to the level below: 4**12 paths, 13 directories
            here = os.path.join(d, f"lvl{level}")
            os.makedirs(here)
            for k in range(4):
                os.symlink(os.path.join(d, previous), os.path.join(here, f"l{k}"))
            previous = f"lvl{level}"
        os.symlink(os.path.join(d, previous), os.path.join(d, "dep", "top"))
        res = mx("run", d, timeout=15)
        self.assertEqual(res.returncode, 0, res.stderr[-300:])

    def test_y3_a_cycle_over_two_directories_is_detected(self):
        d = self.task(self.SPEC, {"dep/a/f": "1\n", "dep/b/g": "2\n"})
        os.symlink("../b", os.path.join(d, "dep", "a", "to_b"))
        os.symlink("../a", os.path.join(d, "dep", "b", "to_a"))
        self.assertEqual(mx("run", d, timeout=30).returncode, 0)
        self.assertEqual(mx("run", d, timeout=30).returncode, 0)
        self.assertEqual(self.lines(d, "r"), 1)
        self.write(d, "dep/b/g", "changed\n")
        self.assertEqual(mx("run", d, timeout=30).returncode, 0)
        self.assertEqual(self.lines(d, "r"), 2)

    def test_y7_a_file_name_that_is_not_valid_utf8_is_hashed(self):
        d = self.task(self.SPEC)
        os.makedirs(os.path.join(d, "dep"))
        with open(os.path.join(os.fsencode(d), b"dep", b"bad-\xff.txt"), "wb") as f:
            f.write(b"x")
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Traceback", res.stderr)


class RecordFilesWithForeignBytes(TaskCase):
    """N6b: approvals.jsonl / journal.jsonl are read as text; bytes that are not UTF-8 must not crash the runner."""

    def raw(self, d, name, data):
        with open(os.path.join(d, name), "wb") as f:
            f.write(data)

    def test_undecodable_bytes_in_approvals_are_not_an_approval_and_not_a_crash(self):
        d = self.task([{"id": "make", "run": "echo v > art", "check": "test -s art"},
                       {"id": "send", "run": "echo sent >> rs", "check": "test -s rs", "deps": ["art"],
                        "approval": "required"}])
        self.assertEqual(mx("run", d).returncode, 4)
        self.raw(d, "approvals.jsonl", b'{"t": 1, "stage": "se\xc3')
        res = mx("run", d)
        self.assertEqual(res.returncode, 4, res.stderr[-300:])
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "rs"), 1)

    def test_undecodable_bytes_in_the_journal_do_not_stop_the_completion_scan(self):
        d = self.task([{"id": "s", "run": "echo x >> c", "check": "test -s c"}])
        self.raw(d, "journal.jsonl", b"\xff\xfe not json\n")
        res = mx("run", d)
        self.assertEqual(res.returncode, 0, res.stderr[-300:])
        self.assertNotIn("Traceback", res.stderr)


class ApprovalIsConsumedByUse(TaskCase):
    """Audit #3 MAJOR: an approval authorises ONE execution. Changing the artifact away from the approved
    content and back used to bring the old approval back to life: the irreversible command ran a second
    time without a new decision."""

    def spec(self):
        return [{"id": "send", "run": "echo pay >> pay.out", "check": "test -s pay.out", "deps": ["art"],
                 "approval": "required"}]

    def test_changing_the_artifact_away_and_back_does_not_revive_the_old_approval(self):
        d = self.task(self.spec(), {"art": "A\n"})
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "pay.out"), 1)
        self.write(d, "art", "B\n")
        self.assertEqual(mx("run", d).returncode, 4)
        self.write(d, "art", "A\n")  # back to exactly what was approved and already released once
        res = mx("run", d)
        self.assertEqual(res.returncode, 4, res.stderr)
        self.assertEqual(self.lines(d, "pay.out"), 1, "the irreversible command ran again on an old approval")
        self.assertEqual(mx("approve", d, "send").returncode, 0)  # a NEW decision
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "pay.out"), 2)

    def test_an_upstream_stage_that_writes_a_then_b_then_a_does_not_revive_it_either(self):
        spec = [{"id": "gen", "run": "cat src > art", "check": "test -s art", "deps": ["src"]}] + self.spec()
        d = self.task(spec, {"src": "A\n"})
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)
        for content in ("B\n", "A\n"):
            self.write(d, "src", content)
            res = mx("run", d)
            self.assertEqual(res.returncode, 4, res.stderr)
        self.assertEqual(self.lines(d, "pay.out"), 1)

    def test_an_approval_that_was_never_used_still_releases_once_and_only_once(self):
        d = self.task(self.spec(), {"art": "A\n"})
        self.assertEqual(mx("approve", d, "send").returncode, 0)  # approved before the first run: allowed
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "pay.out"), 1)
        self.write(d, "art", "B\n")
        self.write(d, "art", "A\n")  # unchanged content: the stage is simply done, nothing runs
        self.assertEqual(mx("run", d).returncode, 0)
        self.assertEqual(self.lines(d, "pay.out"), 1)


class RetryIsTiedToTheFailedRun(TaskCase):
    """Audit #4 MAJOR: `resolve --retry` used to forget when the stage last started, which brought EVERY
    spent approval back, for other artifact contents too. A retry is a decision about the run that
    failed, not an amnesty: it covers that artifact once and nothing else."""

    def spec(self):  # fails for any content but A
        return [{"id": "send", "run": "cat art >> pay.out; grep -q A art", "check": "test -s pay.out",
                 "deps": ["art"], "approval": "required"}]

    def released_a_then_failed_on_b(self):
        d = self.task(self.spec(), {"art": "A\n"})
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)  # A released once
        self.write(d, "art", "B\n")
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 5)  # B failed: uncertain
        self.assertEqual(self.lines(d, "pay.out"), 2)
        return d

    def test_a_retry_does_not_bring_back_an_approval_of_other_content(self):
        d = self.released_a_then_failed_on_b()
        self.assertEqual(mx("resolve", d, "send", "--retry").returncode, 0)
        self.write(d, "art", "A\n")  # back to the content that was approved and already released
        res = mx("run", d)
        self.assertEqual(res.returncode, 4, res.stderr)
        self.assertEqual(self.lines(d, "pay.out"), 2, "A ran a second time on a spent approval")

    def test_a_retry_covers_the_artifact_that_failed_exactly_once(self):
        d = self.released_a_then_failed_on_b()
        self.assertEqual(mx("resolve", d, "send", "--retry").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 5)  # same B again: it ran (and failed) once more
        self.assertEqual(self.lines(d, "pay.out"), 3)
        self.assertEqual(mx("run", d).returncode, 5)  # and a plain run does not repeat it
        self.assertEqual(self.lines(d, "pay.out"), 3)

    def test_a_retry_that_succeeded_is_spent_and_does_not_cover_the_artifact_later(self):
        spec = [{"id": "send", "run": "cat art >> pay.out; test -f go", "check": "test -s pay.out",
                 "deps": ["art"], "approval": "required"}]
        d = self.task(spec, {"art": "A\n"})
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 5)  # no `go` file yet: fails, uncertain
        self.write(d, "go", "")
        self.assertEqual(mx("resolve", d, "send", "--retry").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 0)  # the retry ran and succeeded
        self.assertEqual(self.lines(d, "pay.out"), 2)
        self.write(d, "art", "C\n")
        self.assertEqual(mx("run", d).returncode, 4)  # other content: needs its own approval
        self.write(d, "art", "A\n")  # back to the content the retry covered
        res = mx("run", d)
        self.assertEqual(res.returncode, 4, res.stderr)
        self.assertEqual(self.lines(d, "pay.out"), 2, "a spent retry covered the same artifact a second time")

    def test_a_retry_does_not_cover_an_artifact_that_changed_in_the_meantime(self):
        d = self.released_a_then_failed_on_b()
        self.assertEqual(mx("resolve", d, "send", "--retry").returncode, 0)
        self.write(d, "art", "C\n")
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(self.lines(d, "pay.out"), 2)


class SpentApprovalsAreSaid(TaskCase):
    """Audit #4 MINORs: a spent approval is no longer silent, a damaged `started` fails closed, and the
    advice for a damaged task.json does not undo the spending."""

    def test_a_run_that_waits_because_the_approval_is_spent_says_so(self):
        d = self.task([{"id": "send", "run": "echo pay >> pay.out", "check": "test -s pay.out", "deps": ["art"],
                        "approval": "required"}], {"art": "A\n"})
        mx("run", d)
        mx("approve", d, "send")
        self.assertEqual(mx("run", d).returncode, 0)
        self.write(d, "art", "B\n")
        self.write(d, "art", "A\n")
        mx("run", d)  # nothing to do: A is done
        self.write(d, "art", "B\n")
        self.assertEqual(mx("run", d).returncode, 4)
        self.write(d, "art", "A\n")
        self.write(d, "task.json", json.dumps({**self.state(d), "stages": {"send": {
            **self.state(d)["stages"]["send"], "status": "pending"}}}))
        res = mx("run", d)
        self.assertEqual(res.returncode, 4, res.stderr)
        self.assertIn("already used", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

    def test_a_started_that_is_not_a_number_fails_closed_without_a_traceback(self):
        d = self.task([{"id": "send", "run": "echo pay >> pay.out", "check": "test -s pay.out", "deps": ["art"],
                        "approval": "required"}], {"art": "A\n"})
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        st = self.state(d)
        st["stages"]["send"]["started"] = "x"
        self.write(d, "task.json", json.dumps(st))
        res = mx("run", d)
        self.assertEqual(res.returncode, 4, res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(self.lines(d, "pay.out"), 0)

    def test_the_advice_for_a_damaged_task_json_names_the_approvals_too(self):
        d = self.task([{"id": "s", "run": "echo ok >> c", "check": "test -s c"}])
        self.write(d, "task.json", "{")
        res = mx("run", d)
        self.assertEqual(res.returncode, 64, res.stderr)
        self.assertIn("approvals.jsonl", res.stderr)


class ResolveIsInterruptible(TaskCase):
    """Audit #3 MINOR: `resolve` has no signal handler, so SIGTERM at the temp-file window killed it and left the temp file."""

    def test_sigterm_right_after_mkstemp_in_resolve_leaves_no_temp_file(self):
        d = self.task([{"id": "send", "run": "echo pay >> pay.out; exit 1", "check": "true", "deps": ["art"],
                        "approval": "required"}], {"art": "A\n"})
        self.assertEqual(mx("run", d).returncode, 4)
        self.assertEqual(mx("approve", d, "send").returncode, 0)
        self.assertEqual(mx("run", d).returncode, 5)  # uncertain
        before = sorted(os.listdir(d))
        code = (
            "import os, signal, sys\n"
            "sys.path.insert(0, %r)\n"
            "from makeextreme import core\n"
            "real = core.tempfile.mkstemp\n"
            "def hook(*a, **k):\n"
            "    made = real(*a, **k)\n"
            "    os.kill(os.getpid(), signal.SIGTERM)\n"
            "    return made\n"
            "core.tempfile.mkstemp = hook\n"
            "sys.exit(core.resolve(sys.argv[1], 'send', '--retry'))\n" % REPO)
        res = subprocess.run([sys.executable, "-c", code, d], capture_output=True, text=True)
        self.assertEqual(res.returncode, 143, res.stderr)
        self.assertEqual(sorted(os.listdir(d)), before, "a temp file was left behind")
        self.assertEqual(self.state(d)["stages"]["send"]["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()
