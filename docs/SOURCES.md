# 登峰 · Makeextreme — 交付内容的来源与取舍（2026-10-31）

用户指令（D5=A 之后）：交付内容要结合 **Superpowers、ECC、Ponytail、本地 Hermes 里实用且适用的 skill**。
本页是"哪一块从哪来、为什么取、为什么不取"的台账。原则沿用 pstack 那次的结论：**学内容，不学结构**；以及 Ponytail 的梯子：**仓库里已有的先复用，不重写**。

## 0. 来源（版本已钉，作者本地有克隆，不进本仓库）

| 来源 | 钉死版本 | 许可 | 实测规模 |
|---|---|---|---|
| `obra/superpowers` | `2ce8aa15`（2026-10-21） | MIT © 2025 Jesse Vincent | 15 个 skill |
| `affaan-m/ECC`（前身 everything-claude-code） | `b38be6a7`（2026-10-29） | MIT © 2026 Affaan Mustafa | 314 个 skill、71 个 agent、98 个 command |
| `DietrichGebert/ponytail` | 已读，笔记在作者本地 | MIT | 已装为本地 skill `ponytail` |
| 作者本地的 Hermes skills | 本机 skill 目录 | — | 见 §2 |

**许可处理**：目前只借想法，没有拷贝原文。**一旦拷贝任何原文段落，必须同时带上对应的版权声明和 MIT 许可文本**（见 `NOTICE.md`）。

## 1. 重要的事实：Superpowers 的主干，本地早已有了

本地 `test-driven-development`、`systematic-debugging`、`requesting-code-review` 三个 skill 的头部都写着 `author: Hermes Agent (adapted from obra/superpowers)`。所以"结合 Superpowers"的主要工作**不是再装一遍**，而是只补**本地缺的那几块里真正有用的**。
本地**没有**的 Superpowers skill 共 12 个：`brainstorming`、`diagnosing-superpowers`、`dispatching-parallel-agents`、`executing-plans`、`finishing-a-development-branch`、`receiving-code-review`、`subagent-driven-development`、`using-git-worktrees`、`using-superpowers`、`verification-before-completion`、`writing-plans`、`writing-skills`。

## 2. 取舍总表

### A. 采用 / 改造进登峰（本项目真正需要的）

| 登峰里的位置 | 取自 | 取什么（具体到哪一条） | 怎么改 |
|---|---|---|---|
| **F5 完成 = 对产物的检查通过** | ECC `loop-design-check`：「the exit code is final」「the 'done' cell is flipped by a human only，loop 是 worker 不是验收官」；Superpowers `verification-before-completion`：「Agent reports success → 查 VCS diff」 | 把"不信自述"从散文变成**运行器的代码路径**：终态只由运行器在 check 通过后写 | 已在 M0 实现。Superpowers 那条铁律是给**人和 agent 读的**，我们把它做成**机器强制**——Superpowers 自己的 `writing-skills` 也写了：「能用正则/校验自动化的约束就自动化，文档留给需要判断的地方」 |
| **journal 的事件格式** | Superpowers `executing-plans`「completion contract」：任务完成那一行必须写进**最终测试命令和结果**，每个偏离有 `Ruling:` 行 | `stage_done` 事件记：check 命令、rc、输出哈希 | 只借字段设计，不借整个计划执行流程 |
| **AC6 审批：绑定产物哈希、旧批准失效** | ECC `operator-approval-loop`：草稿 sha256、按"纪元"记录决定、过期的批准不能放行改写后的文本、同一批准不会被两个 worker 各投递一次 | 审批记录 = {阶段, 被批准产物的 sha256, 批准人, 时间}；产物一变，旧批准作废 | **不要**它的 SQL 账本、对手方、渠道、内部通知这整套。只取"哈希 + 纪元"两点 |
| **已知孤儿缺口** | kiso `docs/durability.md`：「started 但从未回报的执行 = `uncertain`，阻塞等人决定」（不是 Superpowers/ECC，来自 step-0 试跑） | `Popen` 前先 fsync「即将启动」；续跑见到它但没有 pgid → 幂等阶段重跑，非幂等阶段停 | 借想法 |
| **AC5 阶段指纹** | DVC（step-0 试跑，8/11） | 指纹 = 命令 + 依赖内容哈希，不一致则失效 | 自己写几十行，不引入 DVC |
| **阶段设计 skill（新增，唯一的新 skill）** | ECC `loop-design-check`：Step 0 四条件门（任务每周重复、可自动验证、预算够、agent 有能"看到结果"的工具，缺一不建）；Step 1 机器可判定的目标 + **边界条件**（防 Goodhart：只检查"测试全过"会被"删测试"钻空子）；独立的 judge | 做成 `makeextreme-stage-design`：写 `stages.json` 的方法——每阶段一个 `check`、一个"不得做什么"、是否幂等、是否需审批；以及"何时**不**该用登峰（阶段未知 → 交给 Longhaul）" | 改写为我们的格式，砍掉 `/loop`、`/schedule`、Claude Code 子 agent 的部分；中文触发词也不要 |
| **skill 的测试方法** | Superpowers `writing-skills`：「没看过 agent 在没有这个 skill 时失败，就不知道它教得对不对」（压力场景 = 测试，基线失败 = RED） | 新增的那个 skill 上线前，先拿一个**真实失败**（OCR 0/248、159/272）当基线，再写 skill，再看 agent 是否遵守 | 采用方法，不采用其 15k 字的完整流程 |
| **第一个客户的 playbook** | 本地 `video-briefing`、`youtube-content`（含"证据分级简报"一节）、`hermes-agent`「Multi-stage work — verifiable exits」（含 7 个阶段出口表） | 把已经手工验证过的出口检查（分母不可省、后台启动≠完成）**翻译成 `stages.json` 的 `check`** | 这是登峰 M3 / AC10 的内容；不重写文字，只把检查可执行化 |

### B. 复用现有 skill，只引用，不拷贝

| 本地 skill | 用在哪里 |
|---|---|
| `ponytail` | 登峰自己的开发纪律：先查有没有现成的，最小完整改动，`shortcut:` 账本；**对方案偷懒，不对阅读偷懒** |
| `test-driven-development`、`systematic-debugging`（含 Premise Rule） | M1 开发流程；探针先 RED 再 GREEN；同一前提两次失败就怀疑前提（这次 step-0 三次探针自错就是例子） |
| `requesting-code-review`（含 Step 4b/4c/6b） | M1 里程碑的 Sonnet 中间审计 + Opus 终审的清单 |
| `eval-harness-integrity` | 防止"自己出题自己评分"；变异测试的口径 |
| `context-handoff` | 任务跨 harness / 跨会话交接时的结构 |
| `trio-dev-loop`、`three-model-roundtable`、`grill-me`、`spike` | 开发流程与决策；**登峰不重复实现**它们 |
| `scheduled-agent-loops` | 第二个客户（`grill-me` cron）接入时参考 |

### C. 不取（及理由）

| 项目 | 理由（证据类型） |
|---|---|
| Superpowers `using-superpowers` | [读描述] 要求"在**任何**回复前强制调用 skill，包括澄清问题"。Hermes 已有自己的 skill 路由，叠加会增加每轮开销并与之冲突 |
| Superpowers `brainstorming` | [读描述] 「You MUST use this before any creative work」。与你的偏好冲突：新项目先 Recon+Plan+Grill，GO 之后**立即执行** |
| Superpowers `finishing-a-development-branch`、`using-git-worktrees` | 前者的选项含 push / 开 PR，而登峰仅限本地；后者我们用 trio 的"互不相交文件白名单"代替 |
| Superpowers `writing-plans`、`executing-plans`、`subagent-driven-development`、`dispatching-parallel-agents` | `trio-dev-loop` 已覆盖同一职责；只摘了 completion contract 的字段（见 A） |
| Superpowers `diagnosing-superpowers`、`receiving-code-review` | 与登峰无关 / 本地 review 流程已覆盖。后者留待 M4 看一眼 |
| ECC `gateguard`（正文 42 KB） | [读描述] 是 PreToolUse 钩子，绑定 Claude Code；篇幅与登峰 130 行核心不成比例 |
| ECC `delivery-gate` | [读描述] Claude Code Stop 钩子，靠"措辞模式"的**表面文本启发式**判断。我们的完成判定是对产物的检查，不看措辞 |
| ECC `continuous-learning-v2` | 自动观察会话并**自动演化成 skill**——与"别让 agent 自动改技能库"的既定结论冲突 |
| ECC `autonomous-loops` | [读描述] 自述"仅为兼容保留" |
| ECC `unified-memory`、`autonomous-agent-harness`、`orch-*` | 引入第二套记忆库 / 又一个 harness / 绑定其 agent 体系；与"登峰是地板，不是 harness"相反 |
| 整个 ECC 的其余 ~290 个 skill | 每个 skill 在 Hermes 里都占系统提示的一行索引（pstack 那次已确认），照搬等于每次对话多交"索引税"，还稀释路由 |

## 3. 登峰交付物的构成（取舍后的结果）

1. **运行器 + CLI**（代码）：机械规则全部在这里——完成判定、锁、续跑、审批、指纹、孤儿清理。
2. **一个新 skill：`makeextreme-stage-design`**（判断类规则）。**这是本项目唯一新增的索引行。**
3. **playbook 模板**（`stages.json`）：先做视频流水线一份。
4. **既有 skill 的小补丁**（不新增索引行）：只在 `requesting-code-review` Step 6b 补两处 Superpowers 里本地缺的措辞——"should/probably/seems to"这类词是红旗；回归测试要走"写 → 过 → 撤销修复 → **必须失败** → 恢复 → 过"。**已写（2026-11-01）**：Step 6b 补了三条——措辞红旗；回归测试必须"写 → 过 → 撤销修复 → 红在与对照不同的行 → 恢复 → 过"（对照先绿、拷贝与原件同样忠实）；拒绝类测试必须断言确切的拒绝而不是"返回码非零"（M1 里一个变异体就靠崩溃冒充拒绝而存活）。后两条来自 M1 的实测，不来自 Superpowers。skill `makeextreme-stage-design` 同日创建（v0.1.0，唯一的新索引行）。台账本身你仍未明确确认；两项都是可逆的本地 skill 改动。
5. **`NOTICE.md`**：来源、版本、许可，拷贝原文时同步更新。

## 4. 本页未验证的部分（避免被当成事实）
- ECC 与 Superpowers 的 skill 我读了**目录、描述、以及少数几个的全文**（`verification-before-completion`、`loop-design-check`、`change-impact`、`operator-approval-loop` 的前部、`executing-plans` 的 completion contract 一节、`writing-skills` 开头）。**其余只读到标题或描述，没有通读**；表中标 [读描述] 的结论只来自描述文字。
- 没有运行过 ECC / Superpowers 的任何 skill、钩子或安装器。
- "本地早已有 Superpowers 主干"这一条，依据是三个 skill 头部的 `author` 字段，**没有逐段比对内容的相似度**。

## 另见（2026-11-01，未取用、未评测）

网页检索时看到的同类项目，只读了搜索结果里的简介，没有读代码，没有取用任何东西：
`areeves/revenant`（crash-safe、可恢复、基于文件的 Python 流水线框架；README 里列了它）、
`TokonoMix/agents-never-sleep`（长跑 agent 的恢复与看门狗）、`deepansh-saxena/DuraLang`（基于 Temporal 的崩溃恢复示例）、
`apache/maka`（运行时恢复架构文档）。没有和它们做过对比，所以不对它们的优劣下任何结论。
