# Ankorgine-CognitiveWorld

中文 · [English](#english)

## 概览

Ankorgine-CognitiveWorld 是一个积极开发中的本地认知多智能体世界模拟引擎。项目研究如何将独立的智能体认知、世界状态、行动裁定、事件因果与时间线恢复组织成可扩展、可追溯的模拟系统。随仓库提供的 Anchor 桌面宿主默认提供《灰域之外》世界预览；整个 MVP 的普通可见桌面操作尚未完成验收。

系统将叙述与世界事实分开：语言模型可以理解输入或提出候选，但不能直接改写世界。NPC 的目标、记忆和判断属于各自的认知范围；行动是否产生效果由正式裁定与事件提交链决定。对尚未安装的机制，系统保留不确定性，不把语言上的合理性当作物理结果。

## 示例世界：《灰域之外》

《灰域之外》（Gray Domain Beyond）以天意、五种倾向、实验品与认知腐化为创作背景。当前世界包提供序章和可交互的门／通道场景，用于展示引擎的有限闭环；序章不是世界事实或 NPC 记忆，背景主题也不意味着相应机制已经实现。

## 研究问题与设计原则

完整原则见 [Core Doctrine](docs/COGNITIVEWORLD_CORE_DOCTRINE.md)：独立世界权威、角色自有认知、逐次重建上下文、模型提案与确定性执行、证据治理及按需计算。它区分基础不变量、已有窄路径与未完成目标。

- **责任分离。** WorldState 保存规范世界状态；Cognition 管理角色自己的认知；AgentDecision 选择候选；Resolution 裁定因果效果；EventProcessor 提交已确认变化；Presentation 负责面向玩家的安全展示。
- **信息有来源和权限。** 玩家与 NPC 只依据各自获准的 Observation 和认知投影行动。记忆保留来源，但主观记忆或语义相似度都不证明世界事实。
- **候选不等于结果。** 输入理解、目标解析、只读查看、澄清、未覆盖机制与正式行动具有不同结果边界。信息不足、尚未支持的机制和已经核实的不可能效果应当区分。
- **恢复与隔离。** 签名存档、事件历史、Timeline 与 Runtime session/generation 的验证共同约束恢复及迟到任务。分支和恢复不能凭借模型输出获得新的事实权限。
- **有界探索。** 现有 Event Tree 与证据查询提供有限的候选诊断；通用未知机制探索和未来分支模拟仍是研究方向。

## 架构概览

下图表示当前主要调用路径；分支不意味着每次玩家输入都会触发 NPC 回合或存档。

~~~mermaid
flowchart LR
    UI[Anchor 桌面界面] --> HOST[产品网关 / 宿主装配]
    HOST --> TASK[后台输入协调器]
    HOST --> RUN[Runtime 调度]
    TASK --> SERVICE[PlayerActionService]
    SERVICE --> UNDERSTAND[输入理解与授权目标候选]
    UNDERSTAND --> READ[只读查看 / 澄清 / 无结果]
    UNDERSTAND --> ATTEMPT[行动候选与 Attempt]
    ATTEMPT --> RES[Resolution]
    RES --> EVENT[EventFactory / EventProcessor]
    EVENT --> WORLD[WorldState / EventHistory]
    EVENT --> OBS[授权 Observation]
    READ --> PRES[Presentation 安全投影]
    OBS --> PRES
    PRES --> HOST
    HOST --> UI
    RUN --> TURN[AgentTurn / AgentDecision]
    OBS --> TURN
    TURN --> COG[Cognition / Memory]
    COG --> TURN
    TURN --> ATTEMPT
    SAVE[SaveManager / 验证恢复] <--> RUN
    SAVE <--> WORLD
~~~

Core 不依赖 PySide6。桌面端通过产品网关和薄 DTO 接收受限结果；它不直接拥有 WorldState、记忆 Store 或写入许可。只读查看不为展示而制造 World Event；世界变化仍须经过 Resolution、EventFactory、EventProcessor 和 Runtime 写入边界。

## 当前实现

| 范围 | 已实现的有限路径 |
|---|---|
| 世界与机制 | 规范 Entity/WorldState、内容校验与安装，以及示例世界使用的门与已知通道机制；尚非通用 ECS 或物理引擎。 |
| 玩家输入 | 可选的本地 Ollama 输入理解、基于当前授权 Observation 的请求内目标句柄、服务层澄清接续、只读观察和正式行动适配。模型不可用时提供独立故障状态。 |
| 行动与展示 | Resolution 裁定、正式 Event 提交、授权 Observation、类型化行动反馈与 Presentation 安全投影。已满足的目标与确认的状态变化有不同反馈。 |
| 行为适应 | 已确认的锁门失败可影响该 owner 的有限候选评分，反馈另有签名快照与恢复；不等于 NPC 已消费结果，也不等于一般 Belief／Memory 修订。 |
| 智能体认知 | owner 范围内的 Goal、Belief、Memory 与有限 AgentDecision；受治理的 Memory 写入、规范 Store 复核，以及词汇、可信 Event 锚点和可选语义检索。部分自主调度与冲突／机会发现有窄范围实现。 |
| 运行与恢复 | 后台串行输入协调、请求幂等及原 Runtime 代次约束；显式场景状态编解码、签名 Bundle、隔离验证与原 Timeline 的冷启动恢复。 |
| 桌面宿主 | PySide6 世界选择、交互流、世界状态页、真实存档列表及保存／恢复入口，提供《灰域之外》示例世界与签名存档管理。 |

上述是源码与自动化测试覆盖的范围，不代表所有自然语言、社交或世界机制已得到产品级验证。Memory 的正式 D3 决策依赖宿主显式注入策略与授权组件；可用的接口不等于默认策略或完整自主记忆治理。SelfModel 只有可选、带来源的 tentative 更新；Personality 尚无对应的正式演化路径。

## 开发状态与局限

**v1.0 是当前有限能力的发布检查点；完整的可见桌面验收仍待补齐。**

通用的“行动预期 → 正式结果 → 主体获准证据 → 必要消费证明 → 受治理认知修订”闭环尚未实现。三层空间表示和认知／感知／物理独立 LOD 是设计方向，不是现成的通用三维求解器或跨域协调器。

- 普通 Windows 可见桌面的完整进入、行动、保存、退出、重启、恢复及继续行动流程仍待实际验收；离屏 Qt 与独立进程测试不能代替该操作。
- 项目声明 Python 3.10 起；现有独立验收使用 Python 3.14.7，尚未在 3.10 上动态验证。
- 真实 Ollama 测试需显式启用或配置模型。本候选的全量测试中有 9 项因此跳过，不能据此推断所有模型路径的质量。
- 自然语言指代、复杂澄清、机制发现和未知行动的通用性仍有限。桌面 NPC 对话产品闭环及独立的授权历史浏览尚未完成。
- Timeline 祖先校验债务仍开放，D3.2.4 保持冻结。通用 ECS／复合实体、广义物理机制、三轴自适应 LOD、持续自主世界驱动和假设分支模拟仍属规划，不是现有功能。

## 环境与启动

[pyproject.toml](pyproject.toml) 要求 Python **>=3.10**；桌面依赖组为 **desktop**（PySide6 >=6.7）。以下命令在仓库根目录的 Windows PowerShell 中执行。核心库不需要 Qt；桌面入口来自 anchor_desktop.app:main。

~~~powershell
py -3.14 -m venv .venv
$python = Join-Path $PWD '.venv\Scripts\python.exe'
& $python -m pip install -e .
# 使用桌面端时，在同一环境中安装可选依赖：
& $python -m pip install -e '.[desktop]'
& $python -m anchor_desktop
# 或运行 .\.venv\Scripts\anchor-desktop.exe
~~~

命令中的 3.14 与已有验收环境一致；它不改变项目的 >=3.10 元数据要求。启动后的新世界目录提供“灰域之外”（Gray Domain Beyond）；已有签名存档可通过“管理世界与存档”访问。世界的 manifest.json 和 content.json 位于 [src/anchor_desktop/worlds/](src/anchor_desktop/worlds/)；内容仍需经过正式校验与裁定。新会话只动画展示世界包序章；跳过仅显示序章全文，读档不重播。初始观察及交互授权仍保留，场景信息由玩家主动请求“观察周围”后经现有授权路径展示。向上阅读历史时不会自动跳到底部。管理页分别提供内置包隐藏、当前运行实例的未保存进度丢弃与单个手动存档删除，均须确认；尚不提供用户安装包卸载或持久实例的级联删除。已配置的本地 Ollama 在后台执行一次有界预热推理，失败可手动重试；预热期间提交的草稿保留在输入框，应用不会自动排队或重复执行。序章不是角色记忆，预热响应不进入交互历史。可尝试输入“观察周围”，再依据界面实际显示的对象提出行动；示例句子并非保证成功的脚本。

自由输入的本地 Ollama 解释器为可选功能。先自行安装并启动 Ollama，使用 ollama list 查看**已有**对话模型；项目安装不会下载模型。在启动桌面的同一 PowerShell 会话中可配置：

~~~powershell
ollama list
$env:COGNITIVEWORLD_INPUT_UNDERSTANDING_PROVIDER = 'ollama'
$env:COGNITIVEWORLD_OLLAMA_MODEL = '<ollama list 中已有的对话模型名>'
$env:COGNITIVEWORLD_OLLAMA_BASE_URL = 'http://127.0.0.1:11434/v1'
$env:COGNITIVEWORLD_INPUT_UNDERSTANDING_TIMEOUT = '8.0'
& $python -m anchor_desktop
~~~

输入理解适配器仅接受本机 loopback 地址，并限制超时。未配置服务时，桌面仍可启动，依赖该服务的输入会给出服务不可用反馈。Ollama embedding 是另一项可选、由宿主注入的认知检索适配器；上述变量不会自动启用它。

## 验证与测试

**历史工作树验证（2026-10-24）：1,348 passed、9 skipped、0 failed、0 errors，77.43 秒，退出码 0。** 环境为 Python 3.14.7、pytest 9.1.1、PySide6/Qt 6.12.0；在仓库根目录实际执行 `py -3.14 -m pytest -q -rs`。pytest 使用 `pyproject.toml` 的 `pythonpath = ["src"]`，模块解析已核对为本仓库，而非另一个检出目录。

该历史运行的源码基线为 `main` 的 `c493f6e7eb153cdccdcdfd18069d0ffd326dce4c` 加当时未提交的目录展示及回归测试调整；这不是对已发布标签字节内容的重新验收。9 项跳过为显式本地 Ollama 集成／评估或 Embedding 模型配置要求，具体原因见 [当前状态记录](docs/REPOSITORY_STATUS.md#current-audited-worktree-2026-10-24)。没有执行真实模型验收，也没有将离屏 Qt 结果当作可见桌面验收；Python 3.10 动态兼容仍未验证。

当前开发与 B1/B2/B3 归档状态见[当前里程碑状态](docs/REPOSITORY_STATUS.md#current-milestone-status-2026-10-25)。本次文档同步未运行测试，未将上述历史数字更新为当前 HEAD 的新验收结果。

本地复核可使用：

~~~powershell
& $python -m pip install pytest pytest-qt
& $python -m compileall -q src tests
& $python -m pytest -q -ra
~~~

自动化证据只覆盖所执行的工作树、依赖与环境。先前候选、构建和隔离环境的测试数字保留在状态页的历史记录中，不代表本轮重新执行了那些独立检查。

## 路线图与文档

近期工作以 [DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md) 中现有任务为准：继续验证 ANCHOR-M2-01 的通用输入闭环，完成 ANCHOR-M3-01/02 的可见桌面与保存恢复验收。CPU 主动信息检索、未知机制探索、持续自主世界动力和实体组合属于后续研究方向；这里不设发布日期。

权威文档入口：

- [COGNITIVEWORLD_CORE_DOCTRINE.md](docs/COGNITIVEWORLD_CORE_DOCTRINE.md)：核心原则及不变量。
- [COGNITIVEWORLD_SYSTEM_ARCHITECTURE.md](docs/COGNITIVEWORLD_SYSTEM_ARCHITECTURE.md)：统一架构地图与实现边界。
- [AI_BOUNDARY.md](docs/AI_BOUNDARY.md)：模型的职责、上下文与权限边界。
- [ARCHITECTURE.md](docs/ARCHITECTURE.md)：系统边界和长期设计。
- [DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md)：数据、权限、版本及恢复契约。
- [ENGINEERING_RULES.md](docs/ENGINEERING_RULES.md)：工程与安全约束。
- [REPOSITORY_STATUS.md](docs/REPOSITORY_STATUS.md)：实现状态及历史证据。
- [DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md)：任务与验收条件。
- [SOCIAL_CAUSAL_DESIGN.md](docs/SOCIAL_CAUSAL_DESIGN.md)：社会因果的现有边界与规划。
- [MEMORY_DESIGN.md](docs/MEMORY_DESIGN.md)：记忆治理与检索。

## 许可证

项目代码采用 **AGPL-3.0-only**，见 [LICENSE](LICENSE)。依赖、模型与外部材料各有自己的许可条件；相关来源与发行说明见 [PROVENANCE.md](PROVENANCE.md) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)；[CLA.md](CLA.md)、[CCLA.md](CCLA.md) 和 [TRADEMARKS.md](TRADEMARKS.md) 目前为待审草案，不构成已签署协议。

---

<a id="english"></a>
# English

## Overview

Ankorgine-CognitiveWorld is a local cognitive multi-agent world simulation engine under active development. It investigates how agent-specific cognition, world state, action adjudication, causal events, and timeline restoration can form an extensible and traceable simulation. The included Anchor desktop host defaults to a Gray Domain Beyond preview; the complete MVP workflow has not yet been accepted through ordinary visible desktop use.

Narrative output is separate from world facts. A language model may interpret input or propose candidates, but it cannot rewrite the world. Each NPC has its own scope of goals, memories, and judgments; whether an action takes effect is decided through formal resolution and event processing. A plausible description of an uninstalled mechanism is not a confirmed physical outcome.

## Sample World: Gray Domain Beyond

Gray Domain Beyond (《灰域之外》) supplies an authored opening and a bounded interactive door/passage scene. Heaven's Will, the five tendencies, experimental subjects and cognition-altering corruption are fictional background; their broader mechanics are not installed merely by mentioning them. The opening is neither a world fact nor an NPC memory.

## Research Questions and Design Principles

The [Core Doctrine](docs/COGNITIVEWORLD_CORE_DOCTRINE.md) establishes independent world authority, separately owned cognition, reconstructed action contexts, model proposals with deterministic enforcement, evidence-governed revision and need-based computation. It distinguishes foundational invariants, bounded implementations and unfinished objectives.

- **Separation of responsibility.** WorldState owns canonical world state; Cognition owns each character's cognitive records; AgentDecision selects candidates; Resolution adjudicates effects; EventProcessor commits confirmed changes; Presentation controls player-facing output.
- **Authorized, attributed information.** Players and NPCs act from their respective authorized Observations and cognition projections. Memory preserves provenance, but neither subjective memory nor semantic similarity proves a world fact.
- **Candidates are not outcomes.** Input interpretation, target resolution, read-only observation, clarification, unsupported mechanisms, and formal action have distinct result boundaries. Missing information, unsupported behavior, and verified impossibility should remain distinguishable.
- **Restore and isolation.** Signed saves, event history, Timeline, and Runtime session/generation checks constrain restoration and late tasks. Neither branching nor model output confers new authority over facts.
- **Bounded exploration.** The current Event Tree and evidence queries provide limited candidate diagnostics; general unknown-mechanism exploration and hypothetical future simulation remain research directions.

## Architecture

The diagram shows principal implemented paths. It does not imply that every player input triggers an NPC turn or a save.

~~~mermaid
flowchart LR
    UI[Anchor desktop UI] --> HOST[Product gateway / host assembly]
    HOST --> TASK[Background input coordinator]
    HOST --> RUN[Runtime scheduler]
    TASK --> SERVICE[PlayerActionService]
    SERVICE --> UNDERSTAND[Input interpretation / authorized target candidates]
    UNDERSTAND --> READ[Read-only observation / clarification / no result]
    UNDERSTAND --> ATTEMPT[Action candidate / Attempt]
    ATTEMPT --> RES[Resolution]
    RES --> EVENT[EventFactory / EventProcessor]
    EVENT --> WORLD[WorldState / EventHistory]
    EVENT --> OBS[Authorized Observation]
    READ --> PRES[Presentation safety projection]
    OBS --> PRES
    PRES --> HOST
    HOST --> UI
    RUN --> TURN[AgentTurn / AgentDecision]
    OBS --> TURN
    TURN --> COG[Cognition / Memory]
    COG --> TURN
    TURN --> ATTEMPT
    SAVE[SaveManager / verified restore] <--> RUN
    SAVE <--> WORLD
~~~

Core has no PySide6 dependency. The desktop consumes bounded results through the product gateway and thin DTOs; it does not own WorldState, Memory Stores, or write permits. Read-only observation creates no display-only World Event. Confirmed changes still pass Resolution, EventFactory, EventProcessor, and the Runtime write boundary.

## Implemented Capabilities

| Area | Implemented bounded path |
|---|---|
| World and mechanisms | Canonical Entity/WorldState records, content validation and installation, and the door and known-passage mechanisms used by the sample world; not a general ECS or physics engine. |
| Player input | Optional local Ollama interpretation, request-scoped target handles derived from current authorized Observations, service-owned clarification continuation, read-only observation, and formal action adaptation. Provider failure has a separate outcome. |
| Action and presentation | Resolution adjudication, formal Event commit, authorized Observation, typed action feedback, and Presentation safety projection. An already satisfied goal differs from a confirmed state change. |
| Behavior adaptation | Confirmed locked-door failures can affect bounded owner-scoped candidate scores, with separately signed feedback snapshots and restore. This is not proof of result consumption or general Belief/Memory revision. |
| Agent cognition | Owner-scoped Goal, Belief, Memory, and bounded AgentDecision; governed Memory writes and canonical Store rechecks, with lexical, verified Event-anchor, and optional semantic retrieval. Parts of autonomous scheduling and conflict/opportunity discovery are implemented narrowly. |
| Runtime and restore | Serialized background input coordination, request idempotency, and original Runtime-generation checks; explicit scenario-state codecs, signed Bundles, isolated validation, and cold restoration of the original Timeline. |
| Desktop host | PySide6 world selection, interaction stream, world-state page, real save listing and save/restore entry points, with Gray Domain Beyond as the sample world and signed-save management. |

These are source and automated-test boundaries, not product acceptance of arbitrary language, social behavior, or world mechanisms. Formal D3 Memory decisions require explicit host injection of policy and authority components; an interface does not supply a default policy or complete autonomous memory governance. SelfModel has only optional, source-linked tentative updates; Personality has no corresponding governed evolution path.

## Development Status and Limitations

**v1.0 is a checkpoint for the current bounded capabilities; complete visible desktop acceptance remains open.**

The general recoverable expectation → formal outcome → actor-authorized evidence → required consumption proof → governed cognitive revision lifecycle is not implemented. Three-layer spatial representation and independent cognitive/perceptual/physical LOD are design directions, not an available general 3D solver or unified cross-domain coordinator.

- The complete ordinary visible Windows workflow—enter, act, save, exit, restart, restore, and continue—still needs direct acceptance. Offscreen Qt and independent-process tests do not substitute for it.
- Package metadata requires Python 3.10 or later. Independent acceptance used Python 3.14.7; Python 3.10 has not been dynamically validated.
- Real Ollama tests require explicit opt-in or model configuration. Nine tests were skipped in this candidate's full suite; they do not establish quality across all model paths.
- General language reference, complex clarification, mechanism discovery, and unknown actions remain bounded. The desktop NPC dialogue product loop and independent authorized history browsing are unfinished.
- Timeline ancestor-validation debt remains open, and D3.2.4 remains frozen. General ECS/composite entities, broad physical mechanisms, adaptive three-axis LOD, a continuously autonomous world driver, and hypothetical branch simulation are planned, not implemented.

## Installation and Usage

[pyproject.toml](pyproject.toml) declares Python **>=3.10** and the optional **desktop** group (PySide6 >=6.7). Run these commands in Windows PowerShell from the repository root. Core does not require Qt; the desktop entry point is anchor_desktop.app:main.

~~~powershell
py -3.14 -m venv .venv
$python = Join-Path $PWD '.venv\Scripts\python.exe'
& $python -m pip install -e .
# Install the optional desktop dependencies in the same environment:
& $python -m pip install -e '.[desktop]'
& $python -m anchor_desktop
# Alternatively: .\.venv\Scripts\anchor-desktop.exe
~~~

The 3.14 command matches the accepted environment; it does not change the >=3.10 metadata requirement. The sample world is “Gray Domain Beyond” (灰域之外). Existing signed saves remain accessible through world/save management. World manifest.json and content.json files reside in [src/anchor_desktop/worlds/](src/anchor_desktop/worlds/). Content still passes validation and adjudication. New sessions animate only the package-authored Chinese opening; skip reveals the remaining prologue. Initial evidence and interaction candidates remain intact, and scene information is presented through the authorized path on an explicit observation request. Restores do not replay the opening, and upward-scrolled readers retain their position as messages arrive. Management separates confirmed bundled-package hiding, disposal of unsaved live-session progress, and individual manual-save deletion; user-installed package uninstall and persistent-instance cascade deletion are not supported. A configured local Ollama interpreter warms asynchronously through one bounded inference. Failed warm-up retries are explicit; early input stays in the editor and is never automatically queued or resubmitted. Opening prose is not character memory, and warm-up output never enters chat history. You can try “观察周围” and then propose an action concerning an actually displayed object; the example is not a scripted guarantee of success.

The local Ollama input interpreter is optional. Install and start Ollama separately, and use ollama list to identify an **already installed** chat model; installing this project does not download one. Configure the same PowerShell session before launching the desktop:

~~~powershell
ollama list
$env:COGNITIVEWORLD_INPUT_UNDERSTANDING_PROVIDER = 'ollama'
$env:COGNITIVEWORLD_OLLAMA_MODEL = '<chat model already shown by ollama list>'
$env:COGNITIVEWORLD_OLLAMA_BASE_URL = 'http://127.0.0.1:11434/v1'
$env:COGNITIVEWORLD_INPUT_UNDERSTANDING_TIMEOUT = '8.0'
& $python -m anchor_desktop
~~~

The interpreter accepts loopback addresses only and bounds its timeout. Without a configured service, the desktop can still start, while dependent free-form input reports service unavailability. Ollama embeddings are a separate, optional, host-injected cognition retrieval adapter; the variables above do not enable it.

## Validation and Testing

**Historical worktree verification on 2026-10-24: 1,348 passed, 9 skipped, 0 failed, 0 errors in 77.43 seconds; exit code 0.** Environment: Python 3.14.7, pytest 9.1.1, PySide6/Qt 6.12.0. The actual repository-root command was `py -3.14 -m pytest -q -rs`. The configured pytest `pythonpath = ["src"]` and checked module paths resolve to this checkout.

That historical run used `main` at `c493f6e7eb153cdccdcdfd18069d0ffd326dce4c` plus the then-uncommitted public-catalog and regression-test changes, not the unchanged published tag. The nine skips require explicit local Ollama opt-ins or an embedding-model configuration; see [current status](docs/REPOSITORY_STATUS.md#current-audited-worktree-2026-10-24). Real-model integration, complete visible desktop acceptance and Python 3.10 runtime compatibility were not verified by this run.

See [current milestone status](docs/REPOSITORY_STATUS.md#current-milestone-status-2026-10-25) for the development baseline and B1/B2/B3 archival. This documentation synchronization ran no tests and does not present the historical count above as a fresh result for the current HEAD.

To run the local suite:

~~~powershell
& $python -m pip install pytest pytest-qt
& $python -m compileall -q src tests
& $python -m pytest -q -ra
~~~

Automated evidence covers only the executed worktree and environment. Earlier candidate, build and isolated-environment totals remain historical records in the status document; they were not all re-executed in this audit.

## Roadmap and Documentation

The near-term agenda follows existing entries in [DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md): further validate the general input loop under ANCHOR-M2-01, and complete visible desktop/save/restore acceptance under ANCHOR-M3-01/02. CPU-led information retrieval, unknown-mechanism exploration, continuous autonomous world dynamics, and entity composition are later research directions; no delivery dates are claimed here.

Authoritative documents:

- [COGNITIVEWORLD_CORE_DOCTRINE.md](docs/COGNITIVEWORLD_CORE_DOCTRINE.md): foundational principles and invariants.
- [COGNITIVEWORLD_SYSTEM_ARCHITECTURE.md](docs/COGNITIVEWORLD_SYSTEM_ARCHITECTURE.md): integrated architecture and implementation boundaries.
- [AI_BOUNDARY.md](docs/AI_BOUNDARY.md): model responsibilities, context and authority limits.
- [ARCHITECTURE.md](docs/ARCHITECTURE.md): system boundaries and longer-term design.
- [DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md): data, authorization, versioning, and restoration.
- [ENGINEERING_RULES.md](docs/ENGINEERING_RULES.md): engineering and safety constraints.
- [REPOSITORY_STATUS.md](docs/REPOSITORY_STATUS.md): implementation state and historical evidence.
- [DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md): tasks and acceptance conditions.
- [SOCIAL_CAUSAL_DESIGN.md](docs/SOCIAL_CAUSAL_DESIGN.md): current social-causality limits and plans.
- [MEMORY_DESIGN.md](docs/MEMORY_DESIGN.md): Memory governance and retrieval.

## License

Project code uses **AGPL-3.0-only**; see [LICENSE](LICENSE). Dependencies, models, and external material retain their respective license conditions; see [PROVENANCE.md](PROVENANCE.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for source and distribution notes. Contributions are described in [CONTRIBUTING.md](CONTRIBUTING.md). [CLA.md](CLA.md), [CCLA.md](CCLA.md), and [TRADEMARKS.md](TRADEMARKS.md) remain drafts pending review, not signed agreements.
