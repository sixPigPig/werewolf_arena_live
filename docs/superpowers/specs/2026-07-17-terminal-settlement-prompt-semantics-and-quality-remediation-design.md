# 狼人杀终局结算边界、Prompt 语义与决策质量修复开发设计

## 1. 文档信息

- 编写日期：2026-07-17
- 文档状态：已按统一推荐合同完成开发并通过全链路验收
- 依据对局：`game_d8a3c680`
- 依据运行：`run_2d12b755578b`
- 当前实现基线：`e9728f6b feat: add immediate self-explosion and exile last words`
- 适用范围：`apps/api` 游戏引擎、Prompt、公开事实、质量校验、Live/Replay、语音、Admin 诊断及共享客户端
- 上游设计：
  - `docs/superpowers/specs/2026-07-17-self-explosion-last-words-and-player-reasoning-remediation-design.md`
  - `docs/superpowers/specs/2026-07-14-p0-game-integrity-remediation-design.md`
  - `docs/superpowers/specs/2026-07-14-p1-game-flow-experience-remediation-design.md`
  - `docs/superpowers/specs/2026-07-14-p2-game-quality-performance-remediation-design.md`
  - `docs/superpowers/specs/2026-07-14-p3-quality-evaluation-observability-remediation-design.md`
  - `docs/superpowers/specs/2026-07-15-privacy-audience-contract-v2-remediation-design.md`
  - `docs/superpowers/plans/2026-07-16-live-replay-blocking-remediation.md`

本文将 `run_2d12b755578b` 的复盘结论及本轮补充讨论整理为可开发、可拆分、可测试的技术设计。本文最初在讨论阶段只记录设计；用户后续明确要求“按照该文档进行开发”，当前工作树已按本文统一推荐合同完成业务代码、测试和文档更新，不修改历史运行数据。

旧 7 月 17 日设计已经作为实现基线落地，不再是“完全待开发”状态。用户以“按照该文档进行开发”确认采用 TASK-00 的全部默认推荐：统一覆盖最后一狼、最后一神、人数优势等终局；保留合法猎人强制结算；终局不补遗言或警徽；终局 brief 折叠；Live 抢占普通 backlog；历史 Replay 忠实保留。本文据此正式取代旧设计中相冲突的终局条款。即时自爆、非终局遗言、隐私投影、回放/语音一致性和恢复幂等等其他已实现设计不受影响。

## 2. 总体结论

本局胜负计算本身正确：最后一名平民被放逐后，狼人达到屠边条件并获胜。问题在于系统没有在胜负已经客观确定时立即封口，仍继续执行遗言模型调用、警徽等附属流程，最后才发布 `game_completed`。

本轮确认两项直接需求：

1. 发送给大模型的自然语言状态不得暴露 `vote_exile` 这类内部状态码，应显示为准确的中文明文；内部存储、事件和回放协议仍保留稳定枚举。
2. 放逐最后一名平民已经产生胜方时应立即结束对局，不再生成没有博弈意义的遗言。

本文建议将第二项推广为统一工程不变量；该推广范围须由 TASK-00 确认：

> 完成仍可能改变胜负的强制结算后，一旦胜方确定，只允许提交最终状态、必要结果事件和 `game_completed`；不得再请求任何附属玩家动作或开启新的游戏阶段。

即使先完成最低合同，也不能只在 `_run_exile_last_words()` 增加一个脆弱特例。推荐方案让放逐、夜间死亡、首夜延迟死亡、猎人连锁、警长死亡和狼人自爆都经过同一个终局边界；所有模型入口再增加独立终局防线，避免同类缺口继续出现。

## 3. 本局证据与问题清单

### 3.1 终局仍继续运行

| 证据 | 观察结果 | 结论 |
| --- | --- | --- |
| 运行状态 | `run_2d12b755578b` 正常完成，约 17 分 18 秒，事件序号连续，共 1325 条 | 不是异常中断或事件丢失 |
| 决胜状态 | 第 1305 号事件后仅剩狼人祁野与猎人唐糖，最后一名平民卓然已被放逐 | 平民屠边已经成立，狼人胜负已客观确定 |
| 后续事件 | 第 1306～1324 号事件仍继续，第 1307～1321 号为完整 `exile_last_words` 模型链 | 对局已终局但玩家模型仍被调用 |
| 完成事件 | `game_completed` 到第 1325 号事件才发布 | 终局被附属流程延后 |
| 额外耗时 | 决胜状态到完成约 12.89 秒 | 用户看到的“对局还在继续”是真实执行和播放延迟 |

直接根因是“移除玩家”和“刷新 `state.winner`”分离：

- `GameEngine._remove_player()` 只更新存活列表，不计算胜负；
- `_require_non_terminal_player_action()` 只检查已经写入的 `state.winner`；
- 放逐路径在遗言、猎人和警徽处理后才刷新胜负；
- 因此存在“存活结构已经终局，但 `state.winner` 仍为空”的窗口，终局保护在窗口内无效。

### 3.2 其他已经终局仍可能继续的路径

| 优先级 | 路径 | 当前风险 |
| --- | --- | --- |
| P0 | 终局放逐 | 无条件请求遗言；最后一民、最后一神、最后一狼都可能触发 |
| P0 | 终局警长死亡 | 仍请求警徽移交/撕毁；模型失败甚至可能把已决胜对局标为失败 |
| P0 | 猎人枪击形成终局 | 枪击目标移除后仍可能处理目标警徽，再晚些判胜 |
| P0 | 首夜延迟死亡形成终局 | 当前可能先跑完整警长报名、发言、退水、投票和 PK，再公布已经终局的死亡 |
| P1 | 最后一狼以警长身份自爆 | 仍可能处理警徽、首爆/双爆计数和竞选延期状态 |
| P1 | 公共轮次摘要 | 当前在 winner 后仍作为独立阶段发布；虽然不调用玩家模型，但会延迟完成和播放 |
| P1 | Live 播放积压 | 客户端收到终局时仍可能继续播放未消费的普通 Cue、字幕和音频 |
| P1 | 历史 Replay | 会忠实重放旧数据中的终局后遗言、猎人和警徽事件，最后才显示完成 |

以下内容不是“无意义继续”，不能被粗暴删除：

- 同一夜已经形成的狼刀、毒杀等完整死亡批次；
- 死亡猎人依法触发且可能改变胜负的开枪；
- 白痴放逐免死判断；
- 最终存活状态、胜方、必要的放逐/死亡/枪击结果和终局法官提示；
- 运行、持久化和播放层完成必要的 ACK 与幂等收尾。

### 3.3 Prompt 暴露内部状态码

当前 `apps/api/app/werewolf/prompts_zh.py` 的硬状态渲染直接输出 `death_cause`，因此模型 Prompt 出现：

```text
你的出局原因：vote_exile。
```

这会把持久化协议泄漏到自然语言上下文，也降低模型对规则语义的理解。正确边界是：

- 引擎、数据库、事件、回放 payload 使用稳定代码；
- Prompt 展示层统一映射为中文；
- 未识别代码使用中文兜底，不把原始值发送给模型，并在内部记录告警。

### 3.4 事实可信等级丢失

本局中狼人南乔的遗言以 `category: "claim"` 记录，但后续 Prompt 将其扁平化到“公开事实记录”。女巫把玩家声明当成引擎确认事实，毒杀好人并把警徽交给实际狼人。

公开可见不等于客观真实。公开事实链路需要同时保留业务 `category` 和可信 `trust_class`，至少区分引擎确认事实、玩家声明和历史未分类记录。私人观察与模型策略笔记不属于 public facts，必须通过独立授权通道进入单个玩家 Prompt：

- 引擎确认事实；
- 玩家公开声明，可能撒谎；
- 无法分类的历史记录。
- 当前玩家合法可见的私人观察，仅走私人 Prompt 通道；
- 模型策略笔记/历史总结，仅走当前玩家记忆通道。

### 3.5 猎人及终局硬规则错误

存活猎人唐糖称“如果放逐错人，下一晚再开枪纠正”。该说法违反硬规则：猎人不能在存活状态下选择任意夜晚开枪，只能在合法死亡触发时决定是否开枪；放逐最后一民后也不存在下一夜。

Prompt 已包含基础规则仍未阻止错误，说明需要确定性校验，而不是继续堆提示词。违反硬规则的草稿不得公开、持久化或进入语音物化。

### 3.6 质量、时长和可观测性

| 类别 | 本局观察 | 影响 |
| --- | --- | --- |
| 质量误报 | 17 个 warning、24 个 code；`promises_ineligible_sheriff_vote` 两次误伤普通放逐语境 | 触发无收益重写 |
| 重写耗时 | 两次误报重写合计约 22.49 秒 | 延长对局但未改善内容 |
| 矛盾检测 | `role_term_contradiction` 只凭词面共现，未绑定主体和命题 | 噪声高、误导诊断 |
| 发言长度 | 29 条公开玩家发言约 29.71 分钟；13 条超过 60 秒，3 条超过 90 秒，最长约 141.5 秒/731 字 | 节奏严重失控 |
| 执行指标 | `request_count=136`，但离散动作和首 token 样本为 0，`game_duration_ms` 为空 | Admin 无法解释真实耗时 |
| 自爆审计 | 实际即时自爆行为正确，但日志降级到 `legacy`，缺少窗口和执行状态字段 | 无法可靠复盘接受/拒绝原因 |
| 静态语音时长 | `voice_b45c615e2991` 记录 45ms，实际约 4.4 秒 | 播放进度、时长指标和排障失真 |

## 4. 新旧合同拟修订

下表是本文推荐的统一目标，不表示未确认事项已经成为线上合同。最后一名平民终局无遗言为已确认最低要求；其余推广项在 TASK-00 勾选后才 supersede 对应旧设计。

| 旧设计条款 | 本文修订 | 保留内容 |
| --- | --- | --- |
| 7 月 17 日设计 §8.2/§8.3：放逐后固定执行遗言、技能、警徽、连锁，再判胜 | 放逐已经形成终局候选时，先完成可能改变胜负的强制结算；胜方确定后跳过遗言、警徽和附属阶段 | 普通非终局放逐保留既有遗言顺序；合法猎人和完整死亡批次仍需结算 |
| 7 月 17 日设计 §10.8：最后一狼仍先遗言再发布胜负 | 推荐统一为任何终局放逐都不再生成遗言；当前只确认最后一民场景 | 白痴免死、自爆、夜死和猎人带走仍不生成驱逐遗言 |
| 7 月 17 日设计 §8.4：任何提前结束白天均进入独立公共总结 | 终局摘要数据可折叠进最终状态/完成 payload，不再开启独立 summary 阶段 | 非终局轮次摘要继续保留 |
| 7 月 14 日 P0 设计 §9.1：警徽属于判胜前完整连锁 | 警徽不改变阵营胜负，终局后跳过 | 非终局警长死亡仍正常移交或撕毁 |
| 7 月 14 日 P0 设计 §9.6：`public_round_brief` 位于 `game_completed` 前 | 不得成为终局后的独立动作或播放阻塞 | 可作为同一次最终状态提交中的确定性字段 |

本文不推翻以下既有合同：

- 即时自爆窗口和过期草稿抑制；
- 同夜多死亡必须完整结算；
- 猎人合法开枪可能改变最终胜负；
- 白痴免死不会移出存活列表；
- 全部强制结算完成、稳定胜方确定后不得出现玩家模型事件；
- audience 隔离、语音来源、回放顺序和 checkpoint 幂等要求。

对其他上游文档的边界：P1 中“`game_completed` 唯一投影终局法官 Cue”的合同继续有效；Live/Replay blocking 方案中的 `sourceEventId`/`lastSourceEventId` 播放边界与逐 utterance ACK 继续有效，本文只提议增加终局抢占；Privacy Audience Contract v2 完全保留，任何事实分区都不得放宽 audience。本文不 supersede 这些合同。

## 5. 目标与非目标

### 5.1 目标

1. 建立跨放逐、夜死、延迟夜死、自爆和猎人的统一终局结算边界。
2. 消除“存活结构已终局但 winner 尚未刷新”的模型调用窗口。
3. 让模型只看到中文业务语义，不看到叙事上下文中的内部状态码。
4. 保留公开事实的来源、类别和可信等级，阻止玩家声明冒充客观事实。
5. 对猎人能力、终局后续轮次等硬规则做确定性校验。
6. 修复质量误报、发言超长和无效重写造成的耗时。
7. 让 Live、Replay、语音和 Admin 与新的终局合同一致。
8. 通过固定复现本局末局结构的集成夹具证明修复有效。

### 5.2 非目标

- 不改变阵营胜负条件或身份配置。
- 不把中文展示文案写回数据库替代稳定枚举。
- 不删除非终局遗言、合法猎人技能或同批死亡。
- 不重写模型供应商或 TTS 架构。
- 不在本任务中自动篡改历史对局事件。
- 不用延长超时掩盖质量重写和播放积压问题。

## 6. 核心不变量

以下为本文推荐的统一目标合同；最后一民场景已确认，其余角色/胜负条件按 TASK-00 的最终选择收敛后生效。

### 6.1 终局定义

需要区分三个状态：

| 状态 | 定义 | 允许行为 |
| --- | --- | --- |
| `non_terminal` | 当前存活结构没有胜方 | 正常规则阶段和玩家行动 |
| `terminal_candidate` | 当前存活结构出现胜方，但同一结算批次仍有可能改变胜负的强制技能/死亡 | 只允许完成该批次的强制结算 |
| `terminal_committed` | 强制结算队列为空、存活结构稳定、winner 已提交 | 只允许最终状态、必要结果、完成和基础设施 ACK |

不能把 `state.winner is not None` 作为唯一真相。终局判断必须同时使用当前存活结构和强制结算队列。

### 6.2 强制结算与附属流程

| 动作 | 是否可能改变胜负 | `terminal_candidate` 时 | `terminal_committed` 后 |
| --- | --- | --- | --- |
| 同批狼刀/毒杀/规则死亡落地 | 是 | 必须完成 | 禁止新增 |
| 合法死亡猎人开枪 | 是 | 必须完成 | 禁止新增 |
| 白痴免死判断 | 是，决定是否真正死亡 | 必须先完成 | 不适用 |
| 最终放逐/死亡/枪击结果事件 | 已发生事实 | 必须提交 | 可幂等补齐，不得重复 |
| winner 与最终存活状态 | 最终结果 | 队列清空后提交 | 只读 |
| `game_completed`（终局法官 Cue/语音的唯一源事件） | 完成通知 | winner 提交后发布 | 可幂等重放/ACK |
| 驱逐遗言 | 否 | 仅最终确认非终局时允许 | 禁止 |
| 警徽移交/撕毁 | 否 | 仅最终确认非终局时允许 | 禁止 |
| 警长报名、发言、退水、投票、PK | 否 | 禁止 | 禁止 |
| 独立公共 summary 阶段 | 否 | 禁止 | 禁止 |
| 私有轮次记忆 | 否 | 禁止 | 禁止 |
| 下一轮/下一夜 | 否 | 禁止 | 禁止 |

### 6.3 模型封口

从 `terminal_committed` 开始：

- 玩家 provider 调用数必须为 0；
- 不得创建 `action_requested`、模型流、遗言、警徽或 summary action；
- 不得发布玩家语音任务；
- 不得因警徽、总结或普通播放失败把已完成对局改为 failed；
- runner 必须尽快、幂等地发布 `game_completed`。

## 7. 统一终局结算状态机

### 7.1 推荐顺序

为降低规则回归，普通非终局放逐保留既有“遗言 → 猎人 → 警徽”顺序；只在主要结果已经形成 `terminal_candidate` 时切换到终局结算分支：

```text
应用主要结果（放逐、自爆或死亡批次）
→ 白痴等“是否真正死亡”判断
→ 落地当前批次全部规则死亡
→ 计算 terminal_candidate
   ├─ 否：按现有非终局规则执行遗言及后续；每次死亡技能后重新检查终局
   └─ 是：只结算仍可能改变胜负的死亡触发技能（当前为猎人）
            → 重新计算稳定存活结构
            → 提交 winner
            → 若终局：发布必要结果与 game_completed，立即返回
            → 若终局被解除：恢复其他合法非终局 aftermath，但不事后补遗言
```

这里的有意顺序修订只影响“主要结果已经形成终局候选，同时仍有猎人等强制结算”的边界。此时遗言不改变胜负，猎人开枪可能改变胜负，因此先完成猎人再确认胜方。本文推荐一旦进入该分支就永久跳过本次驱逐遗言：即使自定义规则使终局候选在开枪后解除，也不出现“开枪后补遗言”的倒序展示；其余非终局 aftermath 可以恢复。该语义必须由 TASK-00 最终确认。

### 7.2 引擎接口建议

不要求采用以下类名，但实现必须表达同等边界：

```python
class TerminalAssessment:
    winner: str | None
    pending_outcome_settlements: tuple[str, ...]

    @property
    def committed(self) -> bool:
        return self.winner is not None and not self.pending_outcome_settlements
```

建议将当前分散的处理收敛为显式分支：

```python
apply_primary_outcome()
candidate = assess_terminal_candidate()

if candidate:
    settle_outcome_affecting_chain()
    if commit_winner_if_stable():
        finalize_game_once()
        return

run_non_terminal_aftermath_with_terminal_checkpoints()
```

`run_non_terminal_aftermath_with_terminal_checkpoints()` 才能包含遗言、警徽和轮次延续；其中任何死亡技能改变存活结构后都必须先重新判胜，再决定能否继续附属动作。禁止在多个调用点手写“先做一些附属动作、最后再看 winner”。

### 7.3 各路径要求

#### 普通放逐

1. 锁票并发布放逐结果。
2. 处理白痴免死；免死则不移除、不遗言、不误判终局。
3. 真正死亡后立即计算终局候选。
4. 若尚未形成终局候选，保留既有非终局遗言顺序；猎人或其他死亡技能执行后再次检查终局，再决定是否允许警徽和后续阶段。
5. 若已经形成终局候选，只先结算合法猎人及其连锁死亡，再基于稳定存活结构判胜。
6. 最终终局则直接完成；只有胜方不再成立时，才恢复尚未执行的其他合法非终局流程，不事后补本次驱逐遗言。

本局三人残局必须得到：

```text
卓然被放逐
→ active_players = [祁野（狼人）, 唐糖（猎人）]
→ wolves win
→ game_completed
```

不得再出现 `exile_last_words`、`sheriff_badge`、私有总结或下一夜。

#### 夜间死亡

- 先完整应用同夜狼刀、毒杀及规则定义的同时死亡；
- 再处理死亡猎人的合法开枪；
- 存活列表稳定后判胜；
- 终局后跳过死者警徽和白天普通阶段；
- 不允许在第一名死者移除后就提前截断同批其他死亡。

#### 首夜延迟死亡

保留正常非终局玩法的“警长竞选与首夜死亡公布”顺序，但增加必然终局例外：

1. 在启动完整警长竞选前，对待公布死亡批次及所有合法猎人结果做只读终局投影；
2. 只有“猎人开枪、不开枪及所有合法目标分支都必然终局”时，才提前落地完整死亡和猎人链；
3. 必然终局时跳过报名、发言、退水、投票和 PK；
4. 任一合法分支可能继续对局时维持既定“先警选、后公布死亡”顺序，不提前落地或公布死亡。

终局投影不能只看第一名待死亡玩家，也不能忽略猎人触发或“不发动技能”选项。这样不需要在死亡已经公开后尝试恢复不可逆的警长竞选顺序。

#### 狼人自爆

- 保留已实现的即时抢占和旧草稿抑制；
- 自爆者移除后先判断是否最后一狼；
- 若终局，跳过警徽、首爆/双爆计数、竞选延期和公共总结；
- 非终局时才继续当前规则允许的竞选状态和警徽结算。

#### 猎人连锁

- 猎人是当前唯一明确允许在 `terminal_candidate` 状态继续请求的玩家动作；
- 该权限必须由结算上下文显式授予，不能成为任意 action 的宽泛 bypass；
- 猎人目标死亡后重新计算待结算队列和胜方；
- 最终胜方确定后，枪击目标的警徽也不再处理。

### 7.4 winner 与事件提交

- winner 必须在稳定存活结构形成的同一引擎事务/检查点内写入；
- 最终状态事件先于 `game_completed`，两者都需幂等；
- 允许在最终状态内携带确定性轮次摘要数据，但不得为此启动新的 phase、玩家模型或语音长链；
- runner 仍是唯一发布 `game_completed` 的责任方，避免引擎与 runner 双发；
- `game_completed` 自身是终局法官 Cue 和终局语音的唯一源事件，不再额外发布一条独立终局 Cue；
- 若 runner 恢复时发现 winner 已提交但 completion 未发布，应只补齐完成，不恢复被取消的附属动作。

推荐的新局公开顺序：

```text
decisive result state/event
→ optional mandatory hunter result state/event
→ winner/final state
→ game_completed（由该事件唯一投影终局法官 Cue/语音）
```

从最终胜方确定点到 `game_completed` 之间不得出现玩家模型事件。

## 8. 全局终局动作防线

### 8.1 防线位置

至少在以下边界执行统一检查：

- 离散玩家 action 提交 provider 前；
- 流式公开发言启动前；
- 质量重写启动前；
- 遗言、警徽和私人记忆入口；
- 恢复后重新调度 pending action 前；
- 语音任务从玩家 action 物化前。

### 8.2 判定规则

```python
if state.winner is not None:
    reject_non_terminal_action()

projected_winner = get_winner(active_players)
if projected_winner and not context.is_outcome_affecting_settlement:
    reject_non_terminal_action()
```

实际实现应返回有界原因码，例如：

- `terminal_committed`
- `terminal_candidate_non_settlement_action`
- `stale_action_after_terminal`

原因码用于内部日志和指标；面向模型或用户的自然语言使用中文。

### 8.3 取消与失败语义

- 终局使 pending 普通 action 失效时，记录为 `canceled_terminal`，不是 completed 或 failed；
- 已有草稿不得发布到 public event、action log 可见内容或语音；
- 终局后的附属 action 失败不得反向覆盖已提交 winner；
- 所有取消必须完成内部终态记账和客户端安全 ACK，避免恢复后复活。

## 9. Prompt 中文语义边界

### 9.1 映射原则

建立集中式 Prompt 展示映射，不在模板中散落条件判断。首批死亡原因映射：

| 内部枚举 | 发送给模型的中文 |
| --- | --- |
| `vote_exile` | 被白天投票放逐 |
| `werewolf_attack` | 被狼人夜间袭击 |
| `witch_poison` | 被女巫使用毒药 |
| `hunter_shot` | 被猎人开枪带走 |
| `werewolf_self_explosion` | 因狼人自爆出局 |

自然语言状态区遇到未知枚举时：

- 自然语言状态区仅显示“因未识别的规则原因出局”或同等明确中文；
- 不拼接原始枚举，不允许 snake_case 透传；
- 内部记录 `unknown_prompt_state_code` 告警和有界字段名；
- 不把玩家原文、姓名等高基数内容放入指标标签。

### 9.2 适用边界

- 自然语言硬状态、公开事实和策略上下文必须使用中文业务语义；
- 数据库、事件、Replay DTO 保留机器枚举，避免兼容性迁移；
- 如果模型输出 JSON Schema 必须返回协议枚举，可以保留 enum 值，但字段说明和每个选项必须同时给出中文解释；
- 对 `death_cause` 之外的 phase、status、reason、current_action 做一次 inventory，清理所有无必要的内部码泄漏；机器输出 Schema 使用显式 allowlist。

### 9.3 验收

- 已知原因在自然语言状态/事实区只出现中文，不出现上述原始枚举；
- 未知原因不泄漏原值并产生内部告警；
- phase/status/reason/current_action 使用参数化 inventory 测试或受控 allowlist；
- 机器输出 JSON Schema 可以出现协议 enum，但每个值都附中文解释，测试不得把该允许区误判为泄漏；
- Replay 和持久化仍可读写原枚举；
- 中文映射在 Prompt、Admin 展示和测试 fixture 中使用同一来源或同一受控合同。

## 10. 公开事实可信度投影

### 10.1 公开事实的两个维度

不得用新的可信等级覆盖现有业务类别。每条公开事实保留两个正交维度：

| 维度 | 示例 | 用途 |
| --- | --- | --- |
| `category` | `death`、`vote`、`claim`、`speech`、`sheriff_result` | 表示发生了什么业务事件，保持现有兼容合同 |
| `trust_class` | `engine_fact`、`player_claim`、`legacy_unclassified` | 表示该记录能否当作客观事实 |

Prompt 分区规则：

| `trust_class` | 含义 | Prompt 分区 |
| --- | --- | --- |
| `engine_fact` | 引擎确认的死亡、票型、警徽、技能结果 | 引擎确认事实 |
| `player_claim` | 玩家公开发言、遗言、自称身份和判断 | 玩家声明，可能撒谎 |
| `legacy_unclassified` | 历史字符串无法可靠分类 | 未分类公开记录，非引擎确认 |

`private_observation` 和 `strategy_note` 不是 public fact 的 category 或 trust class：

- 私人观察从角色授权状态直接进入“你的私人信息”；
- 策略笔记从当前玩家私有记忆进入“策略笔记，不是事实”；
- 两者绝不能进入 `state.public_facts`、`compressed_public_facts`、公开 DTO 或其他玩家 Prompt。

### 10.2 全链路要求

- `compressed_public_facts` 不得压扁业务类别、可信等级、来源事件、轮次和主体；
- 座位号/玩家名映射不得丢失原 `category` 或 `trust_class`；
- Prompt 按可信等级分区渲染，而非统一标题“公开事实记录”；
- 事实压缩只能合并 `category + trust_class` 均兼容的记录，不能把 claim 升级为 fact；
- 历史无分类字符串 fail closed 到 `legacy_unclassified`；
- audience 过滤先于分类渲染，不能因为分区而泄漏私密事实。
- Prompt compositor 分别接收 public facts、授权私人观察和私有策略记忆，不用一个数组混装三种来源。

### 10.3 验收示例

```text
引擎确认事实：
- 第 3 轮，5 号被放逐。

玩家声明（可能撒谎）：
- 5 号遗言声称 8 号是狼人。

你的私人信息：
- 你昨夜查验 8 号，结果为好人。
```

后续模型不得把第二条当成与第一、第三条同等级的客观事实。

## 11. 终局与猎人确定性门禁

### 11.1 硬规则

- 存活猎人不能主动选择“下一夜开枪”；
- 只有合法死亡触发中的猎人才有一次开枪决策；
- 已经因放逐最后一民确定终局时不存在下一夜；
- 对局终局后任何“之后我再……”式行动承诺都不得被当作可执行计划。

### 11.2 校验流程

1. Prompt 提供当前存活结构、当前阶段、猎人是否拥有合法死亡触发及“本次错误放逐是否立即终局”的中文硬状态。
2. action quality 在发布前做确定性校验，输出有界硬错误码。
3. 首稿违反硬规则时最多重写一次，并明确反馈具体约束。
4. 第二稿仍违反硬规则时使用安全短发言或沉默 fallback，不发布错误稿。
5. 拒绝稿不得进入 public event、action log 可见内容、Replay 或语音任务。

### 11.3 建议错误码

- `hunter_claims_voluntary_future_shot`
- `claims_future_round_after_terminal`
- `claims_illegal_post_death_action`
- `hard_rule_retry_exhausted`

错误码只用于内部诊断；用户和模型看到中文解释。

## 12. 质量校验与发言长度预算

### 12.1 误报修复

- `promises_ineligible_sheriff_vote` 只在明确的警长竞选投票上下文执行；普通放逐票、警长 1.5 票描述不得触发。
- `role_term_contradiction` 必须解析主体、目标和命题；不同目标分别被称为查杀/好人不构成自相矛盾。
- 硬事实错误与风格 warning 分离；硬错误 fail closed，风格告警允许 fail open。
- 同一错误重写后仍存在时不继续循环调用；最多一次重写，随后确定性 fallback。

### 12.2 长度预算

沿用已评审的初始工程值，并将其变成发布前硬门禁：

| 动作 | 最大汉字数 | 预计语音上限 |
| --- | ---: | ---: |
| 警上发言 | 180 | 35 秒 |
| 普通白天发言 | 220 | 40 秒 |
| 警长/放逐 PK 发言 | 180 | 35 秒 |
| 非终局驱逐遗言 | 150 | 30 秒 |
| 狼队私聊 message | 60 | 不公开 |

超限流程：

1. 带目标长度反馈重写一次；
2. 仍超限时按完整句边界截断，或使用安全短发言 fallback；
3. 在文本被接受后才创建 TTS，不在音频生成后粗暴截音；
4. 记录 `speech_length_retry_exhausted`，但不记录完整原文到指标标签。

### 12.3 质量指标

至少区分：

- validator 命中次数；
- 首稿误报/人工 fixture 复核；
- 重写成功；
- 重写仍失败；
- 确定性 fallback；
- 因终局取消；
- 重写额外耗时。

## 13. Live、Replay 与语音终局行为

### 13.1 新对局的源头合同

引擎是唯一源头。新对局在终局边界后不生成遗言、警徽、summary 玩家动作或对应语音任务；Replay 和 Live 不应靠展示层猜测并过滤正常源数据。

### 13.2 Live 终局抢占

当前 `useLiveDirector` 的测试明确固定“收到 terminal 不跳过 backlog”的旧行为。本文推荐修订为：

- 收到终局时丢弃尚未播放的普通发言、遗言、警徽和 summary Cue；
- 正在播放的非必要普通 Cue 可取消；对应语音必须按 `utterance_id` 发送一次 `voice_played` ACK；
- 必须保留决定性放逐/死亡/猎人结果，以及由 `game_completed` 投影的唯一终局法官 Cue；
- 终局后迟到的 chunk、subtitle、voice_end 只能被忽略或安全 ACK，不得重新激活流程；
- TASK-00 若确认 Live 终局抢占，则新生成的每条 `game_completed` payload 必须写入 `terminal_keep_from_event_id`：它表示“终局必须保留的第一条 source event，包含该事件”；`game_completed` 自身的 event id 是保留区间上界；新引擎保证该闭区间内只含决定性结果、强制结算、最终状态和完成事件。
- director 丢弃 source event id 小于 `terminal_keep_from_event_id` 的未播放普通 Cue；utterance 的 `[sourceEventId, lastSourceEventId]` 与保留区间相交时宁可保留，不能误删决定性结果。
- 语音 WebSocket 当前按 utterance 串行等待 ACK，不支持范围水位 ACK。被抢占或迟到的 utterance 必须逐条发送 `voice_played { utterance_id }`，服务端收到后才能继续发送下一条；不得仅移动本地 cursor。

### 13.3 Replay 历史兼容

默认策略：

- 新对局由引擎保证不产生非法终局后事件；
- 历史 Replay 忠实保留当时真实存储的事件，不批量改写数据库；
- 可在 UI 标注“按历史版本规则生成”；
- 若产品决定历史回放也隐藏终局后附属动作，应作为显式投影版本实现并保留原始 payload，不能静默篡改。

### 13.4 语音

- 决胜放逐只生成必要结果；终局法官语音仅由 `game_completed` 物化一次，不创建独立重复 Cue，也不创建遗言、警徽或 summary 玩家语音；
- Player Public 与 God View 继续遵守 audience 投影；
- 静态音频 `duration_ms` 取媒体元数据或字幕最后 `end_ms`，不得取 WebSocket 发送墙钟耗时；
- 发送值、持久化值和 Replay 值保持一致，且不得小于最后一条字幕结束时间。

## 14. 可观测性与审计

### 14.1 模型请求生命周期

provider attempt 与逻辑 action 是两层生命周期，不能把 action fallback 当成一次模型请求的终态。

每个实际 provider attempt 必须恰有一个结果：

- `valid_response`
- `invalid_response`
- `timed_out`
- `canceled`
- `transport_failed`

并满足：

```text
attempt_count
= valid_response + invalid_response + timed_out + canceled + transport_failed
```

每个逻辑 action 必须恰有一个最终结果：

- `completed`
- `fallback`
- `canceled`
- `failed`

并独立满足：

```text
action_count = completed + fallback + canceled + failed
```

两层通过稳定 `action_id + attempt_id` 关联。一个 action 可以因非法 JSON/非法候选产生多个 attempt，也可以在 provider 返回有效响应后因硬规则校验失败最终进入 fallback；两层指标不得共用一个等式。

流式动作应记录首 token；没有样本时显示 unavailable，不能用 0 冒充健康值。完整对局必须能稳定计算 `game_duration_ms`，并分别统计离散动作、公开发言、私有总结和后台自爆判断。

### 14.2 预算

- 确认 execution budget 在真实 provider 路径启用；
- 超预算 provider attempt 必须记录为 `timed_out`；其逻辑 action 再独立进入 fallback/canceled/failed 之一；
- `timeout_count=0` 只有在预算已启用且确实无超时时才有意义；
- 终局取消与超时分开统计。

### 14.3 自爆 provenance

接受和拒绝的自爆决策均记录：

- 当前 `decision_schema`
- `window_id`
- `execution_status`
- `duration_ms`
- 规范化后的有限 `benefit_type`

合法同义值应先归一化，不应因为枚举文案差异降级到 `legacy`。后台私密判断可不公开，但不能被 `NullEventSink` 吞掉全部计时和终态。

### 14.4 指标隐私与基数

指标标签只允许有限 action/result/reason 枚举，不包含模型原文、玩家名、任意异常文本或 Prompt。详细上下文进入权限受控的结构化日志。

## 15. API、持久化、恢复与兼容

### 15.1 无需变更的合同

- `DeathEvent.cause` 等内部枚举继续稳定持久化；
- 现有 audience 和隐私 DTO 不因中文 Prompt 映射改变；
- 历史 replay payload 不做破坏性迁移；
- 非终局遗言事件格式保持兼容。

### 15.2 可能需要扩展的合同

- TASK-00 若启用 Live 终局抢占，新局 `game_completed` 必写 `terminal_keep_from_event_id`；该值是必须保留区间的首个 source event id，完成事件 id 是区间上界；旧 payload 继续可选读取，缺失时保持历史非抢占行为；
- 若事实类别当前在压缩 DTO 中缺失，保留业务 `category` 并增加受控 `trust_class`、`source_event_id` 和 `round_no`；
- action 终态增加 `canceled_terminal` 或映射到现有 canceled reason；
- 自爆审计补齐窗口、执行状态和耗时字段。

所有新增字段优先后向兼容、可选读取、严格写入；共享客户端 parser 与 API 测试必须同步。

### 15.3 Checkpoint 与恢复

- `terminal_candidate` 不作为可漂移布尔值持久化；每次从 checkpoint 中的 `active_players` 和未完成 settlement 重新派生；
- outcome-affecting settlement 必须在内部 checkpoint 保存可恢复游标，最低结构如下：

```text
settlement_schema_version: "settlement_v1"
primary_outcome_action_id: string
primary_presentation?:
  presentation_id: "pp_<opaque hash>"
  kind: "exile_result" | "night_result" | "self_explosion_result"
  phase: string
  actor: string | null
  action: string
  payload: immutable public result snapshot
settlement_cursor: integer
settlements[]:
  settlement_id: string
  kind: "death_batch" | "hunter_shot"
  actor: string | null
  status: "pending" | "choice_accepted" | "applied"
  accepted_choice: internal value | null
  presentation?:
    presentation_id: "hp_<opaque hash>"
    kind: "hunter_shot_result"
    hunter_shot_status: "shot" | "skipped"
    hunter_shot: string | null
continuation:
  kind: "none" | "day_exile_aftermath" | "night_death_aftermath"
  status: "pending" | "applied"
  skip_exile_last_words: boolean
  transfer_sheriff_badge: boolean
canceled_action_ids[]: string
```

- settlement 游标、`settlement_id` 和内部 action identity 只进入 checkpoint；公开事件只携带不透明 `presentation_id` 及 shot/skipped 结果字段。内部 identity 与公开语义 identity 在恢复前后都保持稳定；
- winner 提交和终局 action 取消状态进入同一 checkpoint 边界；
- 恢复发现 winner 时不得重新调度遗言、警徽、总结或下一轮；
- 恢复重新派生出 `terminal_candidate` 时，只能从 `settlement_cursor` 继续未完成的 outcome-affecting settlement；
- 接受过的猎人目标使用稳定 action identity 去重；猎人公开结果使用稳定 `presentation_id` 标识同一语义，允许恢复 run 拥有自己的 transport occurrence；
- 决定性放逐、夜死或自爆同样使用稳定 `pp_*` 展示标识；child run 必须先恢复主结果，再恢复 `hp_*` 猎人结果，最后发布不带展示标识的 folded state；
- `pp_*` 信封冻结在猎人结算前，只包含原始死亡、当时存活名单及截至主结果的公开 outcome；不得从已被猎人枪击修改的最终 `RoundState` 重新拼装；
- 若猎人结算使原终局候选失效，恢复按 `continuation` 完成警徽和当前轮后续；已经因候选终局而跳过的放逐遗言不得事后补生成；
- 候选解除后继续到下一轮时，checkpoint 必须把恢复前完整日志与恢复后的警徽/摘要变更一起晋升为 durable prefix；再次崩溃与恢复不得丢轮或重复拼接；
- completion 缺失时只补 `game_completed`，不回滚 winner。

至少覆盖五个独立崩溃点：决定性结果已应用但 winner 尚未写入、winner 已写入但 `game_completed` 尚未发布、猎人选择已接受但枪击结果尚未应用、猎人 `applied` checkpoint 后首次发布前，以及猎人结果发布后 winner 提交前。恢复不得重复请求模型；猎人结果可在 child run 以同一 `presentation_id` 重新投递，但折叠 Replay、Live 导播和语音不得重复呈现。

## 16. 预期代码改动范围

| 领域 | 主要文件 | 修改方向 |
| --- | --- | --- |
| 终局结算 | `apps/api/app/werewolf/engine.py` | 统一死亡链、winner 提交、非终局 aftermath 和全局动作 guard |
| 终局回归 | `apps/api/tests/test_werewolf_runner.py`、`test_run_05aa0b0f2b92_p0_regression.py` | 反转旧终局遗言断言，补本局三人残局及各路径矩阵 |
| Prompt | `apps/api/app/werewolf/prompts_zh.py` | 中文映射、未知兜底、终局硬状态 |
| 公开事实 | `apps/api/app/werewolf/public_facts.py` | 保留业务 category、trust class、来源和轮次；私人信息不进入该管道 |
| Prompt/事实测试 | `apps/api/tests/test_werewolf_lm.py`、`test_werewolf_public_facts.py` | 不泄漏状态码、claim 不升级为事实 |
| 质量校验 | `apps/api/app/werewolf/action_quality.py`、`debate_realism.py` | 猎人硬规则、阶段化投票校验、主体化矛盾检测 |
| 预算与遥测 | `apps/api/app/werewolf/execution_budget.py`、`execution_telemetry.py`、`evaluation_bundle.py` | attempt 终态、首 token、游戏时长、终局取消、重写耗时 |
| Replay | `apps/api/app/werewolf/replay_playback.py`、`apps/api/tests/test_replay_playback.py` | 新局事件顺序与历史兼容策略 |
| Live | `packages/game-client/src/live/liveDirector.ts` 及 hook 测试 | 终局抢占、逐 utterance ACK；启用抢占时新局必写 `terminal_keep_from_event_id` |
| Mobile Web | `apps/mobile-web/src/pages/LivePage.tsx` 及测试 | 终局展示、字幕和音频队列清理 |
| 语音 | `apps/api/app/werewolf/voice_stream.py`、`voice_materializer.py`、`voice_store.py` | 终局后任务约束、静态音频时长来源 |
| Admin | `apps/api/app/admin/p2_diagnostics.py` 及测试 | 指标可用性、质量重写和终局取消诊断 |
| 恢复 | `apps/api/app/werewolf/checkpoint.py`、`models.py` 及 resume 测试 | `settlement_v1` 游标、winner/取消/强制结算幂等恢复 |

实际开发前先以 `rg` 确认最新符号位置；文件表是影响范围，不是要求无条件修改每个文件。

## 17. 开发任务与 PR 拆分

### TASK-00：确认规则决策门槛（阻断统一 P0 实现）

- [x] 放逐最后一名平民已经产生狼人胜方时，不生成驱逐遗言并立即完成对局。
- [x] 确认统一规则覆盖最后一狼、最后一神和人数优势终局，而不只覆盖最后一民。
- [x] 确认死亡猎人在潜在终局中仍先完成合法开枪。
- [x] 确认放逐已形成终局候选时，顺序改为“强制猎人结算 → 判胜 → 终局则无遗言”，并覆盖猎人开枪、不发动和所有合法目标。
- [x] 确认一旦进入终局候选强制结算分支，即使自定义规则使候选终局解除，也不在开枪后倒序补遗言。
- [x] 确认终局 public brief 折叠进最终状态，不作为独立阶段。
- [x] 确认 Live 收到终局时抢占普通 backlog。
- [x] 确认历史 Replay 默认忠实保留旧事件。

### PR-1 / TASK-01：先写终局 RED 回归

- [x] 建立“狼警长 + 最后一民 + 存活猎人，最后一民被放逐”的固定夹具。
- [x] 断言该夹具在无待结算猎人触发时，从稳定胜方确定点起没有玩家模型调用、遗言、警徽、总结或下一轮。
- [x] 补最后一狼、最后一神、`wolves_gte_others` 人数优势、终局警长、猎人开枪/不发动、同夜多死亡、白痴免死和首夜延迟死亡用例。
- [x] 反转 `test_terminal_exile_skips_private_round_memories`、`test_decisive_state_precedes_game_completed_without_model_events_between` 的旧终局断言。
- [x] 将 `test_exile_last_words_run_before_hunter_and_badge_settlement` 明确限定为非终局合同。
- [x] 反转 `test_run_05aa0b0f2b92_p0_fixture_full_path` 中终局遗言和 `provider.calls == 1` 的旧 fixture 断言。

验收：新测试在旧实现上以预期原因失败，且非终局遗言测试继续通过。

### PR-1 / TASK-02：统一引擎终局结算

- [x] 拆分 outcome-affecting settlement 与 non-terminal aftermath。
- [x] 在稳定存活结构形成后立即提交 winner。
- [x] 终局跳过遗言、警徽、竞选状态、公共 summary phase、私有记忆和下一轮。
- [x] 首夜延迟死亡增加终局投影与例外路径。
- [x] 最后一狼自爆跳过无意义警徽和竞选状态。

### PR-1 / TASK-03：全局动作防线与恢复

- [x] provider 前同时检查持久化 winner 和当前存活结构。
- [x] 仅允许显式的 outcome-affecting settlement 穿过候选终局窗口。
- [x] pending action 以 `canceled_terminal` 结束并抑制草稿。
- [x] 按 `settlement_v1` checkpoint 游标恢复强制结算，不复活终局后动作，只幂等补完成。

### PR-2 / TASK-04：Prompt 中文语义投影

- [x] 建立集中式死亡原因中文映射。
- [x] 未知枚举中文兜底并记录内部告警。
- [x] inventory phase/status/reason/current_action 等硬状态内部码，以参数化测试或 allowlist 清理自然语言 Prompt 泄漏。
- [x] 保持数据库、事件和 Replay 枚举不变。

### PR-2 / TASK-05：公开事实可信等级

- [x] 在公开事实压缩、world state 和 Prompt 全链路同时保留业务 `category` 与 `trust_class`。
- [x] Prompt compositor 通过独立通道展示引擎事实、玩家声明、授权私人信息和私有策略笔记。
- [x] 保证私人观察/策略笔记不进入 `state.public_facts`、公开 DTO 或其他玩家 Prompt。
- [x] 历史未知记录按非事实 fail closed。
- [x] 验证 audience 过滤没有回归。

### PR-2 / TASK-06：猎人和终局硬规则门禁

- [x] 注入明确的猎人合法触发与终局后无下一轮硬状态。
- [x] 增加确定性错误码和最多一次重写。
- [x] 重试耗尽走安全 fallback，拒绝稿不进入事件、存储和语音。

### PR-3 / TASK-07：质量误报和发言时长

- [x] 将警长投票资格校验绑定明确阶段。
- [x] 将角色术语矛盾绑定主体、目标和命题。
- [x] 落地 180/220/180/150/60 汉字预算及完整句 fallback。
- [x] 记录重写收益、耗尽和额外耗时。

### PR-4 / TASK-08：Live、Replay 与语音

- [x] 修订 Live terminal/backlog 测试和队列策略。
- [x] 保留决定性结果；终局 Cue 只由 `game_completed` 投影一次，清理普通积压和迟到数据。
- [x] TASK-00 启用抢占后，新局必写 `terminal_keep_from_event_id`，同步实现闭区间保留语义、旧 payload fallback 和逐 utterance `voice_played` ACK。
- [x] 固定新局 Replay 无终局附属动作、非终局遗言完整、历史 payload 策略明确。
- [x] 修复静态语音 `duration_ms` 来源。
- [x] 验证 Player Public 与 God View audience 不串线。

### PR-5 / TASK-09：遥测、预算和自爆审计

- [x] 分别实现 provider attempt 与 logical action 的终态和计数守恒，并用稳定 `action_id + request_id`（request 即 provider attempt identity）关联。
- [x] 补离散动作、首 token、游戏时长、终局取消和后台自爆样本。
- [x] 验证 action budget 真正在执行路径生效。
- [x] 补齐自爆 `decision_schema/window_id/execution_status/duration_ms`。
- [x] 更新 Admin P2 诊断和有界指标。

### TASK-10：全链路验收与文档收口

- [x] 运行目标测试、API 全量测试、共享客户端和 Mobile Web 验证。
- [x] 用固定三人残局同时检查引擎事件、Replay payload、语音任务和 Live 抢占。
- [x] 更新旧 7 月 17 日文档状态，并链接本文的 supersede 条款。
- [x] 记录灰度指标、兼容策略和回滚开关。

## 18. 测试矩阵

### 18.1 终局边界

| ID | 场景 | 验收标准 |
| --- | --- | --- |
| T-01 | 狼人、最后一民、存活猎人三人局放逐最后一民 | 立即狼人胜利；无遗言、警徽、summary、私有记忆和后续模型请求 |
| T-02A | 放逐可开枪猎人后已形成终局候选，猎人开枪 | 只有带合法 settlement context 的 `hunter_shoot` 可穿过 guard；开枪后判最终胜者，终局无遗言/警徽/总结 |
| T-02B | 同一场景猎人不发动 | 记录合法跳过后判最终胜者；不因未开枪恢复遗言 |
| T-03 | 非终局普通放逐 | 遗言和合法非终局结算仍完整 |
| T-04 | 终局死亡者或猎人目标是警长 | 不请求 `sheriff_badge`；警徽失败不能破坏已决胜对局 |
| T-05 | 最后一狼自爆 | 立即好人胜利；无警徽、竞选状态、总结和后续玩家动作 |
| T-06 | 首夜延迟死亡在所有合法猎人分支下都必然终局 | 完成同批死亡/猎人后终局；不启动警长竞选；任一分支可继续时维持旧顺序 |
| T-07 | 同夜狼刀、毒杀、猎人连锁 | 完整批次后判胜，不在第一名死亡后截断 |
| T-08 | 白痴放逐翻牌免死 | 仍存活、不误判终局、不生成遗言，流程继续 |
| T-09 | `state.winner` 未刷新但存活结构已终局 | 普通 provider 调用数为 0 |
| T-10 | 全部强制结算完成、稳定胜方确定点到 `game_completed` | 只有最终状态和完成；无玩家 action/model/遗言/警徽/summary 事件 |
| T-11 | `wolves_gte_others` 自定义人数优势终局 | 按 TASK-00 最终合同封口，不只覆盖经典屠边 |
| T-12 | 终局跳过独立 summary phase | 最终状态仍包含确定性本轮公开摘要数据，Replay 不丢最后一轮结果 |

需要反转的旧测试合同：

- `test_terminal_exile_skips_private_round_memories`：无强制技能场景的 `provider.calls` 由 `>= 1` 改为 `0`。
- `test_decisive_state_precedes_game_completed_without_model_events_between`：改为 `model_events == []`。
- `test_exile_last_words_run_before_hunter_and_badge_settlement`：只保留为非终局合同，另测猎人导致终局后无遗言。
- `test_run_05aa0b0f2b92_p0_fixture_full_path`：反转终局遗言和 `provider.calls == 1` 断言。

### 18.2 Prompt、事实和猎人

| ID | 场景 | 验收标准 |
| --- | --- | --- |
| P-01 | 已知 `death_cause` | 自然语言状态/事实区只有中文，不出现内部枚举；JSON Schema 允许值不计为泄漏 |
| P-02 | 未知 `death_cause` | 中文兜底、不泄漏原值、有内部告警 |
| P-03 | 内部持久化与回放 | cause 枚举继续稳定读写 |
| P-04 | phase/status/reason/current_action inventory | 参数化扫描或受控 allowlist；自然语言区没有未映射机器码 |
| F-01 | claim/death/vote 经压缩与座位映射 | 业务 `category`、`trust_class`、来源和轮次均不丢失 |
| F-02 | 狼人遗言进入后续 Prompt | 归入“玩家声明/可能撒谎”，不在引擎事实区 |
| F-03 | 客观死亡、票型、警徽 | 归入引擎确认事实，并与私人信息分区 |
| F-04 | 历史无分类字符串 | 标记为非引擎确认，不默认升级 |
| F-05 | 私人观察和策略记忆 | 不进入 public facts/公开 DTO/其他玩家 Prompt，只经授权独立通道合成 |
| H-01 | 存活猎人称下一夜主动开枪 | 硬错误；草稿不公开、不持久化、不生成语音 |
| H-02 | 最后一民可能被放逐 | Prompt 明示会立即终局；反向陈述被拦截 |
| H-03 | 首次重写修正错误 | 只发布修正稿 |
| H-04 | 两稿均违反硬规则 | 安全 fallback，并记录 retry exhausted |

### 18.3 质量和性能

| ID | 场景 | 验收标准 |
| --- | --- | --- |
| Q-01 | 普通放逐语境出现“我这一票/1.5 票” | 不触发无警长投票资格警告 |
| Q-02 | 真正警选中无资格者承诺投票 | 仍准确触发 |
| Q-03 | 不同对象分别描述为查杀/好人 | 不误报角色术语矛盾 |
| Q-04 | 重写后硬错误相同 | 不循环调用，走确定性 fallback |
| Q-05 | 公开发言超限 | 最终文本在预算内，拒绝稿无事件/语音泄漏 |
| Q-06 | 指标 | 误报、重写成功、耗尽、额外耗时分别计数且标签有界 |

### 18.4 Replay、Live 和语音

| ID | 场景 | 验收标准 |
| --- | --- | --- |
| R-01 | 新局决定性放逐 Replay | 决胜结果 → 必要强制技能 → 终局，无附属动作 |
| R-02 | 非终局遗言 Replay | 遗言、字幕、语音和后续合法结算完整 |
| R-03 | 历史 payload 含终局后遗言 | 按已确认历史策略稳定展示，不静默改写 |
| L-01 | Live 播放中收到新格式终局 | 新 payload 按必写 `terminal_keep_from_event_id` 闭区间保留必要结果；终局 Cue 仅由 `game_completed` 投影；旧 payload 缺字段时维持历史非抢占行为 |
| L-02 | 被抢占或终局后迟到的语音 | 不播放/不重新激活；每个 utterance 仍按 id 发送一次 `voice_played` ACK |
| V-01 | 决胜放逐持久化 | 无遗言/警徽/summary 语音任务；`game_completed` 恰好生成一次终局语音 |
| V-02 | audience | Public/God View 事件—语音覆盖完整且不串线 |
| V-03 | 静态音频 | duration 来自媒体/字幕，不是发送耗时 |

### 18.5 遥测、预算和恢复

| ID | 场景 | 验收标准 |
| --- | --- | --- |
| M-01 | 正常、非法响应、重试、fallback、超时、取消、传输失败 | provider attempt 与 logical action 分别恰有一个终态、分别计数守恒，并以 id 关联 |
| M-02 | 流式公开发言 | 有 delta 时 first token 大于 0；无样本显示 unavailable |
| M-03 | 完整对局 | game duration 和各动作样本与日志一致且非空 |
| M-04 | 动作预算 | 超预算进入明确终态，终局取消不伪装为超时 |
| M-05 | 后台自爆判断 | 私密但可计时、计数、有终态 |
| M-06 | 自爆接受/拒绝 | 当前 schema、窗口、执行状态和耗时完整 |
| M-07A | 决胜结果已应用、winner 写入前崩溃 | 恢复后重算并提交 winner，不重复决定性结果或模型调用 |
| M-07B | winner 已写入、completion 前崩溃 | 只补一次 `game_completed`，不复活附属动作 |
| M-07C | 猎人选择已接受、枪击结果应用前崩溃 | 从 settlement cursor 应用已接受目标，不再次请求猎人 |
| M-07D | 猎人结果 `applied` checkpoint 后在首次发布前或发布后崩溃 | child run 以相同 `presentation_id` 恢复 shot/skipped 结果并建立本 run 终局边界；已消费客户端不重复呈现，未消费客户端呈现一次 |
| M-07E | 狼人数量达到好人数量后，死猎人击杀一狼使候选失效 | 正常与崩溃恢复均清除 winner 候选，跳过已省略的遗言，完成合法 aftermath 并继续对局；不重复请求猎人模型或发布结果 |
| M-07F | 原放逐尚未终局、某个猎人枪击分支可能终局，遗言结果发布前或发布后崩溃 | 合法遗言仍恰好呈现一次；恢复不再次调用遗言模型，使用稳定 `lws_*` 发言和 `lwr_*` 状态语义 ID 后再进入猎人结算 |
| M-08 | 指标隐私 | 无模型原文、玩家名和任意异常文本标签 |

## 19. 验证命令

后端测试必须从 `apps/api` 运行：

```bash
cd apps/api
.venv/bin/pytest -q \
  tests/test_run_05aa0b0f2b92_p0_regression.py \
  tests/test_werewolf_runner.py \
  tests/test_werewolf_lm.py \
  tests/test_werewolf_public_facts.py \
  tests/test_werewolf_action_quality.py \
  tests/test_werewolf_execution_budget.py \
  tests/test_werewolf_execution_telemetry.py \
  tests/test_werewolf_quality_metrics.py \
  tests/test_werewolf_quality_telemetry.py \
  tests/test_replay_playback.py \
  tests/test_live.py \
  tests/test_live_store.py \
  tests/test_voice_materializer.py \
  tests/test_voice_store.py \
  tests/test_voice_stream_api.py \
  tests/test_admin_p2_diagnostics.py \
  tests/test_werewolf_resume.py
.venv/bin/pytest -q
```

共享客户端与 Mobile Web：

```bash
pnpm --dir packages/game-client test -- --run
pnpm --dir packages/game-client typecheck
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web lint
pnpm --dir apps/mobile-web build
```

提交前：

```bash
git diff --check
git status --short
```

## 20. 灰度、回滚与风险

### 20.1 灰度指标

首批观察：

- `terminal_candidate` 到 `game_completed` 的 P50/P95；
- winner 后玩家 provider 调用数，目标恒为 0；
- 因终局取消的 action 数；
- 非终局遗言缺失率，目标无回归；
- 猎人合法触发完成率；
- Live 终局后积压 Cue 数和迟到 ACK；
- Prompt 未知状态码告警；
- 质量重写率、成功率和额外耗时；
- 静态语音 duration 与字幕末端偏差。

### 20.2 主要风险

| 风险 | 缓解 |
| --- | --- |
| 过早判胜截断猎人或同夜死亡 | 显式强制结算队列；T-02/T-07 回归 |
| 过度修复导致非终局遗言消失 | 单独保留 T-03/R-02 |
| 首夜顺序改变普通玩法 | 只对终局投影命中的批次走例外 |
| Live 抢占漏掉决定性结果 | 保留稳定 terminal source boundary，不按数组位置猜测 |
| 历史回放表现变化 | 默认忠实历史，投影策略显式版本化 |
| 中文映射破坏协议 | 只改 Prompt 展示层，枚举持久化不变 |
| validator 新增误报 | 硬规则使用阶段和状态，不做纯关键词判断 |
| winner 已写但 completion 失败 | checkpoint 幂等补 completion，不恢复附属 action |

### 20.3 回滚

- 引擎终局边界不能回滚为“继续请求玩家动作”；出现问题时优先关闭非关键 Live 抢占或新的质量 validator，而不是恢复终局后遗言。
- Prompt 中文映射可以独立回滚，但必须保留未知值不泄漏的安全兜底。
- 历史 Replay 投影若上线，应有独立版本/开关；原始事件始终保留。
- 所有回滚均需保留新旧 checkpoint 和可选 DTO 字段的双读兼容。

## 21. 完成定义

同时满足以下条件才算完成：

1. 本局三人残局 fixture 在引擎、事件、Replay、语音和 Live 五层均通过。
2. 最后一民被放逐后没有遗言；该场景稳定胜方确定后玩家 provider 调用为 0。
3. 在 TASK-00 确认的推广范围内，所有终局路径都跳过警徽、独立 summary、私有记忆和下一轮。
4. 猎人、同夜多死亡和白痴免死没有被提前终局破坏。
5. Prompt 不再出现 `vote_exile` 等叙事性内部状态码，持久化协议保持兼容。
6. 玩家声明不会再被渲染成引擎确认事实。
7. 猎人“下一夜主动开枪”等硬规则错误被确定性拦截，拒绝稿无泄漏。
8. 质量误报和发言长度有自动化边界，重写最多一次且可观测。
9. Live 终局行为、历史 Replay 策略和静态语音时长合同有测试固定。
10. provider 计数守恒，游戏时长、首 token、预算、自爆 provenance 和终局取消可诊断。
11. 目标测试、后端全量测试、共享客户端和 Mobile Web 验证全部通过。
12. 旧设计被标注为已实现基线，并明确链接本文取代的终局条款。

## 22. 当前状态

- [x] 完成 `run_2d12b755578b` 只读复盘。
- [x] 确认最终胜负正确、终局后仍执行遗言的问题。
- [x] 盘点其他终局后继续路径及现有测试/设计冲突。
- [x] 确认 Prompt 内部状态码需改为中文明文。
- [x] 汇总事实可信度、猎人硬规则、质量、时长、语音和遥测问题。
- [x] 形成开发任务、测试矩阵、验收与风险方案。
- [x] 完成 TASK-00 产品决策确认并采用全部推荐默认项。
- [x] 完成 TASK-01～TASK-09 业务代码与回归测试。
- [x] 完成 TASK-10 全链路验收与文档收口。

## 23. 实施与验收记录

### 23.1 已落地合同

- 引擎以“决定性结果 → 合法强制结算 → 稳定胜方 → 最终状态 → `game_completed`”为唯一终局顺序；终局不再生成遗言、警徽、独立总结、私有回合记忆或下一轮玩家动作。
- 猎人、同夜多死亡、白痴免死与首夜延迟死亡使用确定性投影；只有仍可能改变胜负的合法结算能穿过终局候选窗口。
- 首夜 deferred death 尚未落地时，警长竞选中的最后一狼自爆只形成终局候选；夜死与猎人结算写入首个终局 checkpoint 后才提交 winner，避免丢失整批死亡。
- provider 前同时校验持久化 winner 与当前存活结构；被终局抢占的 logical action 和 provider attempt 使用受控终态收口，拒绝稿不进入事件、Replay、语音或公开 DTO。
- Prompt 叙事区使用集中式中文语义映射；`vote_exile` 等内部枚举只保留在持久化、Replay 协议和受控 JSON Schema 中。未知值 fail closed 为中文兜底并记录内部告警，不回显原码。
- 未知状态只有在确认为不含 ASCII 标识符的中文明文时才允许透传；斜杠、空格、纯数字等非中文未知值一律走中文兜底。必须输出协议 enum 的 `benefit_type` 在 Prompt 中逐值附带中文释义。
- 公开事实保留 `category`、`trust_class`、轮次、主体和来源；共享客户端 parser 同步保留这些可选 provenance 字段。私人观察和策略笔记继续走独立授权通道。
- 新局 Live 的 `game_completed` 严格写入 `terminal_keep_from_event_id`，按闭区间保留决定性结果并抢占普通 backlog；每条被跳过的 utterance 仍独立 ACK。历史缺字段 payload 与历史 Replay 保持原行为。
- `settlement_v1` checkpoint 分别记录决定性主结果、猎人选择、候选解除 continuation 和 winner 提交；主结果使用稳定 `pp_*` immutable snapshot，猎人 shot/skipped 使用稳定 `hp_*`。恢复严格按 primary → hunter → folded/continuation 执行；候选被猎人逆转时继续当前轮合法后续，但不回填已经跳过的放逐遗言，也不重复请求猎人模型。恢复跨入下一轮后的 checkpoint 保留完整历史日志前缀，支持再次崩溃、再次恢复。
- 正常和恢复终局的最后公开 state 都折叠 `public_summary`；folded state 不携带 `presentation_id`，因此不会再次生成主结果语音。放逐、夜死、自爆和猎人结果均可作为 durable judge voice 的语义 occurrence。
- 当原放逐尚未终局但猎人技能可能决定胜负时，合法遗言保持在主结果与猎人之间；完成态先进入 checkpoint，再以稳定 `lws_*`/`lwr_*` 发布。发布边界两侧崩溃均可恢复且不重复调用遗言模型；若原放逐已经终局，则仍严格跳过遗言。
- Live 导播、God View 事件轨和语音以 session 为连续性边界记录已经实际呈现或播放完成的 `presentation_id`：父 run 已消费的 child occurrence 不再展示或播放，但仍逐 utterance ACK；父 run 尚未真正消费时，child occurrence 正常呈现一次。完整 Replay 中 Director 与 voice 选择同一个实际 occurrence；显式 seek 开启新的回放遍历。原始父/子 transport event 可以各保留一条，客户端效果保持 effectively-once。
- logical action 遥测的 finalized-ID 去重窗口采用有界 FIFO，避免长时间运行的 API 进程随对局数量无界增长；指标标签仍只使用受控低基数值。

### 23.2 固定残局验收

新增脱敏夹具 `run_2d12b755578b_terminal_regression.json`：狼警长、最后一民、存活猎人三人残局，最后一民被放逐后立即判狼人胜。配套测试串联以下五层：

1. Engine：胜方与存活结构正确，终局后 provider 调用为 0；
2. 公开 DTO / Replay：没有遗言、警徽、独立总结或私有摘要；
3. 真实数据库 voice outbox：没有玩家或终局附属语音，`game_completed` 恰好一个法官任务；
4. Live source boundary：从 `exile_resolved` 开始的闭区间完整且无后续模型事件；
5. game-client：收到同 run/session 的完成事件后，从决定性放逐边界抢占普通积压。

### 23.3 兼容、灰度与回滚落点

- 兼容：死亡原因和 action 枚举未迁移；新增事实 provenance、终局边界、`presentation_id` 和诊断字段均为加法字段，旧客户端可忽略，当前共享客户端可选读取；旧 checkpoint 双读，历史 Replay 不重写。`voice_utterances.presentation_id` 由 Alembic `20260717_27` 以 nullable 字段加入，旧语音记录可继续读取，并可从对应 source event 兼容派生。
- 灰度：Admin P2 与结构化日志可观察 provider attempt、logical action、终局取消、重写收益、时长预算、自爆窗口和静态语音时长；指标标签只使用有界枚举，不携带 Prompt、模型原文或玩家名。
- 回滚：只能独立关闭 Live 抢占展示或新的非关键质量校验；不得回滚为 winner 后继续请求玩家。原始事件和历史回放始终保留，Prompt 映射回滚也必须保留未知码不泄漏兜底。

### 23.4 2026-07-17 验证结果

| 范围 | 结果 |
| --- | --- |
| API Ruff | `app`、`tests` 全量通过 |
| API pytest | `1844 passed, 10 skipped` |
| `run_2d12b755578b` 五层回归 | `1 passed` |
| game-client | `333 passed`，typecheck 通过 |
| Mobile Web | `211 passed`，lint、生产构建及 bundle budget 通过 |
| Admin Web | 单 worker 全量 `290 passed`，lint、生产构建通过 |
| Alembic | 唯一 head 为 `20260717_27`；本地开发库升级后 `alembic check` 无待生成操作 |
| 工作树检查 | `git diff --check` 通过 |

Admin Web 的首次并发复验触发既有异步列表加载时序抖动；按仓库稳定验证方式使用 `--maxWorkers=1` 重跑全绿。本轮新增或修改的 Admin P2 用例在此前定向与全量验证中均通过。
