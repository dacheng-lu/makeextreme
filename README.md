<p align="center">
  <img src="assets/logo.jpg" alt="Makeextreme · 登峰 logo" width="640">
</p>

# 登峰 · Makeextreme

**Reach the peak. Resume the climb.**  
**登峰不止，断点可续。**  
**Den Gipfel erreichen. Den Aufstieg fortsetzen.**

**Resume after a crash · Done means the artifact passes · Irreversible steps wait for approval**  
**崩溃可续 · 以产物验收 · 不可逆须批准**  
**Nach dem Absturz fortsetzen · Fertig heißt: Artefakt geprüft · Unumkehrbares wartet auf Freigabe**

[English](#english) · [简体中文](#zh-cn) · [Deutsch](#deutsch)

Version: **1.1.0** · [Design record / 设计记录 / Entwurfsprotokoll](ARCHITECTURE.md) · [Apache-2.0](LICENSE)

## English

makeextreme is a small floor under agent pipelines whose stages are known in advance. It runs the stages of a task one after another, decides "done" from the **artifact** instead of an exit code, continues after a crash from the last green stage and never releases an irreversible stage on its own. It is a runner of about 600 lines in the Python standard library, not a framework, a scheduler or an agent.

### Status

- The code was written by an AI agent (Claude Sonnet 5.5 running in Hermes) at the owner's direction.
- **Published before its final independent audit.** That was the owner's one-time exception on 2026-11-01. The M1 core had five milestone audits, each by a fresh Sonnet 5.5 session with read-only access to the repository (the same model family as the author, not a different model); the fifth passed (0 blocker, 0 major, 1 minor, 3 plan items). A deeper audit is still to come.
- Version 1.1.0, one author, Linux only, Python standard library only; tested on Python 3.11 and 3.14.
- Not compared with any other tool, so no ranking claim is made.

### When to use it

Use it for a pipeline you run more than once, or one long enough to be killed half-way (video briefing, report build, batch OCR), when the success of each stage can be decided by a command on the real output, the budget survives a rerun of the crashed stage and the stage runs unattended. Do not use it for exploratory work whose stages are unknown; [Longhaul](https://github.com/dacheng-lu/longhaul) coordinates that kind of work and makeextreme does not.

### What version 1 includes

`python -m makeextreme run <task_dir>` reads `<task_dir>/stages.json` and runs the stages in order:

```json
[{"id": "ocr", "run": "sh bin/ocr.sh",
  "check": "test $(ls ocr | wc -l) -eq $(ls frames | wc -l)", "deps": ["frames", "bin/ocr.sh"], "outputs": ["ocr"]}]
```

- A stage is done only when `run` exits 0 **and** `check` exits 0 against the real output.
- A finished stage is skipped on the next run unless its command or the content of a declared dep changed.
- A stage may declare `"outputs"` (1.1.0): their content is recorded after the run and checked before every skip. If an output was deleted or edited, an ordinary stage is run again and an approval stage becomes *uncertain* and is not repeated; a stage that did not produce a declared output is not done. A path cannot be both a `dep` and an `output` of the same stage.
- A stage marked `"approval": "required"` (it must declare `deps`) waits for `python -m makeextreme approve <task_dir> <stage>`. The approval is bound to the stage and to the hash of its artifact, and one approval releases one execution. If such a stage crashes or fails it becomes *uncertain* and is never repeated automatically; look at the outside world, then `python -m makeextreme resolve <task_dir> <stage> --done` or `--retry`.
- Exit codes of `run`: `0` complete, `2` a stage failed, `3` locked by a live runner, `4` waiting for approval, `5` an uncertain stage needs `resolve`, `6` refused (a secret-shaped value in the record), `64` invalid or missing `stages.json` or task directory.

### Get started

```bash
git clone https://github.com/dacheng-lu/makeextreme
cd makeextreme
mkdir demo
echo '[{"id": "hello", "run": "echo hi > out.txt", "check": "test -s out.txt"}]' > demo/stages.json
python3 -m makeextreme run demo     # exit 0; run it again and the stage is skipped
```

The package is not installed; run it from the repository root. A larger task is in `examples/video_pipeline/` (`new_task.py` writes a ready task directory). To run a task from cron, `examples/cron_tick.sh <task_dir>` starts one worker per tick and reports; makeextreme has no watchdog on purpose.

### What was measured

- 121 tests (`python -m unittest discover -s tests -p 'test_*.py'`) and 94 mutants (`python tests/mutants.py all`, about 3 minutes): every mutant makes at least one test fail.
- **AC10, video pipeline** (`examples/video_pipeline/`): download, audio, transcript, frames, OCR, assembly and delivery as stages. On a 38-second video, `kill -9` of the runner during OCR (after 1, 4, 9 and 17 frames, and once with a real download from the URL) and a second `run` gave all 7 artifacts byte-identical to an uninterrupted run, no finished stage ran twice, and no orphan process stayed. Four deliberately broken runner variants make that check fail (`python examples/video_pipeline/ac10_mutants.py`). On a copy of the finished task, deleting `ocr/`, editing `asr.txt` and deleting the approved stage's output each made the next `run` redo only the damaged stage (the approved stage stopped with exit 5 and was made again only after `resolve --retry`), with the original bytes back.
- Whisper is not bit-deterministic on the machine used: the same clip gave two different transcripts in about 1 run out of 6 to 10. The example therefore caches a transcript by the hash of its audio, and AC10 shows that runs resume correctly, not that transcription is deterministic.
- **AC9, Hermes host** (`examples/hermes_host/ac9.py`): a stage runs `hermes chat --oneshot` under `env -i`, the answer is captured and checked; a wrong model name fails the stage, and a stage without `env -i` fails the canary check.

### Boundaries

- `approve` cannot tell who typed it. It stops an accidental release, not an agent that holds your shell.
- A stage that calls `setsid` and clears its environment cannot be found and killed after a crash; a child that ignores SIGTERM lives until the next `run`.
- State (`task.json`) and journal (`journal.jsonl`) are two writes; after a crash between them the journal can be one entry behind. `task.json` is authoritative.
- Only declared `outputs` are verified before a skip. A stage without `outputs` is skipped without running its `check` again: if its output is deleted or edited afterwards, nothing notices unless a later stage lists that output in `deps` (measured on 1.0.0: delete the last stage's output and `run` exits 0 with a `skip` and no file). Outputs are hashed on every run, also when the stage is skipped, so a very large output costs time.
- Passing `check` proves what `check` measures. A check that is too weak makes a wrong result "done".
- The design record, with every limit found by the audits, is `ARCHITECTURE.md` (in Chinese).

### Contributing

Useful contributions include a reproducible crash-and-resume scenario, a stage your pipeline needs and the runner cannot express, and a check that catches a false "done". Include the expected behavior, the observed behavior and the commands. Run the tests before and after; `tests/test_readme.py` keeps this page and the repository in step.

[Files and design references](#files-and-design-references) · [Back to top](#登峰--makeextreme)

<a name="zh-cn"></a>

## 简体中文

makeextreme 是给「阶段已知」的 agent 流水线垫的一层地板。它按顺序执行任务的各个阶段，用**产物**（而不是退出码）判定「完成」，崩溃后从最后一个通过的阶段继续，并且不会自行放行不可逆的阶段。它是一个约 600 行、只用 Python 标准库的运行器，不是框架、调度器或 agent。

### 状态

- 代码由 AI agent（运行在 Hermes 里的 Claude Sonnet 5.5）按所有者的指示编写。
- **在最终独立审计之前就公开了。** 这是项目所有者在 2026-11-01 一次性的破例。M1 核心做过五轮里程碑审计，每轮都是一个全新的 Sonnet 5.5 会话、对仓库只读（与作者同一个模型家族，不是另一种模型）；第五轮通过（0 个 BLOCKER、0 个 MAJOR、1 个 MINOR、3 个 PLAN）。更深入的审计之后再做。
- 版本 1.1.0，单人开发，仅限 Linux，只用 Python 标准库；在 Python 3.11 和 3.14 上测过。
- 没有和任何其他工具做过对比，因此不作任何排名性的说法。

### 适用场景

适合会重复运行、或长到可能被中途杀掉的流水线（视频简报、报告构建、批量 OCR），并且满足：每个阶段的成败都能用一条命令对真实产物判定，预算在重跑崩溃的阶段后依然够用，阶段能无人值守运行。不适合阶段未知的探索性工作；那类工作由 [Longhaul](https://github.com/dacheng-lu/longhaul) 来协调，makeextreme 不做。

### 第一版包含什么

`python -m makeextreme run <task_dir>` 读取 `<task_dir>/stages.json`，按顺序执行各阶段：

```json
[{"id": "ocr", "run": "sh bin/ocr.sh",
  "check": "test $(ls ocr | wc -l) -eq $(ls frames | wc -l)", "deps": ["frames", "bin/ocr.sh"], "outputs": ["ocr"]}]
```

- 只有 `run` 退出码为 0 **并且** `check` 对真实产物退出码也为 0，阶段才算完成。
- 已完成的阶段下次运行时会被跳过，除非它的命令或所声明依赖（`deps`）的内容变了。
- 阶段可以声明 `"outputs"`（1.1.0）：运行后记录它们的内容，每次跳过之前重新校验。产物被删或被改时，普通阶段会重跑，`approval` 阶段变成「不确定」且不重复；没有产出所声明产物的阶段不算完成。同一个路径不能同时是同一阶段的 `dep` 和 `output`。
- 标了 `"approval": "required"` 的阶段（必须声明 `deps`）要等 `python -m makeextreme approve <task_dir> <stage>`。批准绑定阶段和产物的哈希，一次批准只放行一次执行。这样的阶段如果崩溃或失败，会变成「不确定」，绝不自动重跑；先去外部世界核实，再用 `python -m makeextreme resolve <task_dir> <stage> --done` 或 `--retry` 决定。
- `run` 的退出码：`0` 完成，`2` 某阶段失败，`3` 被存活的运行器锁住，`4` 等待批准，`5` 有不确定阶段需要 `resolve`，`6` 拒绝完成（记录里有形似密钥的值），`64` `stages.json` 或任务目录无效或缺失。

### 开始使用

```bash
git clone https://github.com/dacheng-lu/makeextreme
cd makeextreme
mkdir demo
echo '[{"id": "hello", "run": "echo hi > out.txt", "check": "test -s out.txt"}]' > demo/stages.json
python3 -m makeextreme run demo     # 退出码 0；再运行一次，该阶段会被跳过
```

包没有安装，请在仓库根目录运行。更大的任务示例在 `examples/video_pipeline/`（`new_task.py` 会写出一个现成的任务目录）。要从 cron 运行任务，`examples/cron_tick.sh <task_dir>` 每个节拍启动一个 worker 并报告；makeextreme 刻意不带看门狗。

### 实测了什么

- 121 个测试（`python -m unittest discover -s tests -p 'test_*.py'`）和 94 个变异体（`python tests/mutants.py all`，约 3 分钟）：每个变异体都会让至少一个测试失败。
- **AC10，视频流水线**（`examples/video_pipeline/`）：下载、音频、转写、抽帧、OCR、拼装、交付各为一个阶段。在一段 38 秒的视频上，OCR 期间对运行器 `kill -9`（分别在第 1、4、9、17 帧之后，另有一次用真实 URL 下载），再运行一次后，7 个产物与不中断的一次逐字节相同，没有已完成的阶段被重跑，也没有残留的孤儿进程。四个故意弄坏的运行器变体会让这项检查失败（`python examples/video_pipeline/ac10_mutants.py`）。在已完成任务的副本上，删掉 `ocr/`、改动 `asr.txt`、删掉已批准阶段的产物，下一次 `run` 都只重做被破坏的那个阶段（已批准的阶段以退出码 5 停下，`resolve --retry` 之后才重做），原来的字节都回来了。
- 在所用机器上 Whisper 不是逐位确定的：同一段音频约每 6 到 10 次会出现一次不同的转写。因此示例按音频哈希缓存转写，AC10 证明的是「恢复正确」，不是「转写确定」。
- **AC9，Hermes 宿主**（`examples/hermes_host/ac9.py`）：一个阶段在 `env -i` 下运行 `hermes chat --oneshot`，答案被捕获并检查；模型名写错会让阶段失败，没有 `env -i` 的阶段会过不了金丝雀检查。

### 能力边界

- `approve` 分辨不出是谁敲的。它能防止意外放行，防不住握着你 shell 的 agent。
- 调用了 `setsid` 并清空环境变量的阶段，崩溃后找不到也杀不掉；忽略 SIGTERM 的子进程会活到下一次 `run`。
- 状态（`task.json`）和日志（`journal.jsonl`）是两次写入；两次之间崩溃，日志可能少一条。以 `task.json` 为准。
- 只有声明了的 `outputs` 会在跳过之前被校验。没声明 `outputs` 的阶段被跳过时不会再跑 `check`：事后产物被删或被改，除非后面某个阶段把它列进了 `deps`，否则没人会发现（在 1.0.0 上实测：删掉最后一个阶段的产物，`run` 退出码 0，日志写 `skip`，文件不在）。产物每次运行都要哈希，跳过时也一样，所以特别大的产物会花时间。
- `check` 通过只证明 `check` 测量的东西。太弱的检查会让错误的结果也算「完成」。
- 设计记录和审计发现的全部限制见 `ARCHITECTURE.md`（中文）。

### 参与改进

有价值的贡献包括：可复现的崩溃与续跑场景、你的流水线需要而运行器表达不了的阶段、能抓住虚假「完成」的检查。请写明预期行为、实际行为和命令。改动前后都请跑测试；`tests/test_readme.py` 让本页与仓库保持一致。

[文件与设计参考](#files-and-design-references) · [回到顶部](#登峰--makeextreme)

## Deutsch

makeextreme ist ein kleiner Unterbau für Agenten-Pipelines, deren Stufen im Voraus bekannt sind. Er führt die Stufen einer Aufgabe nacheinander aus, entscheidet „fertig“ am **Artefakt** statt am Exit-Code, setzt nach einem Absturz bei der letzten grünen Stufe fort und gibt eine nicht umkehrbare Stufe nie von selbst frei. Er ist ein Runner von rund 600 Zeilen in der Python-Standardbibliothek, kein Framework, kein Scheduler und kein Agent.

### Stand

- Der Code wurde von einem KI-Agenten (Claude Sonnet 5.5 in Hermes) im Auftrag des Eigentümers geschrieben.
- **Veröffentlicht vor dem unabhängigen Abschluss-Audit.** Das war eine einmalige Ausnahme des Eigentümers am 2026-11-01. Der M1-Kern hatte fünf Meilenstein-Audits, jeweils durch eine frische Sonnet-5.5-Sitzung mit Lesezugriff auf das Repository (dieselbe Modellfamilie wie der Autor, kein anderes Modell); das fünfte bestand (0 Blocker, 0 Major, 1 Minor, 3 Plan-Punkte). Ein tieferes Audit folgt noch.
- Version 1.1.0, ein Autor, nur Linux, nur die Python-Standardbibliothek; getestet mit Python 3.11 und 3.14.
- Mit keinem anderen Werkzeug verglichen, daher keine Rangaussage.

### Wann ist makeextreme sinnvoll?

Für eine Pipeline, die mehrfach läuft oder so lang ist, dass sie unterwegs beendet werden kann (Video-Briefing, Berichtsaufbau, Stapel-OCR), wenn sich der Erfolg jeder Stufe mit einem Befehl am echten Ergebnis entscheiden lässt, das Budget einen erneuten Lauf der abgestürzten Stufe übersteht und die Stufe unbeaufsichtigt läuft. Nicht für Erkundungsarbeit mit unbekannten Stufen; die koordiniert [Longhaul](https://github.com/dacheng-lu/longhaul), makeextreme nicht.

### Funktionsumfang von Version 1

`python -m makeextreme run <task_dir>` liest `<task_dir>/stages.json` und führt die Stufen der Reihe nach aus:

```json
[{"id": "ocr", "run": "sh bin/ocr.sh",
  "check": "test $(ls ocr | wc -l) -eq $(ls frames | wc -l)", "deps": ["frames", "bin/ocr.sh"], "outputs": ["ocr"]}]
```

- Eine Stufe ist nur fertig, wenn `run` mit 0 endet **und** `check` am echten Ergebnis ebenfalls mit 0 endet.
- Eine fertige Stufe wird beim nächsten Lauf übersprungen, außer ihr Befehl oder der Inhalt einer deklarierten Abhängigkeit (`deps`) hat sich geändert.
- Eine Stufe kann `"outputs"` angeben (1.1.0): ihr Inhalt wird nach dem Lauf festgehalten und vor jedem Überspringen geprüft. Wurde ein Ergebnis gelöscht oder geändert, läuft eine normale Stufe erneut und eine Freigabe-Stufe wird *unsicher* und nicht wiederholt; eine Stufe, die ein angegebenes Ergebnis nicht erzeugt hat, ist nicht fertig. Ein Pfad kann nicht zugleich `dep` und `output` derselben Stufe sein.
- Eine Stufe mit `"approval": "required"` (sie muss `deps` angeben) wartet auf `python -m makeextreme approve <task_dir> <stage>`. Die Freigabe ist an die Stufe und den Hash ihres Artefakts gebunden, und eine Freigabe erlaubt genau eine Ausführung. Stürzt so eine Stufe ab oder schlägt sie fehl, wird sie *unsicher* und nie automatisch wiederholt; erst die Außenwelt prüfen, dann `python -m makeextreme resolve <task_dir> <stage> --done` oder `--retry`.
- Exit-Codes von `run`: `0` fertig, `2` eine Stufe ist fehlgeschlagen, `3` von einem lebenden Runner gesperrt, `4` wartet auf Freigabe, `5` eine unsichere Stufe braucht `resolve`, `6` abgelehnt (ein schlüsselähnlicher Wert im Protokoll), `64` ungültige oder fehlende `stages.json` oder Aufgabenverzeichnis.

### Einstieg

```bash
git clone https://github.com/dacheng-lu/makeextreme
cd makeextreme
mkdir demo
echo '[{"id": "hello", "run": "echo hi > out.txt", "check": "test -s out.txt"}]' > demo/stages.json
python3 -m makeextreme run demo     # Exit-Code 0; ein zweiter Lauf überspringt die Stufe
```

Das Paket wird nicht installiert; im Repository-Hauptverzeichnis ausführen. Eine größere Aufgabe liegt in `examples/video_pipeline/` (`new_task.py` schreibt ein fertiges Aufgabenverzeichnis). Für den Lauf aus Cron startet `examples/cron_tick.sh <task_dir>` pro Takt einen Worker und berichtet; makeextreme hat absichtlich keinen Watchdog.

### Was gemessen wurde

- 121 Tests (`python -m unittest discover -s tests -p 'test_*.py'`) und 94 Mutanten (`python tests/mutants.py all`, etwa 3 Minuten): jeder Mutant lässt mindestens einen Test fehlschlagen.
- **AC10, Video-Pipeline** (`examples/video_pipeline/`): Download, Audio, Transkript, Frames, OCR, Zusammenbau und Auslieferung als Stufen. Bei einem 38-Sekunden-Video führte `kill -9` auf den Runner während der OCR (nach 1, 4, 9 und 17 Frames sowie einmal mit echtem Download von der URL) und ein zweiter `run` dazu, dass alle 7 Artefakte byteidentisch zu einem ununterbrochenen Lauf waren, keine fertige Stufe zweimal lief und kein Waisenprozess zurückblieb. Vier absichtlich kaputte Runner-Varianten lassen diese Prüfung fehlschlagen (`python examples/video_pipeline/ac10_mutants.py`). An einer Kopie der fertigen Aufgabe führten das Löschen von `ocr/`, das Ändern von `asr.txt` und das Löschen des Ergebnisses der freigegebenen Stufe jeweils dazu, dass der nächste `run` nur die beschädigte Stufe neu machte (die freigegebene Stufe hielt mit Exit-Code 5 an und wurde erst nach `resolve --retry` neu gemacht), mit den ursprünglichen Bytes.
- Whisper ist auf der verwendeten Maschine nicht bitgenau deterministisch: derselbe Clip ergab etwa bei jedem 6. bis 10. Lauf ein anderes Transkript. Das Beispiel legt Transkripte deshalb nach dem Hash ihres Audios ab, und AC10 zeigt, dass die Wiederaufnahme stimmt, nicht dass die Transkription deterministisch ist.
- **AC9, Hermes-Host** (`examples/hermes_host/ac9.py`): eine Stufe führt `hermes chat --oneshot` unter `env -i` aus, die Antwort wird erfasst und geprüft; ein falscher Modellname lässt die Stufe fehlschlagen, und eine Stufe ohne `env -i` besteht die Canary-Prüfung nicht.

### Grenzen

- `approve` kann nicht erkennen, wer es getippt hat. Es verhindert eine versehentliche Freigabe, keinen Agenten, der deine Shell hält.
- Eine Stufe, die `setsid` aufruft und ihre Umgebung leert, wird nach einem Absturz weder gefunden noch beendet; ein Kindprozess, der SIGTERM ignoriert, lebt bis zum nächsten `run`.
- Zustand (`task.json`) und Journal (`journal.jsonl`) sind zwei Schreibvorgänge; nach einem Absturz dazwischen kann das Journal einen Eintrag zurückliegen. Maßgeblich ist `task.json`.
- Nur angegebene `outputs` werden vor dem Überspringen geprüft. Eine Stufe ohne `outputs` wird übersprungen, ohne dass ihr `check` erneut läuft: Wird ihr Ergebnis danach gelöscht oder geändert, merkt das niemand, solange nicht eine spätere Stufe es in `deps` führt (auf 1.0.0 gemessen: das Ergebnis der letzten Stufe löschen, `run` endet mit 0, das Journal schreibt `skip`, die Datei fehlt). Ergebnisse werden bei jedem Lauf gehasht, auch beim Überspringen; sehr große Ergebnisse kosten also Zeit.
- Ein bestandenes `check` beweist nur, was `check` misst. Eine zu schwache Prüfung lässt auch ein falsches Ergebnis „fertig“ sein.
- Das Entwurfsprotokoll mit allen von den Audits gefundenen Grenzen ist `ARCHITECTURE.md` (auf Chinesisch).

### Mitwirken

Hilfreich sind ein reproduzierbares Absturz-und-Fortsetzen-Szenario, eine Stufe, die deine Pipeline braucht und der Runner nicht ausdrücken kann, und eine Prüfung, die ein falsches „fertig“ abfängt. Bitte erwartetes Verhalten, beobachtetes Verhalten und die Befehle angeben. Die Tests vorher und nachher ausführen; `tests/test_readme.py` hält diese Seite und das Repository im Gleichklang.

[Dateien und Entwurfsquellen](#files-and-design-references) · [Zurück zum Anfang](#登峰--makeextreme)

## Files and design references

The design record is in Chinese. 设计记录使用中文。 Das Entwurfsprotokoll ist auf Chinesisch.

| File / 文件 / Datei | Purpose / 用途 / Zweck |
| --- | --- |
| [makeextreme/core.py](makeextreme/core.py) | Runner · 运行器 · Runner |
| [makeextreme/secret_scan.py](makeextreme/secret_scan.py) | Credential detector (from Longhaul) · 凭证检测器（取自 Longhaul）· Zugangsdaten-Erkennung (aus Longhaul) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Design record and audit findings · 设计记录与审计发现 · Entwurfsprotokoll und Audit-Funde |
| [NOTICE.md](NOTICE.md) · [docs/SOURCES.md](docs/SOURCES.md) | Sources and licenses · 来源与许可 · Quellen und Lizenzen |
| [examples/video_pipeline/](examples/video_pipeline/) | AC10 video pipeline · AC10 视频流水线 · AC10-Video-Pipeline |
| [examples/hermes_host/ac9.py](examples/hermes_host/ac9.py) | AC9 Hermes host · AC9 Hermes 宿主 · AC9-Hermes-Host |
| [examples/cron_tick.sh](examples/cron_tick.sh) | One cron tick · 一个 cron 节拍 · Ein Cron-Takt |
| [tests/](tests/) | Tests and mutants · 测试与变异体 · Tests und Mutanten |
| [assets/logo.jpg](assets/logo.jpg) | Logo · 标志 · Logo |
| [assets/social-preview.png](assets/social-preview.png) | Social preview, 1280×640 · 社交预览图 · Social-Preview |

Design inspirations, not bundled dependencies or claims of affiliation:  
以下项目为设计参考，不是内置依赖，也不代表官方关联：  
Entwurfsquellen, keine mitgelieferten Abhängigkeiten oder behaupteten Partnerschaften:

- [Longhaul](https://github.com/dacheng-lu/longhaul): `secret_scan.py` is copied from it (Apache-2.0) / 拷贝了 `secret_scan.py` / `secret_scan.py` ist von dort kopiert.
- [Superpowers](https://github.com/obra/superpowers), [ECC](https://github.com/affaan-m/ECC), [ponytail](https://github.com/DietrichGebert/ponytail): ideas only (MIT) / 只借想法 / nur Ideen.
- [kiso](https://github.com/vincemakes/kiso): idea only (MIT), not run / 只借想法（MIT），没有运行 / nur eine Idee (MIT), nicht ausgeführt.
- [DVC](https://github.com/treeverse/dvc) (Apache-2.0), [resilient-agent-toolkit-v2](https://github.com/chenhz01/resilient-agent-toolkit-v2) (MIT): run as test subjects before building; nothing copied, DVC gave the idea of a stage fingerprint / 建造前被当作被测对象试跑，没有拷贝，DVC 给了「阶段指纹」的想法 / vor dem Bau als Testobjekte ausgeführt, nichts kopiert, DVC gab die Idee des Stufen-Fingerabdrucks.
- [areeves/revenant](https://github.com/areeves/revenant): another crash-resumable pipeline runner, seen and not evaluated / 另一个可恢复流水线运行器，只看到，未评测 / ein weiterer wiederaufnehmbarer Pipeline-Runner, gesehen und nicht bewertet.

License / 许可证 / Lizenz: [Apache License 2.0](LICENSE).
