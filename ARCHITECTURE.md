# 登峰 · Makeextreme — 架构冻结稿 v0.1

状态：草稿，待你确认后冻结 · 日期：2026-10-31 · 仓库名：`makeextreme`（已确认可用：GitHub 用户/组织、PyPI、npm 均为空）
证据标签：**[实测]** 本次在本机跑过 · **[读取]** 读自文件 · **[推断]** 我的判断，可能错

---

## 1. 它是什么，不是什么

**是**：套在现有 harness（Hermes、Claude Code、Codex）上的一层。它让长任务做到三件事：
中断后从最后一个绿阶段续跑；阶段只有通过实际产物的检查才算完成；完成时留下可复核的证据。

**不是**：模型循环、工具层、权限系统、UI。这些全部借用宿主。

**适用**：阶段在开跑前已知的任务——下载→转写→抽帧→OCR→成稿→交付这类流水线。
重点是**可靠执行**：扛崩溃、续跑、凭产物判完成、留证据。

**不适用**：事先不知道有哪些阶段的探索型任务。那是 Longhaul 协议的领地（长途、未知、边做边调）。
本项目的定位因此**不是"远航"**，而是"地板"：不管上面的 agent 怎么探索，底下的执行不丢、不假完成。
命名应当表达这个功能，不沿用 Longhaul 的航海隐喻。

## 2. 和 Longhaul 的边界

**[读取]** Longhaul v1.1 的计划文件 §8 明写："No runtime, scheduler, process-restart or model router"，
并说运行时适配器是 "a v1.3 conversation, and only when crash-resume is actually needed"。

所以分工是：
- **Longhaul = 协议**：任务状态的格式（schema v2）、证据绑定、`gate` 完成检查、重试预算。
- **本项目 = 运行时**：真正去执行阶段、扛住崩溃、续跑。恰好是 Longhaul 明确留空的那一块。

需求依据 **[读取，来自本会话历史]**：`grill-me` cron 连续 4 次以 status -15 退出且"未写入持久终态"；
视频流水线 OCR 在 159/272 帧处被误判为完成。这就是 Longhaul 所说的"crash-resume 确实需要"。

**硬规则**
- F2a 不依赖 Longhaul 的代码和 schema（2026-11-01，D9）：只拷贝 `scripts/secret_scan.py`（取自 v1.1 `af52cd8`，Apache-2.0，随 `NOTICE.md` 署名）。v1.1 的 gate、状态格式一律不接。
- F2b 不向 `~/Projects/longhaul` 写任何东西。**[实测]** 它的工作树正在做 v1.2（eval harness），
  有未提交改动，读取时测试 130 项中 1 项失败（`test_declared_mutant_scores_reproduce_on_the_oracle`）。那是它自己的在研状态，不归我们修。

## 3. 冻结的设计决定

| # | 决定 | 理由 |
|---|---|---|
| F3 | 每个任务一个目录：`stages.json`（规格）、`task.json`（状态）、`journal.jsonl`（只追加事件日志） | 人能直接读；状态放在能检查的地方，不放进进程 |
| F4 | 阶段契约 = `{id, run, check}`；`check` 是对**实际产物**的命令，退出码 0 才算过 | "OCR 跑了"不等于"OCR 跑完了" |
| F5 | **进程退出码 0 永远不等于完成**；终态由运行器在 check 通过后写，不由阶段自己写 | 159/272 的教训 |
| F6 | 状态写入走"临时文件 + fsync + 原子 rename"；日志每条 fsync | 崩溃时不留半个文件 |
| F7 | 单写者锁，记录 pid + 进程启动 tick；持锁者已死则接管，存活则拒绝 | 防 pid 复用，防双写 |
| F8 | 续跑：从最后一个绿阶段开始，已完成阶段不重跑；崩溃阶段重跑前先杀掉它遗留的孤儿进程组 | 见下文"实测" |
| F9 | 不可逆动作（删除、发送、部署）声明为 `approval: required` 阶段，运行器暂停并记录，**不自动放行** | 拒绝 pstack 的 never-block-on-the-human 用于不可逆场景 |
| F10 | 状态和日志里不得出现凭据；完成时对 `journal.jsonl` 与 `task.json` 做凭据扫描（拷贝自 Longhaul v1.1 的 `secret_scan.py`，不依赖其余部分） | 沿用已有检测，不重写；不绑 Longhaul 的 schema |
| F13 | 不可逆（`approval`）阶段在崩溃或被 SIGTERM 中断后进入 `uncertain`：运行器清理孤儿但**不自动重跑**，退出码 5；人用 `resolve --done`（check 必须通过）或 `resolve --retry` 决定 | 动作可能已经发生；防止重复发送/删除（借 kiso 的 uncertain 想法） |
| F11 | 只用 Python 标准库，≥3.10，先支持 Linux | 与 Longhaul 同风格；本机即 Linux |
| F12 | 宿主 v1.0 只有两个：通用 shell、Hermes（`hermes chat --query-file … -Q`，按 Longhaul-trio 记录的隔离坑清洗环境） | 先打通两条，再谈 Claude Code / Codex |

## 4. v1.0 明确不做

调度器（交给 systemd 或 Hermes cron 去调用 `run`）· 模型路由 · UI · MCP 注册表 · 多宿主一次到位 ·
阶段 DAG 并行（阶段内部的并行属于宿主）· 云端同步。

**规则**（借自 Longhaul 自己的原则）：没有失败测试的新字段，不加。

## 5. 验收标准（每条都能机器检查）

| AC | 内容 | 状态 |
|---|---|---|
| AC1 | `kill -9` 运行器于阶段中，续跑后：已完成阶段不重跑、崩溃阶段重跑一次、孤儿进程被清掉 | **[实测] 通过** |
| AC2 | 阶段退出码 0 但 check 失败 → 标 failed，运行器停止，后续阶段不动 | **[实测] 通过** |
| AC3 | 对已完成任务再次续跑：不执行任何阶段，状态文件字节不变 | **[实测] 通过** |
| AC4 | 持锁者存活 → 拒绝（退出码 3）；持锁者已死 → 接管并完成 | **[实测] 通过** |
| AC7 | SIGTERM（即 cron 的 -15）→ 退出码 143，状态与日志记 `interrupted`；续跑可完成 | **[实测] 通过** |
| AC5 | 产物改动后，只让依赖它的阶段失效（阶段指纹 = 命令 + 显式声明的 `deps` 内容 sha256，记入状态；照 DVC 的思路，不引入 DVC） | **[实测] 通过**（`tests/test_fingerprint.py`，6 项） |
| AC6 | `approval` 阶段：无记录的批准不得继续；批准绑定阶段指纹（命令 + check + deps 内容），产物一变旧批准作废；绑定阶段 id；运行器从不写批准记录 | **[实测] 通过**（`tests/test_approval.py`） |
| AC8 | 任务完成时对 journal 与 task.json 做凭据扫描；埋入凭据 → 完成被拒（D9：不再接 Longhaul gate） | **[实测] 通过**（`tests/test_secrets.py`；断行的日志行按纯文本扫描） |
| AC9 | Hermes 宿主跑通一个真实阶段（清洗环境，结果被捕获）——按需集成测试，不进 CI | 未做 |
| AC10 | 第一个真实客户：视频流水线（下载→转写→抽帧→OCR→成稿→交付）在短视频上端到端跑通；OCR 期间被杀，续跑后最终产物哈希与不中断的一次相同 | 未做 |

**M0 的验证方式 [实测]**：`spike/test_m0.py` 11 项全过；随后做了变异测试——故意破坏运行器 5 处
（去掉清孤儿、退出码 0 即完成、永不跳过、不接管死锁、不记 interrupted），**5 个变异全部被对应的探针抓到**，
说明这些测试不是自己验证自己。

## 6. 里程碑

估算未经测量，仅供排序。

- **M0 可行性**（已完成）：`spike/runner.py` 约 130 行 + 11 个探针。
- **M1 核心**（**已完成 2026-11-01**，提交 `0abc449`、`102f57c`）：AC5、AC6、AC8 已补；孤儿缺口已闭合；spike 拆成包 `makeextreme/`（`core.py`、`secret_scan.py`、`__main__.py`）。27 个测试 + 18 个变异体均被抓到；`spike/test_m0.py` 仍 11/11。**未做**：独立审计（D5：Sonnet 里程碑审计）、`requesting-code-review` 两处措辞补丁、skill `makeextreme-stage-design`。
- **M2 宿主**：shell + Hermes 两个 host，AC9。
- **M3 第一个客户**：视频流水线（AC10）；之后接 `grill-me` cron。
- **M4 收口**：README、CI、与 Longhaul 钉版本对账。

## 7. 已知缺口与风险

- **[已修，2026-11-01]** 运行器恰在 `Popen` 与状态保存之间被 SIGKILL 时 pgid 会丢失。现在每次尝试给子进程环境注入 `MAKEEXTREME_RUN_ID`，恢复时按它扫 `/proc/*/environ` 杀掉整组，不依赖 task.json 里的 pgid（`tests/test_approval.py::OrphanGap`，变异 M6 被抓）。残余：仅 Linux；改了 uid 的子进程读不到 environ。
- **与 Longhaul 重复**：靠 F2 的"协议/运行时"分工控制。若 M1 时发现要改 Longhaul 的 schema，停下来先和你谈。
- **范围膨胀成框架**：靠"无失败测试不加字段"控制。
- **宿主污染基线 [推断]**：**[实测]** `claude -p --model sonnet` 能正常回复（Claude CLI 已重新登录），
  但回复末尾自带 "Skipped: nothing to check. Risk: none." 一行，像是有常驻的 ponytail 类规则在生效，来源我没查。
  任何基线对照实验都必须在隔离环境里跑。
- **Linux 专用**：`/proc/<pid>/stat` 和进程组语义。macOS/Windows 不在 v1.0。

## 8. 待你决定

- **D1 项目名**：**已定** — 仓库 `makeextreme`，展示名"登峰 · Makeextreme"。
- **D2 钉版本**：钉 Longhaul v1.1（`af52cd8`）——默认采用。Longhaul v1.2 目前未发布且在修（见聊天），不依赖它。
- **D3 仓库位置**：独立仓库 `~/Projects/makeextreme`——默认采用。
- **D4 第一个客户**：视频流水线——默认采用。
- **D5 M1 的执行方式**：**已定 = A**（2026-10-31，用户回复）。我自己写；Sonnet 在里程碑处审计；Opus 只做最终审；不动 GPT-6-Astra。
- **D6 交付内容的来源**：**已定**（2026-10-31，用户指令）：结合 Superpowers、ECC、Ponytail 与本地 Hermes 实用且适用的 skill。取舍台账见 `docs/SOURCES.md`。

**Grill 第 1 轮（2026-11-01，用户用字母回答）**
- **D7 受众与成功标准**：**已定 = 1B**。自用 **加** 开源到 GitHub。v1.0 成功 = 视频流水线 AC10 通过且 Hermes 可调用。许可证、公开时机、分发形式见第 2 轮（待定）。
- **D8 杀死准则**：**已定 = 2C**。不设"比现状强否则砍掉"的对照实验，做到 M4。**后果（我的意见，已告知）**：差异点 1–4 到发布时仍未经 A/B 证明，因此 README 只能写**已测量**的事实（STEP0 试跑表），不得写"比 X 更好"。
- **D9 Longhaul 耦合**：**已定 = 3B**。只拷贝 `secret_scan.py`（Apache-2.0，NOTICE 署名），去掉 gate 桥（AC8 已改写），证据格式用自己的 journal。
- **D10 审批威胁模型**：**已定 = 4A**。只防"意外自动放行"，批准绑定产物哈希、产物变则旧批准作废；**不声称能防持有 shell 的 agent 自行批准**（同账户同 shell，运行器分不清），文档写明。附加规则：不可逆阶段必须声明 `approval: required`，否则不得入阶段。
- **D11 预算**：**已定 = 6B**。无封顶，做完 M4。
- **D12 崩溃后谁续跑**：**已定 = 5A**（2026-11-01）。cron tick 只当启动器和报告员（沿用本地 `scheduled-agent-loops` 的模式：tick 有 3 分钟硬中断，worker 在后台用 `flock -n` 起），登峰当 worker。**登峰里不写看门狗/重启守护代码**；只在文档里放一份启动脚本示例。原因：Longhaul v1.1 自述是协议而非运行时（计划 §8 "无运行时、调度、进程重启"），不能重启进程；登峰的单写者锁和"已完成则什么都不做"让每个 tick 都启动一次是安全的。
- **D13 许可证**：**已定 = 7A** Apache-2.0（与 Longhaul、被拷贝的 `secret_scan.py` 一致）。`LICENSE` 已放入仓库（与 Longhaul 的同一文本）。版权行在首次公开前补全。
- **D14 首次公开推送**：**已定 = 8B** AC10 通过后才公开。推送不可逆：只在用户明确说"推"之后做，并先过三关——凭据与路径扫描（仓库含 `/home/dav` 路径与 `trial/`）、README 只写已测量事实（D8）、商标与域名检查（目前都没查）。
- **D15 分发**：**已定 = 9A** 只放 GitHub，`git clone` 即用，纯标准库；PyPI 等 M4 之后再议。
- **D16 README 语言**：**已定 = 10D** 英文、中文、德文三语。**风险（我的意见）**：三语是三份要同步的文档；Longhaul 的审计（DOC2）已经发现过"zh/de 缺了一条提示却没有测试抓到"。因此 README 的每个语言段落都必须有测试：存在、且含同一组必备事实（平台、审批威胁模型声明、测量表链接）。

## 9. 同类对照（2026-10-31，GitHub API 实测星数；功能描述取自各仓库自述，未逐个运行）

**结论：崩溃续跑 + 审批这一块已经有人做了，不是空白。** 本项目不能把它当卖点。

| 类别 | 项目 | 与本项目的重叠 |
|---|---|---|
| agent 持久运行时 | `vincemakes/kiso` ★83（TypeScript，约 2,200 行内核）：事件溯源会话、跨进程持久的审批、崩溃后精确续跑 | **最接近**：续跑 + 审批几乎同款 |
| agent 持久运行时 | `julep-ai/julep` ★6,575：崩溃可续、可安全重试、解释每一步 | 续跑 |
| agent 编排 | `kelvinschen/acpus` ★41（TypeScript）：编排 Claude/Codex 等，崩溃存活、暂停续跑 | 续跑 + 多宿主 |
| agent 预算与续跑 | `prashar32/riskkernel` ★20：预算、崩溃可续、人工审批门 | 续跑 + 审批 |
| Python 零依赖 | `chenhz01/resilient-agent-toolkit-v2` ★0：检查点/续跑等零依赖 Python 工具 | 语言与风格最像，但几乎无人用 |
| 通用耐久执行 | Temporal ★24k、Restate ★4.6k、DBOS（Python）★1.7k、Inngest ★6k、LangGraph ★44k | 续跑 + 状态持久 |
| 阶段哈希与续跑 | DVC ★16k、Snakemake ★2.9k、Nextflow ★3.5k | **只重跑变化的阶段**，对应 AC5 |
| 证据校验 | `yebiguo/ProofRun` ★15、`rokabytedev/proofrun` ★12、`donewhen` ★65 | "证据而非声明" |

**所以真正可能成立的差异只剩这几条**（均为 [推断]，需要在 M1 开头验证）：
1. **完成 = 对实际产物的检查通过，不是进程退出码**（F5）。上表项目多数以步骤返回为完成。
2. **套在现有宿主（Hermes、Claude Code）外面，不是又一个 agent 运行时**。kiso、julep、acpus 都自带运行时。
3. **与 Longhaul 的状态格式和 gate 原生对接**（证据绑定到产物哈希，凭据扫描）。
4. **Python 标准库、单文件级别、本机可读可改**。

**M1 第 0 步（先做，限一个工作段）**：对 kiso、resilient-agent-toolkit-v2、DVC 三个，
按 AC1–AC4、AC7 和审批各做一次真实试跑（不是读 README）。
**停止准则**：若其中任一个已满足 AC1–AC4、AC7，且能被 Hermes 的 shell host 直接驱动，
则**采用它**，本项目只保留 AC8（gate 桥）和"产物检查即完成"这层薄包装；否则按原计划继续写。

**第 0 步结果（2026-10-31，已执行）**：详见 `docs/STEP0_同类试跑.md`。同一组黑盒场景：
M0 spike（对照）9/9；toolkit-v2 5/10；DVC 8/11；kiso 未运行（它是需要接模型的 agent 运行时，
准则对它不适用——依据 README 的推断，未运行其 kill -9 脚本）。**无一满足 AC1–AC4、AC7 → 不采用，继续自己写。**
副产物：AC5 照 DVC 的阶段指纹做（不引入 DVC）；孤儿缺口用 kiso 的"uncertain"思路闭合；
审批必须是绑定产物哈希的独立记录（toolkit-v2 的审批门在无人批准时再跑一次就自动放行，已复现）。

## 10. 交付内容的来源（D6）

见 `docs/SOURCES.md`（采用 / 复用 / 不取 的逐项台账）与 `NOTICE.md`。结论：运行器 + CLI（机械规则）、
**仅 1 个**新 skill `makeextreme-stage-design`、playbook 模板（先做视频流水线）、对既有 skill 的小补丁（不新增索引行）。
