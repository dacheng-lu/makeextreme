# makeextreme（登峰）

[English](README.md) · 中文 · [Deutsch](README.de.md)

给「阶段已知」的 agent 流水线垫的一层地板。它按顺序执行任务的各个阶段，用**产物**（而不是退出码）判定「完成」，
崩溃后从最后一个通过的阶段继续，并且不会自行放行不可逆的阶段。

## 状态

- 版本 1.0.0，单人开发，仅限 Linux，只用 Python 标准库；在 Python 3.11 和 3.14 上测过。
- 代码由 AI agent（运行在 Hermes 里的 Claude Sonnet 5.5）按所有者的指示编写。
- **在最终独立审计之前就公开了。** 这是项目所有者在 2026-11-01 一次性的破例。M1 核心做过五轮里程碑审计，每轮都是一个
  全新的 Sonnet 5.5 会话、对仓库只读（与作者同一个模型家族，不是另一种模型）；第五轮通过（0 个 BLOCKER、0 个 MAJOR、
  1 个 MINOR、3 个 PLAN）。更深入的审计之后再做。
- 没有和任何其他工具做过对比，因此不作任何排名性的说法。

## 它做什么

`python -m makeextreme run <task_dir>` 读取 `<task_dir>/stages.json`，按顺序执行各阶段：

```json
[{"id": "ocr", "run": "sh bin/ocr.sh",
  "check": "test $(ls ocr | wc -l) -eq $(ls frames | wc -l)", "deps": ["frames", "bin/ocr.sh"]}]
```

- 只有 `run` 退出码为 0 **并且** `check` 对真实产物退出码也为 0，阶段才算完成。
- 已完成的阶段下次运行时会被跳过，除非它的命令或所声明依赖（`deps`）的内容变了。
- 标了 `"approval": "required"` 的阶段（必须声明 `deps`）要等 `python -m makeextreme approve <task_dir> <stage>`。
  批准绑定阶段和产物的哈希，一次批准只放行一次执行。这样的阶段如果崩溃或失败，会变成「不确定」，绝不自动重跑；
  先去外部世界核实，再用 `python -m makeextreme resolve <task_dir> <stage> --done` 或 `--retry` 决定。

`run` 的退出码：`0` 完成，`2` 某阶段失败，`3` 被存活的运行器锁住，`4` 等待批准，`5` 有不确定阶段需要 `resolve`，
`6` 拒绝完成（记录里有形似密钥的值），`64` `stages.json` 或任务目录无效或缺失。

## 实测了什么

- 96 个测试（`python -m unittest discover -s tests -p 'test_*.py'`）和 77 个变异体
  （`python tests/mutants.py all`，约 3 分钟）：每个变异体都会让至少一个测试失败。
- **AC10，视频流水线**（`examples/video_pipeline/`）：下载、音频、转写、抽帧、OCR、拼装、交付各为一个阶段。
  在一段 38 秒的视频上，OCR 期间对运行器 `kill -9`（分别在第 1、4、9、17 帧之后，另有一次用真实 URL 下载），
  再运行一次后，7 个产物与不中断的一次逐字节相同，没有已完成的阶段被重跑，也没有残留的孤儿进程。
  三个故意弄坏的运行器变体会让这项检查失败（`python examples/video_pipeline/ac10_mutants.py`）。
- 在所用机器上 Whisper 不是逐位确定的：同一段音频约每 6 到 10 次会出现一次不同的转写。因此示例按音频哈希缓存转写，
  AC10 证明的是「恢复正确」，不是「转写确定」。
- **AC9，Hermes 宿主**（`examples/hermes_host/ac9.py`）：一个阶段在 `env -i` 下运行 `hermes chat --oneshot`，
  答案被捕获并检查；模型名写错会让阶段失败，没有 `env -i` 的阶段会过不了金丝雀检查。
- **调度**：`examples/cron_tick.sh <task_dir>` 每个 cron 节拍启动一个 worker 并报告；makeextreme 刻意不带看门狗。

## 已知限制

- `approve` 分辨不出是谁敲的。它能防止意外放行，防不住握着你 shell 的 agent。
- 调用了 `setsid` 并清空环境变量的阶段，崩溃后找不到也杀不掉；忽略 SIGTERM 的子进程会活到下一次 `run`。
- 状态（`task.json`）和日志（`journal.jsonl`）是两次写入；两次之间崩溃，日志可能少一条。以 `task.json` 为准。
- 设计记录和审计发现的全部限制见 `ARCHITECTURE.md`。

## 许可

Apache-2.0，见 `LICENSE`。`makeextreme/secret_scan.py` 拷贝自 [Longhaul](https://github.com/dacheng-lu/longhaul)
（Apache-2.0）；其他项目只提供了想法（`NOTICE.md`、`docs/SOURCES.md`）。另见、未评测的同类可恢复流水线运行器：
[areeves/revenant](https://github.com/areeves/revenant)。
