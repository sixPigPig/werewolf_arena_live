# 狼人杀直播娱乐模式规则、发言语音与可观测性升级开发设计

## 1. 文档信息

- 编写日期：2026-07-18
- 文档状态：已按确认合同完成本地开发与回归，待提交/发布
- 样本对局：game_16060126
- 样本运行：run_51df2451a620
- 适用模式：现有单一直播娱乐模式
- 适用范围：后端规则与运行合同、Mobile 直播/回放呈现、Admin 配置/诊断/复盘管理、语音与质量统计
- 当前实现状态：后端、Mobile、Admin、数据库迁移与回归测试均已落地；未部署，也未改写历史对局

本文明确按三条实现线拆分：后端提供唯一真源；Mobile 修改观众侧 Live / Replay、字幕与语音播放；Admin 修改规则、音色、试听、诊断与复盘管理。Mobile 与 Admin 是两个独立前端，不共用页面职责，也不把改动合并描述。

本地开发落地状态：

- **后端**：完整规则契约与冻结快照、动作来源/超时矩阵、阶段生命周期、发言失败语义、TTS 演绎快照、赛后质量任务和三层统计已实现。
- **Mobile**：只更新 Live / Replay 的公开阶段、未发言、动作取消、系统代投标记及语音播放消费；没有新增配置或复盘管理入口。
- **Admin**：只更新规则契约管理、玩家音色与演绎试听、运行诊断、质量任务与关键决策卡；不承担普通观众 Live / Replay 页面职责。

关联设计：

- [管理端可配置规则集设计](./2026-07-12-configurable-rule-sets-design.md)
- [即时自爆、驱逐遗言与玩家事实推理修复设计](./2026-07-17-self-explosion-last-words-and-player-reasoning-remediation-design.md)
- [终局结算边界、Prompt 语义与决策质量修复设计](./2026-07-17-terminal-settlement-prompt-semantics-and-quality-remediation-design.md)
- [P2 对局质量与性能修复设计](./2026-07-14-p2-game-quality-performance-remediation-design.md)
- [P3 质量评估与可观测性修复设计](./2026-07-14-p3-quality-evaluation-observability-remediation-design.md)
- [隐私 Audience Contract v2](./2026-07-15-privacy-audience-contract-v2-remediation-design.md)
- [Live Voice 数据库设计](./2026-07-08-live-voice-streaming-db-design.md)

本文是上述设计在 game_16060126 暴露的新边界上的增量合同。若旧文档与本文冲突，以本文已确认的产品决策为准，尤其包括：

1. 不新增纯评测模式，只保留直播娱乐模式。
2. 不在局中纠正模型的推理错误或替模型做出“更正确”的决定。
3. 发言未取得有效结果时不生成伪造的第一人称玩家台词。
4. 公开硬规则说错也属于模型表现，赛后标注但不触发语义重写。
5. canceled、fallback、provider timeout 和 retry 必须分开统计。

## 2. 总体结论

game_16060126 的状态机结算和狼人胜利结果正确，Live 事件连续，Replay 与最终状态一致。该局不是“引擎算错了”，而是同时暴露了四类产品问题：

1. **模型真实推理错误**：规则和身份信息已经正确传入，模型仍认错队友或形成内部矛盾。这些错误应被原样保留。
2. **模型输入不完整**：引擎禁止狼人袭击自己或狼队友，但模型可见公共规则没有明确说明，导致相关判断不能完全归因给模型。
3. **系统降级伪装成模型行为**：超时中性发言和系统代票在表现与统计上容易被误认为玩家真实表达。
4. **运行与展示合同不统一**：阶段完成事件、赛后复盘状态、语音演绎、Admin 配置和统计口径缺少共同的数据来源。

本次升级的目标不是提高模型胜率，也不是消除模型犯错，而是做到：

> 给模型完整、中性、依法可见的规则与事实；模型仍可推错、说错和选择错误；系统不得把自己的超时降级伪装成模型意图；直播、回放、语音、Admin 和赛后复盘必须能准确说明实际发生了什么。

## 3. 样本对局证据

### 3.1 运行完整性

| 项目 | 结果 |
| --- | --- |
| 对局状态 | complete |
| 运行状态 | completed |
| 胜方 | 狼人阵营 |
| 轮数 | 3 |
| 运行错误 | 无 |
| 恢复次数 | 0 |
| 运行时长 | 约 9 分 54 秒 |
| Live 事件 | 957 条，事件 ID 连续 |
| Replay | 已持久化，与最终状态一致 |
| 赛后质量记录 | game_quality_evaluations 中无对应结果 |

因此，本局后续归因以数据库、持久化 Live 事件、ActionLog、模型请求记录、Replay 和真实引擎候选集合为依据，不以页面观感或单个聚合数字替代运行事实。

### 3.2 角色与关键时间线

| 座位 | 玩家 | 身份 |
| --- | --- | --- |
| 1 | 鹿眠 | 村民 |
| 2 | 七喜 | 狼人 |
| 3 | 阿烈 | 女巫 |
| 4 | 祁野 | 预言家 |
| 5 | 林砚 | 狼人 |
| 6 | 南乔 | 村民 |
| 7 | 老周 | 狼人 |
| 8 | 纪衡 | 白痴 |
| 9 | 小满 | 猎人 |
| 10 | 沈雾 | 狼人 |
| 11 | 卓然 | 村民 |
| 12 | 唐糖 | 村民 |

第一轮：

- 狼队一致袭击 6 号。
- 预言家查验 6 号。
- 女巫没有救 6 号。
- 警长竞选平票后进入 PK，4 号当选警长。
- 2 号在公开发言阶段自爆，取消了尚未完成的 4 号发言并结束当日投票流程。

第二轮：

- 狼队袭击 4 号。
- 女巫没有救 4 号并毒杀 12 号。
- 4 号与 12 号死亡，4 号把警徽移交给 11 号。
- 3 号以 6.5 票被放逐并发表遗言。

第三轮：

- 狼队投票结果使 11 号死亡，11 号撕毁警徽。
- 白天 5、7、8、10 号投 1 号，1、9 号投 10 号。
- 1 号以 4 比 2 被放逐。
- 四名村民均已出局，当前屠边规则下狼人胜利。

### 3.3 请求与逻辑动作口径

本局当前诊断数据为：

| 层级 | 结果 |
| --- | --- |
| 逻辑动作 | 377 |
| completed | 206 |
| 真正 fallback | 11 |
| canceled | 160 |
| Provider 尝试 | 235 |
| valid | 221 |
| invalid | 2 |
| timed out | 11 |
| canceled attempt | 1 |

当前 performance.fallback_count 显示为 171，是把 11 个真正系统降级和 160 个状态机取消相加所得。该字段不能继续用于表达“模型失败次数”。

### 3.4 三个关键推理样本

| 样本 | 模型实际获得的信息 | 观察 | 归因 |
| --- | --- | --- | --- |
| 2 号自爆 | Prompt 已明确狼队友为 5、7、10 号 | reasoning 把真实女巫 3 号称作狼队友 | 模型推理错误 |
| 3 号女巫不救 4 号 | Prompt 已明确 4 号是当夜刀口，合法选择为救 4 号或不救 | reasoning 一方面称 4 号是狼人，一方面又称狼人不能袭击队友，最终不救 | 模型内部逻辑矛盾 |
| 8 号投 1 号 | 引擎真实狼刀候选只包含非狼人 | reasoning 认为狼人可以自刀；模型公共规则未明确禁止 | 模型判断与规则输入缺口共同影响 |

前两项不应触发局中语义重试、改票或改写。第三项应先补齐规则契约，再继续让模型自行推理。

### 3.5 质量重写与超时样本

当前质量重写不是对初稿做行内修改，而是：

1. 第一版公开发言先缓冲，不进入 Live、Replay、字幕或语音。
2. 命中质量问题后，系统把 quality_feedback 交给同一个发言模型。
3. 同一逻辑动作最多重新生成一次。
4. 第一版永不公开；第二版再按现有规则接受、截断或 fallback。

当前该流程应用于警长发言、警长 PK、放逐 PK、放逐遗言和普通辩论。狼人私聊和最终刀票只使用长度预算，不走同一套公开发言重写。

当前检查项覆盖：超长、重复辩论短语、低新颖度、无依据附和、口头禅占比、遗漏警长票、无资格警长票、非预言家查验计划、假设未来或终局、与公开票型冲突、空或无效输出、猎人非法未来开枪、终局后声称仍有未来行动以及死后行动。

第二版仍失败时，当前实现可能使用中性 fallback、空遗言或截断到完整句。本文目标合同会收窄这些路径：语义与推理错误不再触发局中重写；最终没有有效 say 时统一由法官播报“未发言”，不再生成第一人称中性玩家台词。

本局产生 14 次发言质量重试事件：

- repeated_debate_phrase：9 次。
- speech_too_long：7 次。
- 其中 2 次同时命中两类原因。

| 轮次 | 玩家 | 场景 | 原因 |
| --- | --- | --- | --- |
| R1 | 纪衡 | 警长发言 | repeated_debate_phrase |
| R1 | 小满 | 警长发言 | repeated_debate_phrase |
| R1 | 卓然 | 警长发言 | speech_too_long |
| R1 | 唐糖 | 警长发言 | repeated_debate_phrase |
| R1 | 老周 | 辩论 | repeated_debate_phrase |
| R1 | 纪衡 | 辩论 | repeated_debate_phrase |
| R1 | 七喜 | 辩论 | repeated_debate_phrase + speech_too_long |
| R1 | 阿烈 | 辩论 | repeated_debate_phrase |
| R1 | 祁野 | 辩论 | repeated_debate_phrase，之后被自爆取消 |
| R2 | 沈雾 | 辩论 | speech_too_long |
| R2 | 林砚 | 辩论 | repeated_debate_phrase + speech_too_long |
| R2 | 卓然 | 辩论 | speech_too_long |
| R3 | 林砚 | 辩论 | speech_too_long |
| R3 | 老周 | 辩论 | speech_too_long |

这些质量重试与三项严重推理错误无关。系统没有语义校验 reasoning，也不应在本轮升级中增加这种局中裁判。

本局还存在：

- 三次超时后生成的固定中性玩家发言。
- 两次确定性系统票。
- 自爆导致的待执行公开动作取消。
- 完成对局缺少赛后质量评估记录。

这些行为必须在数据和展示上与模型自主行为分开。

## 4. 已确认的产品原则

### 4.1 单一直播娱乐模式

- 不新增“娱乐模式 / 评测模式”开关。
- 不因样本不够纯而终止、重赛或废弃直播对局。
- 系统应优先保证合法、可完成、可观看的对局。
- 赛后可以解释动作来源、规则完整性和运行降级，但不建立另一套纯评测运行路径。

### 4.2 不纠正模型推理

模型拿到正确规则和依法可见事实后，仍可：

- 认错队友；
- 不相信真实预言家；
- 误读票型和发言；
- 形成内部逻辑矛盾；
- 选择合法但明显不优的动作；
- 在公开发言中说错游戏机制。

只要结构化动作属于当时合法候选，系统就应执行原始选择。以下行为明确禁止：

- 因 reasoning 与身份或事实矛盾而发起纠正性重试；
- 让第二个模型改写模型判断；
- 在局中替模型改票、改技能或改自爆决定；
- 把公开硬规则说错作为语义重写理由；
- 将赛后语义评估结果回写对局。

仍然保留的在线校验只有：

- JSON 和字段结构；
- 必填字段；
- 允许的枚举；
- 当前合法候选；
- 输出是否为空；
- 纯展示层的严重超长与近乎逐字重复。

### 4.3 规则补全不等于策略辅导

系统必须告诉模型完整机制，但不能告诉模型当前局面的答案。规则可以写“狼人不能袭击自己或狼队友”，不能进一步写“因此昨夜死亡者一定是好人”。

### 4.4 系统降级不得伪装成模型意图

- 发言超时不生成第一人称中性台词。
- 投票和强制动作的系统代打必须有明确来源。
- canceled 不等于 fallback。
- 系统票可以参与真实胜负结算，但不能计入模型策略样本。

### 4.5 隐藏信息最小化

模型只获得：

1. 公共规则；
2. 角色依法拥有的私有规则；
3. 当前公开事实；
4. 当前角色依法拥有的私人观察；
5. 当前动作的合法候选。

任何由真实隐藏身份推导出的终局预测、阵营数量提示或反事实结果，都不能作为参赛模型提示。

### 4.6 历史对局不可改写

- 不用新规则重新解释旧局的模型能力。
- 不回写历史动作来源、情感或推理结论。
- 新字段无法从旧数据可靠推断时统一显示 legacy_unknown。
- Replay 忠实重放当时实际发生的结果。

## 5. 完整规则契约

### 5.1 单一真源

现有 RuleSet 和规则修订继续作为规则版本与运行快照的基础。新增结构化规则条款层，使以下内容来自同一份受控声明：

- 引擎约束的业务含义；
- 模型可见规则文本；
- Admin 规则展示；
- 当前动作的合法候选说明；
- Replay 保存的规则快照；
- 规则覆盖测试。

规则条款建议使用以下结构：

    RuleClauseV1
      clause_id
      schema_version
      applies_to_rule_sets[]
      roles[]
      phases[]
      actions[]
      audience
      neutral_text_zh
      engine_constraint_ids[]
      prompt_slots[]
      status

clause_id 必须稳定。neutral_text_zh 只描述机制，不包含局面结论、默认策略或隐藏信息。

### 5.2 Prompt 五层结构

每次模型动作的输入按固定顺序构建：

1. **公共固定规则**：所有席位一致。
2. **角色私有规则**：只描述该角色依法知道和能做的事情。
3. **当前公开事实**：死亡名单、公开发言、公开票型、警徽和已公开身份。
4. **当前私人观察**：狼队友、查验、刀口、药品、守护资源等。
5. **本次合法动作**：阶段、动作类型、候选集合和是否允许放弃。

规则、事实与策略建议必须分区。模型的历史总结和策略记忆不能混入规则契约。

### 5.3 本局确认需要补齐的规则

P0：

- 狼人夜间只能袭击非狼人玩家，不能选择自己或狼人队友。
- 天亮只公布夜间出局名单，不公布每名玩家来自狼袭还是毒药，也不因此公开身份。
- 终局放逐后立即结束对局，不再发表驱逐遗言；可改变胜负的强制结算仍按既有终局合同完成。
- 胜负判定与终局附属流程的顺序必须与模型规则文本一致。

P1：

- 放逐采用加权唯一最高票，不要求过半。
- 最高票平票进入 PK；PK 候选不能参加二轮投票；二轮仍平票则无人出局。
- 自爆的有效公开窗口、会取消的动作、当日投票跳过、自爆无放逐遗言以及未终局时进入下一夜。
- 警长竞选资格、原始警下票权、退水后的票权、竞选平票和警徽流失。
- 女巫知道当夜刀口；同夜救毒互斥；不救时毒药不能选择自己或当夜刀口。
- 猎人死亡触发、毒死禁枪和技能结算顺序。

P2：

- 狼队讨论、最终刀票、平票与系统集体降级规则，仅向狼人和授权视图说明。
- 少见的猎人连锁、多人夜死和警徽边界，仅在适用角色与适用动作中注入。

### 5.4 规则覆盖与版本冻结

每局至少持久化：

- rule_set_id；
- rule_revision_id；
- rule_contract_schema_version；
- canonical rule hash；
- 本次实际注入的 clause_id 列表；
- Prompt 模板版本；
- fallback policy 版本；
- 玩家语音配置快照版本。

CI 维护映射：

    engine_constraint_id
      → rule_clause_id
      → audience
      → applicable role/action
      → prompt snapshot

每个引擎硬约束都必须映射到稳定条款并声明 audience。只有对当前行动者依法可见且影响本次决策的条款才进入 Prompt；纯内部完整性约束可以标记 internal_only，不生成模型可见文本。新增约束缺少条款、audience 或适用角色/动作映射时，合同测试必须失败；依法可见的决策约束缺少 Prompt snapshot 时同样失败。运行中的对局、恢复和 Replay 始终使用开局冻结快照，不读取 Admin 的最新修订。

### 5.5 明确移除策略教练

以下内容不能作为规则条款：

- 收益不明确时默认不自爆；
- 默认保护某类角色；
- 推荐优先投谁；
- 当前动作是否大概率终局；
- 基于隐藏身份计算的最优选择。

若未来需要策略辅助，必须作为独立、显式、版本化的产品能力讨论；本文不引入。

## 6. 发言生成与质量重写

### 6.1 活人感目标

发言 Prompt 从“报告式总结”调整为“桌上即时交流”：

- 优先回应最近一到两名具体玩家；
- 允许部分同意、保留意见、临时犹豫和改变站边；
- 允许短句、停顿、反问和情绪变化；
- 发言长度随位置、是否被点名和局面压力变化；
- 玩家性格是稳定倾向，不是固定口头禅模板；
- 不强制每轮使用“结论先放”“三点收束”“共识与分歧”等报告结构；
- 不强制每次发言都新增完整事实清单。

目标是让不同玩家像同一张桌上的不同人，而不是十二份格式相同的分析报告。

### 6.2 发言输出契约

发言模型在同一次调用中返回：

    SpeechOutputV2
      say
      delivery
        mood
        intensity
        pace
        instruction

其中：

- say 是唯一公开文本。
- delivery 只控制语音演绎，不进入其他玩家 Prompt、公开事实或轮次摘要。
- mood、intensity、pace 使用受控枚举。
- instruction 是可选的短演绎提示输入，长度受限，只能描述演绎，不得包含新事实、身份、夜间行动或私人 reasoning；模型返回值绝不原样透传给 TTS。
- delivery 缺失或不合法时，保留有效 say，并回退到玩家冻结的基础演绎风格。

后端把 mood、intensity、pace 与通过白名单校验的非事实演绎词编译为 effective_delivery。instruction 中出现座位号、玩家名、角色、动作结果、阵营判断或其他游戏事实时，丢弃整段 instruction，仅使用受控枚举和冻结基础风格；say 仍然有效。最终 context_texts 只能由后端模板生成，不能直接拼接模型自由文本。

### 6.3 质量重写边界

第一版发言继续缓冲，未通过前不公开、不物化语音。在线质量重写最多一次，只处理表现层问题：

- 与同一玩家近期发言近乎逐字重复；
- 严重超过当前动作的长度上限；
- 空输出或没有可发布的 say；
- 明显是模板占位符、系统错误文本或无法朗读的结构残片。

以下内容不触发重写：

- 身份判断错误；
- 队友识别错误；
- 战术选择错误；
- reasoning 内部矛盾；
- 公开说错游戏规则；
- 不相信公开事实；
- 对票型或发言的错误解释。

公开硬规则错误保留为模型原始表现，只在赛后复盘标注。该决定解决“不纠正模型推理”与旧质量门禁之间的冲突。

### 6.4 发言失败统一语义

以下任一情况最终没有取得有效 say 时，均视为本轮未发言：

- Provider 超时；
- 动作总截止时间到达；
- 格式重试后仍无效；
- 质量重写超时或仍为空；

以上实际发言失败由法官公开播报：

> X号玩家本轮未发言。

约束：

- 不写入玩家发言历史；
- 不作为玩家语气、立场或承诺供后续模型分析；
- 在公共时间线写入 player_did_not_speak 事实，使后续玩家知道该席位没有发表观点；
- 使用法官事件和法官音色；
- Live 与 Replay 显示“发言超时”或对应失败来源；
- 不生成“本轮暂不追加判断，投票时我会给出明确选择”等伪造台词。

请求因自爆、玩家死亡、阶段关闭或其他状态变化被取消时，语义必须保持 canceled：只发布对应的公开取消事实，不播放“本轮未发言”，不写入 player_did_not_speak，也不计入 speech failure 或 fallback。取消同样不写入玩家发言历史。

## 7. 投票与技能动作超时

### 7.1 通用合同

每种动作必须显式定义：

- 是否可选；
- 是否必须产生结算结果；
- 超时默认；
- 是否消耗资源；
- 是否公开；
- fallback 选择算法；
- 迟到结果处理；
- 恢复与重放语义。

截止后到达的模型结果统一记录为 late_result_discarded，不能覆盖已经接受的系统结果。

### 7.2 已确认策略矩阵

| 动作 | 超时结果 | 资源 | 标记与可见性 |
| --- | --- | --- | --- |
| 公开发言 | 不发言，由法官播报未发言 | 不适用 | 立即公开 |
| 放逐票、警长票等强制公开投票 | 系统从当时合法候选中确定性代投 | 不适用 | 立即标记系统代投 |
| 女巫救人 | 不救 | 不消耗解药 | 终局前仅授权视图 |
| 女巫毒人 | 不毒 | 不消耗毒药 | 终局前仅授权视图 |
| 猎人开枪 | 不开枪 | 不消耗技能状态以外资源 | 公开技能窗口可播报跳过 |
| 狼人自爆 | 不自爆 | 不适用 | 无公开动作 |
| 预言家查验 | 本轮不查验，不生成结果 | 不适用 | 终局前仅授权视图 |
| 守卫或医生保护 | 本轮不保护 | 不消耗可用次数 | 终局前仅授权视图 |
| 警徽移交 | 默认撕毁警徽 | 警徽销毁 | 立即公开并标记规则默认 |
| 警长发言顺序 | 使用确定性的左或右顺序 | 不适用 | 立即公开系统选择 |
| 狼队个人刀票 | 该狼人弃权，不伪造个人票 | 不适用 | 终局前仅 God/Admin |
| 狼队集体无结果 | 系统从合法非狼人候选中确定性选取目标 | 不适用 | 终局前仅 God/Admin，终局后复盘披露 |
| 遗言 | 跳过遗言 | 不适用 | 公开显示未发表或直接进入后续流程 |

狼队结算顺序：

1. 只统计按时返回的有效狼票。
2. 有唯一有效结果时按真实票执行。
3. 存在规则规定的有效平票处理时先按规则处理。
4. 全部弃权、持续平票或集体仍无结果时，才使用系统确定性合法目标。

确定性算法必须只消费冻结 seed、action identity 和当时合法候选集合；不得使用候选的真实神民价值、未来胜负预测或模型不可见信息做排序。

### 7.3 系统结果与模型结果分离

逻辑动作记录同时保留：

    model_result
      status
      choice
      reasoning
      attempt_ids[]

    effective_result
      origin
      choice
      reason_code

    lifecycle_status

推荐枚举：

- lifecycle_status：completed、fallback、canceled、failed。
- effective_result.origin：model、system_fallback、state_machine、none。
- reason_code：timeout、batch_deadline、invalid_exhausted、quality_exhausted、self_explosion_cancelled、phase_advanced、rule_default 等稳定低基数枚举。

canceled 动作没有 effective choice，不能伪装成 fallback。

## 8. 动作来源、Live 与 Replay

### 8.1 展示徽标

Live 使用轻量徽标：

- 发言超时；
- 系统代投；
- 规则默认；
- 动作取消；
- 重试后完成。

不需要给每个正常模型动作显示“模型决定”。赛后复盘和 Admin 再展示完整来源。

公开系统代投完成后，后续玩家的公共事实必须同时包含票的最终去向和 origin=system_fallback，避免把系统目标误认为该玩家的主动站边。未发言事件同理，只表示“没有发表观点”，不得派生虚假立场。

### 8.2 公开与隐藏来源

- 公开发言跳过、公开投票代打、警徽规则默认可以实时公开。
- 狼刀、女巫、预言家、守卫等隐藏动作的来源在终局前不能进入 player_public。
- God View 与授权 Admin 可实时查看其有权访问的来源。
- 终局回放可以按产品权限展示隐藏动作来源，但原始 Prompt、raw response 和私人 reasoning 仍仅限受控 Admin 调试权限。

### 8.3 Replay 合同

- Replay 只重放持久化结果，不重新调用模型、不重新选择 fallback、不重新推断 delivery。
- 每个关键动作可以查看模型结果、系统有效结果、取消原因和规则版本。
- 被自爆取消的发言保留为取消记录，不作为已发表内容。
- 旧事件缺少来源字段时显示“来源未知 / 旧数据”，不默认归因给模型。
- 音频缺失只影响播放，不改变动作时间线。

### 8.4 关键决策卡

赛后只挑高影响动作，不把全部事件强塞给用户。每张卡包含：

- 轮次、阶段、角色和动作；
- 当时合法候选；
- 动作来源；
- 模型原始选择与系统有效选择；
- 相关规则条款及输入是否完整；
- 动作是否合法；
- 可验证的 reasoning 矛盾；
- 对当前状态的直接影响；
- 谨慎的单步反事实。

反事实只描述可以确定的下一步变化。例如“8 号若改投 10 号，当前票型将从 4 比 2 变为 3 比 3 并进入 PK”，不能直接声称之后好人必胜。

## 9. 隐藏信息与 Prompt 安全

### 9.1 明确禁止的玩家提示

- 未公开真实身份和神民分布；
- 夜间真实死亡原因；
- 狼队私聊与其他玩家私人 reasoning；
- 未公开查验、刀口和用药；
- 根据真实角色调用胜负函数后得到的“该动作一定终局”；
- 未发生动作的必胜、必输或最优反事实。

### 9.2 本局发现的高风险字段

- 自爆提示中的 explosion_would_end_game。
- 猎人提示中的 terminal_after_current_action 或同类全知终局判断。

这些字段若由真实隐藏角色计算，只能用于引擎内部结算或授权诊断，不能反馈给参赛模型。

### 9.3 可见性原则

提示可以说明：

- 当前公开存活名单；
- 已公开死亡和票型；
- 当前玩家自己的身份；
- 狼人依法知道的队友；
- 预言家自己的查验；
- 女巫当夜刀口和药品余量；
- 当前合法候选。

提示不能替模型推出：

- 夜死者的真实阵营；
- 当前还剩多少神或民；
- 自爆或开枪后是否必然获胜；
- 某个策略是否最优。

## 10. 阶段与事件完成契约

### 10.1 分离三类完成

系统必须区分：

1. **游戏动作完成**：引擎已经接受唯一有效结果并持久化。
2. **游戏阶段完成**：该阶段不会再产生新的规则动作。
3. **展示与语音完成**：客户端已经消费或跳过可见事件，并完成必要 ACK。

语音失败不能回滚游戏动作；展示积压不能让引擎重复执行动作；游戏阶段完成也不代表所有观众已经播完。

### 10.2 阶段生命周期

每个进入的阶段都有稳定 phase_instance_id，并在内部事实流中产生唯一 canonical started 与唯一 canonical completed。唯一性按 (phase_instance_id, lifecycle_kind) 计算，不按 audience 重复计数。completed 至少携带：

- phase_instance_id；
- round；
- phase；
- completion_status；
- completion_reason；
- next_phase；
- terminal；
- source_event_id；
- audience_policy。

completion_status 建议为 completed、skipped、canceled、terminal。canonical 记录保存 audience_policy；隐私层从同一 canonical 事件生成带具体 audience 的投影，投影不是新的阶段生命周期事实。player_public 必须收到不含隐藏细节的 started / completed 投影，Mobile 才能仅依据生命周期推进；God View 与 Admin 可以在授权范围内收到更完整字段。崩溃导致未闭合时，由 run failure 指向未完成阶段；恢复不得重复发出已经持久化的 started 或 completed。

### 10.3 夜间、警长与天亮独立

不能只给首夜打补丁。每一夜都拆分为：

    night_actions_started
      → night_actions_completed
      → 可选的独立公开流程
      → dawn_reveal_started
      → dawn_reveal_completed

其中：

- canonical night_actions_completed 表示当夜强制与可选动作已经完成；其原始隐藏 payload 不直接进入 player_public，但必须投影出仅含 phase_instance_id、公开阶段名、completion_status、completion_reason、next_phase、terminal 和 source_event_id 的公共完成标记，不泄漏动作数、角色、目标、死因或 fallback。
- sheriff_election_started / completed 是独立可选流程。
- 是否启用警长、在哪一轮触发、插入在什么位置，由冻结规则快照决定，不能写死 round 等于 1。
- dawn_reveal_completed 只公布规则允许的夜间出局名单，不公布内部死因。
- 没有警长或其他插入流程时，夜间动作完成后直接进入天亮揭晓。

### 10.4 白天结算

以下分支都必须产生一次且仅一次 day_resolution_completed：

- 正常放逐；
- PK 后放逐；
- 二轮平票无人出局；
- 白痴免死；
- 狼人自爆；
- 终局放逐；
- 规则关闭投票；
- 强制失败导致运行终止。

自爆分支的 completion_reason 为 self_explosion，并明确剩余发言和投票动作已经 canceled。终局分支先闭合当前阶段，再发布 game_completed。

Live、Replay 和恢复逻辑只依赖事件 ID、phase_instance_id 和完成合同，不根据某类事件“通常会不会出现”猜测状态。

## 11. 后端 TTS 情感演绎合同

### 11.1 当前基线

当前语音链路使用：

- 火山引擎 seed-tts-2.0；
- 双向流式 WebSocket；
- BidirectionalTTS namespace；
- 玩家音色 zh_female_gaolengyujie_uranus_bigtts；
- 法官音色 zh_female_vv_uranus_bigtts；
- PCM、24000 Hz；
- 所有玩家共用一个 player_speaker；
- StartSession 只传 speaker 和 audio_params；
- TaskRequest 只传分块后的 text；
- 当前文本按标点和最多 24 字分块。

当前实现入口：

- apps/api/app/werewolf/volcengine_tts.py
- apps/api/app/werewolf/voice.py
- apps/api/app/werewolf/voice_materializer.py
- apps/api/app/werewolf/voice_stream.py

### 11.2 火山引擎 TTS 2.0 接入

官方双向流式接口支持在 StartSession 的 req_params 中传入 context_texts，作为不朗读的语音指令。当前项目应把最终接受的 delivery 映射为 context_texts，而不是把指令拼进 say。

示例：

    {
      "req_params": {
        "speaker": "zh_female_gaolengyujie_uranus_bigtts",
        "audio_params": {
          "format": "pcm",
          "sample_rate": 24000,
          "enable_subtitle": true
        },
        "context_texts": [
          "像真人在狼人杀现场接话。前半句克制，后半句转为质疑；语速自然，强调5号，不要播音腔。"
        ]
      }
    }

官方参考：

- [双向流式语音合成 WebSocket](https://docs.volcengine.com/docs/6561/2532486?lang=zh)
- [语音指令与引用上文示例](https://www.volcengine.com/docs/6561/1871062?lang=zh)
- [语音合成大模型产品简介](https://www.volcengine.com/docs/6561/1257543?lang=zh)

历史 V1 接口中的 enable_emotion、emotion 和 emotion_scale 只适用于部分多情感音色，不作为当前 seed-tts-2.0 路线的主方案。

context_texts 只能在供应商明确支持的 TTS 2.0 预置音色上启用。未来若接入复刻音色，后端与 Admin 必须先按当前接口能力校验，不能默认复刻音色支持同一语音指令合同。

### 11.3 delivery 安全边界

context_texts 只能由后端模板编译，输入限于：

- 当前最终接受的 delivery；
- 当前 audience 已经可以看到的公开上下文；
- 玩家开局冻结的基础演绎风格。

模型返回的自由文本 instruction 不得直接出站。后端先执行第 6.2 节的事实字段拒绝与演绎词白名单校验，再由受版本管理的 delivery mapping 生成 effective_context_texts；校验失败时丢弃 instruction，保留 say，并用受控枚举与基础风格生成安全指令。

不能来自：

- 私人 reasoning；
- 角色身份；
- 狼队私聊；
- 被拒绝初稿；
- 未公开查验、刀口或药品；
- 全知终局预测。

公开语音与 God View 私密语音必须使用独立上下文，不能跨 audience 复用 TTS 会话。delivery 无效时使用冻结的基础风格，不因此丢弃有效 say。

### 11.4 快照与回放

开局时冻结每名玩家的有效音色和基础演绎配置。对局开始后修改 Admin：

- 只影响新对局；
- 不影响进行中对局；
- 不影响恢复；
- 不影响已排队的语音物化；
- 不影响历史 Replay。

语音任务创建并入队前，必须冻结并持久化最终 speaker、effective_delivery、effective_context_texts、voice_config_version、delivery_mapping_version、TTS 请求来源和 audience。VoiceUtterance 与 voice_materialization_job 均通过不可变快照或稳定快照引用读取这些值；Worker 执行、重试或恢复时不得重新查询当前玩家档案、当前 Admin 配置或重新编译 delivery。Replay 优先复用已经持久化的音频与字幕，不重新推断情绪。

### 11.5 语音失败

- TTS 或 delivery 失败不改变已经接受的 say。
- 直播继续显示字幕，不生成另一段假台词。
- 跳过或失败的 utterance 仍完成必要 ACK，避免阻塞后续播放。
- 法官静态语音资源继续独立管理；若修改法官演绎，需要显式重新生成并版本化素材。

## 12. 赛后复盘任务

### 12.1 目标

赛后复盘不是第二种运行模式，也不是一个总分。它只负责解释：

- 哪些动作由模型完成；
- 哪些动作由系统代打；
- 哪些动作被取消；
- 模型当时拿到的规则是否完整；
- 动作是否合法；
- reasoning 是否存在可验证矛盾；
- 对当前状态产生了什么直接影响。

### 12.2 任务生命周期

赛后复盘是异步、只读、可重试任务：

- not_scheduled；
- queued；
- running；
- completed；
- failed；
- superseded。

终局事务只负责可靠创建任务或记录未调度原因，不等待分析完成。复盘 Worker 失败不能改变 winner、run status、Replay 或 game_completed。

幂等键至少包含：

- session_id；
- run_id；
- evaluator_version；
- source_revision。

相同输入与相同版本重复执行不得产生互相冲突的结果。源数据或评估版本变化时生成新版本，不静默覆盖旧结论。

### 12.3 任务状态输出合同

受控诊断 API 必须提供：

- 当前状态；
- 创建、开始和完成时间；
- 尝试次数；
- 失败原因；
- source_revision；
- evaluator_version；
- 是否可以重试；
- 最近一次成功结果。

无记录不能等同于“质量通过”。后端必须明确区分功能关闭、未调度、排队、处理中和失败；具体 Admin 页面职责在第 17 节单独定义。

### 12.4 四轴归因

每个关键动作分别记录：

1. **动作来源**：模型首轮、模型重试后、系统超时、规则默认、状态机结算、取消。
2. **输入完整性**：规则完整、规则缺失、规则有歧义、关键公开事实缺失、私人观察缺失。
3. **动作合法性**：合法执行、合法但取消、非法归一化、非法后系统降级。
4. **赛后推理观察**：与硬事实一致、身份信息冲突、内部逻辑矛盾、使用未说明规则、纯战术分歧。

赛后语义分析只能标注证据充分的类型，不能把战术分歧判成确定错误，也不能参与下一次局中动作。

### 12.5 隐私

- 普通终局回放只展示产品允许公开的复盘。
- 私人 reasoning、狼队友、查验、刀口和隐藏 fallback 仅在终局后的授权 God View 或 Admin 中展示。
- 未终局或可恢复对局继续使用严格 audience 投影。
- 复盘错误信息和日志不得复制私密 Prompt 或 raw response。

## 13. 统计口径

### 13.1 三层分账

Provider attempt：

- valid；
- invalid；
- timeout；
- transport_failure；
- canceled。

Logical action：

- completed_by_model；
- completed_by_system_fallback；
- canceled；
- failed。

Retry：

- provider_retry；
- format_retry；
- quality_rewrite。

三层不能互相替代。一次逻辑动作可有多次 Provider 尝试，但最终只有一个 lifecycle 状态和至多一个有效结果。

### 13.2 本局预期重算

game_16060126 应展示：

- logical actions：377；
- completed：206；
- fallback：11；
- canceled：160；
- provider attempts：235；
- valid attempts：221；
- invalid attempts：2；
- timed out attempts：11；
- canceled attempts：1。

不得继续展示 fallback_count 等于 171 并暗示 171 次模型失败。

### 13.3 分母规则

- 系统代投和规则默认进入运行可靠性统计，不进入模型推理质量分母。
- canceled 不进入 fallback、timeout 或模型完成分母。
- 重试后取得有效模型结果仍属于模型完成，但标记重试后完成。
- 迟到结果不覆盖已接受结果，也不增加第二个逻辑动作。
- Provider timeout rate 与最终 fallback-used rate 分开。
- 游戏完成、Replay 完整、语音物化和播放 ACK 分开统计。

### 13.4 展示用语

在单一娱乐模式下，赛后页面使用：

- 动作来源；
- 规则输入完整性；
- 运行降级；
- 复盘状态；
- 语音与回放完整性。

避免使用“评测资格”“样本作废”“纯度得分”等暗示第二运行模式的措辞。

## 14. 数据与 API 合同

### 14.1 加法扩展

优先扩展现有稳定实体，不建立并行事实源：

- RuleSet / rule_set_revisions：规则条款与覆盖元数据。
- ActionLog / 模型请求日志：model_result、effective_result、lifecycle_status、retry 分类。
- live_events：phase_instance_id、completion_status、completion_reason、action origin。
- game_replay_payloads：规则、fallback、语音配置和来源快照。
- voice_utterances / voice_materialization_jobs：speaker、effective_delivery、effective_context_texts、voice_config_version、delivery_mapping_version、audience 与不可变快照引用。
- game_quality_evaluations：任务生命周期、source_revision、版本和失败信息。
- virtual_player_profiles：玩家音色与基础演绎。

### 14.2 兼容策略

- 新字段尽量可空并带 schema_version。
- 旧 Replay 缺失来源时显示 legacy_unknown。
- 旧玩家档案没有独立音色时回退现有全局 player_speaker。
- 旧对局不回填无法可靠推断的 delivery、规则 clause 列表或动作来源。
- 恢复始终读取 checkpoint 与运行快照，不读取当前 Admin 配置。
- 新客户端必须容忍旧事件缺字段；旧客户端应忽略新增字段。

### 14.3 可追踪标识

诊断链统一按以下坐标关联：

    game/session
      → run
      → phase_instance
      → logical_action
      → provider_attempt
      → source_event
      → voice_utterance
      → evaluation_result

自由文本、玩家名、run_id 和 request_id 不进入高基数 Prometheus 标签，但可以在受控数据库诊断中查询。

## 15. 后端改动范围

| 领域 | 主要位置 | 职责 |
| --- | --- | --- |
| 规则与快照 | apps/api/app/werewolf/rules.py | 结构化条款、规则编译、版本与哈希 |
| 引擎与超时 | apps/api/app/werewolf/engine.py | 合法候选、动作截止、fallback、阶段完成 |
| Prompt | apps/api/app/werewolf/prompts_zh.py | 五层输入、规则投影、移除隐藏终局提示 |
| 模型协议 | apps/api/app/werewolf/lm.py | 结构校验、SpeechOutputV2、迟到结果 |
| 发言质量 | engine.py 相关质量缓冲与重写路径 | 收窄到表现层，不做语义纠正 |
| 自爆审计 | apps/api/app/werewolf/self_explosion_audit.py | 窗口、取消和来源坐标 |
| Live 与持久化 | apps/api/app/werewolf/live_store.py 及 Live 发布路径 | 生命周期、来源、audience |
| Replay | apps/api/app/werewolf/replay_playback.py | 忠实重放、旧数据兼容 |
| 隐私 | apps/api/app/werewolf/privacy_projection.py | player_public、God View、Admin 投影 |
| TTS | apps/api/app/werewolf/volcengine_tts.py | context_texts、session 请求 |
| 语音派生 | apps/api/app/werewolf/voice.py | 玩家音色、delivery、法官未发言播报 |
| 语音 Worker | apps/api/app/werewolf/voice_materializer.py | 冻结快照、物化、失败与 ACK |
| 语音存储 | apps/api/app/werewolf/voice_store.py | effective delivery 与版本 |
| 质量复盘 | apps/api/app/werewolf/quality_evaluation.py | 异步归因、任务状态、安全输出 |
| Mobile-facing API | apps/api/app/api/routes/games.py 及公开 Live/Replay 路由 | 只返回 player_public 安全投影 |
| Admin API | apps/api/app/api/routes/admin_*.py 及相关管理路由 | 配置、试听、诊断、复盘状态与受控重试 |
| 数据迁移 | apps/api/alembic/versions | 新字段、索引与兼容默认值 |

后端是规则、动作结果、来源、audience、语音快照和复盘状态的唯一真源。Mobile 不能自行推断规则结算，Admin 也不能绕过后端直接修改进行中对局。实际开发前应继续使用 rg 搜索 rule_set、fallback_reason、execution_status、VoiceUtterance、game_quality_evaluations 和 phase completion 的全部调用点。

## 16. Mobile 端改动

Mobile 端范围限定为 apps/mobile-web 与它消费的 packages/game-client 公开 DTO。Mobile 负责直播观看、公开状态、字幕、语音播放与回放，不负责编辑规则、玩家音色、TTS 指令或复盘任务。

### 16.1 直播页面

需要修改：

- 玩家发言失败时显示法官事件“X号玩家本轮未发言”。
- 对公开系统代投显示“系统代投”徽标。
- 对规则默认结果显示“规则默认”徽标。
- 对自爆或阶段推进取消的公开动作显示“动作取消”。
- 对重试后成功的发言显示轻量“重试后完成”，但不展示 Provider 内部错误。
- 继续只有一个直播娱乐模式，不增加模式切换入口。
- 阶段条和推进只消费后端 phase_instance_id、started / completed 与 completion_reason，不根据中文文案推断阶段。

Mobile 不得把系统“未发言”插入玩家发言历史，也不得将系统代投渲染为玩家 reasoning。

### 16.2 字幕与语音播放

- say 仍是字幕唯一文本。
- delivery 和 context_texts 不显示在公开 UI，也不进入字幕。
- 系统“未发言”使用法官 speaker_kind 与法官字幕样式。
- Mobile 只播放后端已经物化并带正确 audience 的语音，不在浏览器重新推断情绪。
- TTS 失败时保留字幕并完成跳过 ACK，不能卡住下一条事件。
- sourceEventId 继续作为播放激活边界，lastSourceEventId 继续用于去重与回放元数据。

### 16.3 回放页面

- 按事件 ID 忠实重放，不重新请求模型、选择 fallback 或推断 delivery。
- 公开关键动作展示模型完成、系统代打、规则默认、取消和来源未知。
- canceled 与 fallback 使用不同样式。
- 旧数据没有 provenance 时显示“来源未知 / 旧数据”。
- 普通终局回放只显示公开复盘；God View 入口按既有授权展示允许披露的隐藏动作来源。
- 默认不展示原始 Prompt、raw response 或私人 reasoning。

### 16.4 Mobile 公开 DTO

packages/game-client 的 Mobile-facing 类型只增加公开安全字段，例如：

- phase_instance_id；
- completion_status；
- completion_reason；
- action_origin；
- public_reason_code；
- speech_status；
- source_event_id；
- last_source_event_id；
- voice_status。

Mobile 公开 API 不得返回：

- 私人 model_result.reasoning；
- 隐藏动作真实目标与 fallback 原因；
- context_texts；
- 未公开规则观察；
- Admin 重试堆栈与 Provider 原始错误。

### 16.5 Mobile 验收

- 发言超时、自爆取消、系统代投和重试后完成四类 fixture 的 Live 表达正确。
- 普通直播看不到隐藏技能 fallback。
- Replay 与原始事件顺序一致，旧 Replay 可正常打开。
- 字幕存在而音频失败时仍可继续推进。
- Mobile 中不存在规则、音色、delivery 或复盘任务编辑入口。

## 17. Admin 端改动

Admin 端范围限定为 apps/admin-web 与专用 Admin API。Admin 负责配置、试听、审计、运行诊断和终局复盘管理，不承担普通观众的 Live / Replay 展示职责。

### 17.1 玩家档案与语音配置

玩家档案新增或下沉：

- tts_speaker；
- base_delivery_mood；
- base_delivery_intensity；
- base_delivery_pace；
- base_delivery_instruction；
- voice_enabled；
- voice_config_version。

表单需要：

- 明确继承全局音色或覆盖为独立音色；
- 校验 speaker 与当前 seed-tts-2.0 能力；
- 限制 delivery 枚举、强度和文本长度；
- 展示最终生效值；
- 保留旧档案回退全局 player_speaker 的兼容状态。

### 17.2 规则契约管理

现有规则修订页面扩展：

- 查看稳定 clause_id；
- 查看适用角色、阶段、动作与 audience；
- 查看引擎约束覆盖状态；
- 查看模型规则文本；
- 发布前阻止缺失 P0 条款或存在覆盖断链的修订；
- 查看某局冻结的规则版本、哈希和实际注入条款。

Admin 不提供任意 Prompt 编辑器，也不能把策略建议写入规则条款。

### 17.3 TTS 试听与法官素材

Admin 专用试听页面或组件提供：

- 使用当前未保存表单草稿试听；
- 输入测试 say；
- 选择玩家 speaker；
- 设置基础 delivery 与本轮 delivery；
- 预览后端实际生成的安全 context_texts；
- 展示合成格式、采样率、耗时和安全错误码。

试听任务与正式对局语音任务完全隔离，不创建正式 source_event_id 或 Replay 音频。API Key 只保存在后端，不返回浏览器。

法官静态素材继续在现有素材管理中独立处理。修改法官演绎时必须显式重新生成、校验并版本化，不随玩家 delivery 自动变化。

### 17.4 运行诊断与统计

Admin 运行详情分别展示：

- Provider attempt：valid、invalid、timeout、transport failure、canceled。
- Logical action：模型完成、系统 fallback、canceled、failed。
- Retry：provider、format、quality rewrite。
- 关键动作的 model_result 与 effective_result。
- 规则版本、Prompt 版本、fallback policy 版本和 voice config 版本。

不得继续把 canceled 合并进 fallback_count。自由文本 reasoning 仅在已有调试权限和终局边界内按需读取。

### 17.5 赛后复盘管理

Admin 页面显示：

- not_scheduled、queued、running、completed、failed、superseded；
- 创建、开始、完成时间；
- 尝试次数与安全失败原因；
- source_revision 与 evaluator_version；
- 最近成功结果；
- 受控手动重试。

关键决策卡在 Admin 中可以展示完整四轴归因，但未终局或可恢复对局继续遵守 audience 投影。无记录不能显示为“通过”。

### 17.6 权限、审计与快照边界

- 配置写操作沿用 Admin Session、RBAC、CSRF、乐观锁与审计。
- TTS API Key、Prompt、raw response 和私密 reasoning 不进入普通列表响应。
- 修改规则或玩家语音配置只影响新对局。
- 进行中对局、恢复、已排队语音物化和历史 Replay 使用开局快照。
- Admin 不提供“将新配置强制应用到当前局”的操作。

### 17.7 Admin 验收

- 玩家档案、规则条款、语音试听、运行诊断和复盘状态分别有清晰入口。
- 表单、后端 schema 与审计记录字段一致。
- 未保存语音草稿可以试听但不会污染正式任务。
- API Key 与私密证据不返回前端。
- 修改配置后旧局保持不变，新局使用新快照。
- game_16060126 显示 11 fallback 与 160 canceled，而不是 171 fallback。

## 18. 推荐开发顺序

### WP-01：冻结样本与基础合同

- 为 game_16060126 建立确定性证据 fixture。
- 锁定三项推理归因和当前统计数字。
- 定义规则条款、动作来源、阶段完成与 SpeechOutputV2 schema。

### WP-02：规则与 Prompt 公平输入

- 补全 P0/P1 规则条款。
- 建立引擎约束到 Prompt 条款覆盖测试。
- 移除隐藏身份计算的终局提示。
- 冻结规则与 Prompt 版本。

### WP-03：超时、fallback 与取消

- 发言失败统一为法官“未发言”。
- 投票与技能按矩阵执行。
- 分离 model_result 与 effective_result。
- 丢弃迟到结果。
- canceled 不再计入 fallback。

### WP-04：事件完成合同

- 增加 phase_instance_id。
- 补齐 started / completed。
- 分离夜间动作、可选警长流程和天亮揭晓。
- 补齐自爆、无人出局和终局分支。

### WP-05：发言活人感与质量重写收窄

- 修改发言 Prompt。
- 接入 say + delivery。
- 删除或降级局中语义纠正路径。
- 验证初稿不会泄漏到 Live、字幕和 TTS。

### WP-06：后端 TTS 与语音快照

- StartSession 接入 context_texts。
- 接收并校验 say + delivery。
- 建立玩家独立音色和基础演绎的数据模型。
- 持久化 effective delivery 并复用到 Replay。

### WP-07：赛后复盘与统计后端

- 复盘任务状态可观察、可重试、幂等。
- 四轴归因。
- 拆分 attempt、logical action 与 retry 指标。
- 验证本局重算结果。

### WP-08：Mobile 端

- 接入公开安全 DTO。
- 增加未发言、系统代投、取消和重试徽标。
- 更新 Live 阶段推进、Replay 与语音 ACK。
- 验证旧 Replay 与新字段兼容。

### WP-09：Admin 端

- 玩家音色与基础演绎配置。
- 规则条款与覆盖状态。
- TTS 试听和法官素材边界。
- 运行诊断、统计分账与赛后复盘管理。

前四个工作包是规则公平性和运行真实性基础；后五个工作包分别完成发言、语音、复盘、Mobile 和 Admin。每个工作包应独立提交并带针对性回归，不建议一次性大爆炸合并。

## 19. 测试与验收矩阵

### 19.1 模型真实性

- 构造模型把非队友称为队友，合法自爆仍原样执行。
- 构造女巫 reasoning 自相矛盾，合法不救仍原样执行。
- 构造玩家公开说错“狼人可以自刀”，不触发语义重写。
- 赛后能标注这些错误，但不修改原动作与 Replay。

### 19.2 规则契约

- 狼人不能袭击自己或队友的引擎约束有稳定 clause_id。
- 模型公共规则明确该限制，同时明确夜死原因不公开。
- 终局放逐遗言规则文本与引擎一致。
- 投票、PK、自爆、警长和女巫边界均有 Prompt snapshot。
- 新增引擎约束但缺失条款、audience 或适用范围时 CI 失败；internal_only 条款不进入玩家 Prompt。
- 对当前行动者依法可见且影响决策的约束缺失 Prompt snapshot 时 CI 失败。
- 恢复运行使用原规则快照。

### 19.3 发言

- Provider 超时后没有玩家 say，只有法官“X号玩家本轮未发言”。
- 无效输出耗尽、质量重写耗尽也走同一未发言语义。
- 被自爆或阶段关闭取消的发言只显示取消，不显示超时、不发布 player_did_not_speak，也不计入 speech failure 或 fallback。
- 被拒初稿不进入 Live、Replay、其他玩家 Prompt、字幕和 TTS。
- 发言长度、口头禅和回应对象呈现可控多样性。

### 19.4 投票与技能

- 相同 seed、action 和候选集合在不同进程与恢复后得到相同系统代票。
- 系统目标始终属于当时合法候选。
- 迟到模型结果不能覆盖系统代票。
- 女巫、猎人、预言家、守卫、警徽和狼刀分别覆盖超时。
- 狼队部分有效票、全超时、平票和单候选分别覆盖。
- 可选技能超时不消耗资源。

### 19.5 来源与隐私

- 公开系统代投实时可见。
- 隐藏动作 fallback 终局前不进入 player_public。
- God View 与 Admin 权限各自通过合同测试。
- context_texts 不含角色、reasoning、私聊或被拒草稿。
- 私密和公开 TTS 会话不共享 audience 上下文。

### 19.6 事件完成

- 每个 started 恰有一个 completed。
- canonical 生命周期唯一性按 (phase_instance_id, lifecycle_kind) 计算；多 audience 投影不产生第二份阶段事实。
- 正常放逐、自爆、无人出局、白痴免死和终局均闭合 day resolution。
- 警长关闭、首轮触发、延后触发和恢复均由规则驱动，不依赖 round 等于 1。
- Mobile 能收到裁剪后的公共夜间完成投影，且不泄漏动作数、角色、目标、死因或 fallback。
- dawn_reveal_completed 只公布公开名单。

### 19.7 后端 TTS

- StartSession 快照精确包含有效 context_texts。
- instruction 含座位、角色或私密事实时，出站 StartSession 不含该自由文本，say 仍有效并回退到安全 delivery。
- delivery 缺失不废弃有效 say。
- 不同玩家可使用不同 speaker。
- 开局后修改玩家语音配置不影响进行中、恢复与历史对局。
- 语音任务先入队、再修改 Admin、最后启动 Worker 时，出站请求仍使用入队前冻结的 speaker、effective_context_texts 与 mapping version。
- 语音失败不阻塞游戏，跳过仍完成 ACK。

### 19.8 Mobile 端

- Live 正确显示未发言、系统代投、取消和重试后完成。
- Mobile 不出现规则、音色和复盘任务编辑入口。
- 公开 DTO 不含 context_texts、私密 reasoning 或隐藏 fallback。
- 字幕存在而音频失败时可以继续推进。
- sourceEventId 与 lastSourceEventId 的既有语义不变。

### 19.9 Admin 端

- 玩家音色、基础演绎与继承关系可配置。
- Admin 试听不创建正式对局语音任务。
- API Key 不返回前端。
- 规则覆盖、运行诊断和复盘状态分别可查看。
- 配置写入具备 RBAC、CSRF、乐观锁和审计。
- 修改配置只影响新对局。

### 19.10 Replay 与复盘

- Replay 不重新调用模型或 TTS 决策。
- canceled 与 fallback 分开显示。
- 旧数据缺失来源时显示 legacy_unknown。
- 复盘 Worker 停止或失败不影响对局完成。
- failed 不能显示为通过。
- 重试保持 source_revision 幂等。
- game_16060126 的三项归因与人工结论一致。

### 19.11 统计

- 一次逻辑动作三次 Provider 尝试仍只计一个 logical action。
- 前两次超时、第三次成功时最终 fallback 为 0。
- 系统代投时 fallback 为 1。
- 自爆取消只计 canceled。
- 本局重算为 206 completed、11 fallback、160 canceled。
- provider attempt 仍独立展示 221 valid、2 invalid、11 timed out、1 canceled。

### 19.12 全链路回归

- apps/api 单元、集成、恢复和迁移测试。
- packages/game-client 类型与投影测试。
- mobile-web Live、Replay、语音和 ACK 测试。
- admin-web 表单、权限、CSRF、试听与复盘状态测试。
- 正常运行与中断恢复对比。
- 旧 Replay、旧 checkpoint 和旧玩家档案兼容测试。

## 20. 发布与回滚

### 20.1 发布原则

- 数据字段先加法上线，再切换消费者。
- 规则契约、fallback policy、SpeechOutputV2 和 voice config 分别版本化。
- 新旧客户端兼容窗口内不得删除旧字段。
- 先用确定性 fixture 和本地样本验证，再使用自然对局观察。
- 不用自动改写历史对局作为验收手段。

### 20.2 建议开关

仅为安全灰度保留实现开关，不形成第二产品模式：

- dynamic_delivery_enabled；
- per_player_voice_enabled；
- phase_completion_contract_v2_enabled；
- provenance_v2_read_enabled。

开关只控制新能力灰度，不改变“直播娱乐模式”的游戏规则与评测定位。

### 20.3 回滚

- 规则新修订可停止供新局选择，但旧局继续使用冻结快照。
- delivery 可回退到玩家基础风格，不能回退到伪造玩家发言。
- per-player voice 可回退全局 player_speaker。
- 新展示字段可隐藏，但持久化来源不得丢失。
- 赛后复盘 Worker 可停用，状态必须显示未调度或失败，不能静默消失。

## 21. 非目标

- 不新增纯评测模式。
- 不保证模型采用最优策略。
- 不在局中纠正 reasoning、身份判断或公开规则错误。
- 不自动改票、改技能或改自爆。
- 不让赛后评估参与游戏规则判定。
- 不把策略建议写进规则契约。
- 不根据新规则重算或改写历史对局。
- 不重做整个 Live / Replay UI，只增加必要的来源与状态表达。
- 不更换 TTS 供应商，也不引入额外语音模型调用。
- 不让语音、Admin 或复盘失败改变胜负与对局完成。
- 不扩大普通观众或非终局 Admin 的隐藏信息权限。

## 22. 完成定义

本文全部开发完成需同时满足：

1. 规则、Prompt 与引擎约束存在可审计覆盖关系。
2. game_16060126 的三项关键推理得到正确归因。
3. 合法但错误的模型动作不会被局中纠正。
4. 发言失败不再生成伪造玩家台词。
5. 系统代投、规则默认、取消和重试来源在 Live、Replay、Admin 与统计中一致。
6. 投票与技能超时矩阵全部落地并通过恢复测试。
7. 隐藏终局预测不再进入参赛模型 Prompt。
8. 每个已进入阶段有稳定且唯一的完成事件。
9. TTS 2.0 使用安全的 context_texts，玩家可独立配置音色和基础演绎。
10. Admin 配置按对局冻结，试听、审计和隐私边界完整。
11. 赛后复盘任务状态可观察、失败可重试且不阻塞对局。
12. attempt、logical action、retry、fallback 与 canceled 指标分账正确。
13. 正常、超时、自爆、终局、恢复、旧 Replay 和语音失败全链路回归通过。

本文没有遗留需要继续扩展的产品讨论点。实施阶段只需在不改变上述合同的前提下确定具体字段名、迁移编号、任务拆分和提交顺序。
