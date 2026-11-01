# makeextreme (登峰)

English · [中文](README.zh.md) · [Deutsch](README.de.md)

A small floor under agent pipelines whose stages are known in advance. It runs the stages of a task one after
another, decides "done" from the **artifact** (not from an exit code), continues after a crash from the last
green stage, and never releases an irreversible stage on its own.

## Status

- Version 1.0.0, one author, Linux only, Python standard library only; tested on Python 3.11 and 3.14.
- The code was written by an AI agent (Claude Sonnet 5.5 running in Hermes) at the owner's direction.
- **Published before its final independent audit.** That was the owner's one-time exception on 2026-11-01. The
  M1 core had five milestone audits, each by a fresh Sonnet 5.5 session with read-only access to the repository
  (the same model family as the author, not a different model); the fifth passed (0 blocker, 0 major, 1 minor,
  3 plan items). A deeper audit is still to come.
- Not compared with any other tool, so no ranking claim is made.

## What it does

`python -m makeextreme run <task_dir>` reads `<task_dir>/stages.json` and runs the stages in order:

```json
[{"id": "ocr", "run": "sh bin/ocr.sh",
  "check": "test $(ls ocr | wc -l) -eq $(ls frames | wc -l)", "deps": ["frames", "bin/ocr.sh"]}]
```

- A stage is done only when `run` exits 0 **and** `check` exits 0 against the real output.
- A finished stage is skipped on the next run unless its command or the content of a declared dep changed.
- A stage marked `"approval": "required"` (it must declare `deps`) waits for `python -m makeextreme approve <task_dir> <stage>`. The approval is bound to the stage and to the hash of its artifact, and one approval
  releases one execution. If such a stage crashes or fails it becomes *uncertain* and is never repeated
  automatically; look at the outside world, then `python -m makeextreme resolve <task_dir> <stage> --done` or
  `--retry`.

Exit codes of `run`: `0` complete, `2` a stage failed, `3` locked by a live runner, `4` waiting for approval,
`5` an uncertain stage needs `resolve`, `6` refused (a secret-shaped value in the record), `64` invalid or
missing `stages.json` or task directory.

## What was measured

- 96 tests (`python -m unittest discover -s tests -p 'test_*.py'`) and 77 mutants
  (`python tests/mutants.py all`, about 3 minutes): every mutant makes at least one test fail.
- **AC10, video pipeline** (`examples/video_pipeline/`): download, audio, transcript, frames, OCR, assembly and
  delivery as stages. On a 38-second video, `kill -9` of the runner during OCR (after 1, 4, 9 and 17 frames, and
  once with a real download from the URL) and a second `run` gave all 7 artifacts byte-identical to an
  uninterrupted run, no finished stage ran twice, and no orphan process stayed. Three deliberately broken runner
  variants make that check fail (`python examples/video_pipeline/ac10_mutants.py`).
- Whisper is not bit-deterministic on the machine used: the same clip gave two different transcripts in about
  1 run out of 6 to 10. The example therefore caches a transcript by the hash of its audio, and AC10 shows that
  runs resume correctly, not that transcription is deterministic.
- **AC9, Hermes host** (`examples/hermes_host/ac9.py`): a stage runs `hermes chat --oneshot` under `env -i`,
  the answer is captured and checked; a wrong model name fails the stage, and a stage without `env -i` fails the
  canary check.
- **Scheduling**: `examples/cron_tick.sh <task_dir>` starts one worker per cron tick and reports; makeextreme has
  no watchdog on purpose.

## Known limits

- `approve` cannot tell who typed it. It stops an accidental release, not an agent that holds your shell.
- A stage that calls `setsid` and clears its environment cannot be found and killed after a crash; a child that
  ignores SIGTERM lives until the next `run`.
- State (`task.json`) and journal (`journal.jsonl`) are two writes; after a crash between them the journal can be
  one entry behind. `task.json` is authoritative.
- The design record, with every limit found by the audits, is `ARCHITECTURE.md` (in Chinese).

## License

Apache-2.0, see `LICENSE`. `makeextreme/secret_scan.py` is copied from
[Longhaul](https://github.com/dacheng-lu/longhaul) (Apache-2.0); other projects only gave ideas (`NOTICE.md`,
`docs/SOURCES.md`). Another crash-resumable pipeline runner seen, not evaluated:
[areeves/revenant](https://github.com/areeves/revenant).
