# 管理端可配置规则集设计

状态：已确认
日期：2026-07-12

## 1. 决策摘要

一期建设“受限规则配置器”，只允许管理端组合当前引擎已经支持的角色和玩法机制，不允许新增角色、action、行动顺序或胜负算法。

采用“稳定规则实体 + 不可变发布修订”模型：

- `rule_sets` 保存稳定业务 ID、生命周期、默认标记和当前修订指针；
- `rule_set_revisions` 保存草稿及不可变发布内容；
- 已发布修订不能原地修改，编辑时复制为下一修订草稿；
- 归档只阻止新对局选择，不影响运行中对局、断点恢复和历史回放；
- 每局游戏在创建时固定一份规范化规则快照，此后展示、执行、恢复和回放都使用该快照；
- 规则目录负责“选择哪一版”，规则快照负责“这一局实际执行什么”，游戏引擎不直接访问数据库。

一期不采用单表原地覆盖，因为它无法可靠解决发布并发、修订历史和旧对局恢复；也不采用事件溯源或插件式规则引擎，因为当前需求不需要任意新增玩法机制。

## 2. 目标与非目标

### 2.1 目标

- 允许内部管理端创建、校验、发布、归档、恢复、复制和设置默认规则；
- 保证管理端不能发布当前引擎无法正确执行的组合；
- 保证每局游戏的规则在创建后不可漂移；
- 保证发布新修订或归档规则后，旧 Live、checkpoint 和 replay 仍保持原语义；
- 保持现有四套规则的执行行为和 C 端展示兼容；
- 延续现有 Admin Session、固定 RBAC、CSRF、乐观锁、Problem Details 和审计模式；
- 为未来插件式角色或 action 扩展保留清晰边界，但一期不实现插件机制。

### 2.2 非目标

- 管理端新增角色、阵营、action 或胜负算法；
- 配置夜间行动顺序；
- 配置女巫药剂数量、首夜自救限制或同夜救毒规则；
- 配置守卫不可连续守护；
- 配置普通放逐 PK、投票算法或狼人协商轮数；
- 配置多轮发言或身份揭示策略；
- 配置 `max_rounds`、模型、seed 或虚拟玩家阵容；
- 将新规则热更新到运行中的对局；
- 物理删除已经发布过的规则或修订；
- 提供原始 JSON 或任意提示词编辑器。

## 3. 当前系统约束

当前规则由 `RuleSet` 和 `RoleSpec` 冻结 dataclass 表示，四套官方规则注册在 `OFFICIAL_RULE_SETS` 中。Live run、game session 和 checkpoint 已保存规则 JSON 快照，但创建后台任务和恢复流程仍按 `rule_set_id` 查询当前静态注册表。

一期必须修复以下执行边界：

- API 创建时生成的快照与后台 runner 使用的规则必须是同一份内容；
- `resume_game()` 必须从 checkpoint 快照恢复，不能查询当前目录；
- `day_actions`、`speech_rounds` 和 `reveal_policy` 当前未完整驱动引擎，因此一期不能作为自由编辑字段；
- 预言家、守卫和女巫等特殊行动当前只选择一个存活角色，一期必须限制相应角色最多一名；
- Prompt 中固定的警徽 1.5 票、双爆吞警徽等描述必须改为从有效规则生成；
- 回放、直播和语音一期仍只处理现有 action 集合；
- 法官静态席位语音覆盖 1–12 号，一期人数上限为 12。

## 4. 架构与组件边界

### 4.1 规则领域层

规则领域层是纯 Python 模块，不依赖 SQLAlchemy、FastAPI 或管理端 DTO，负责：

- 不可变运行对象 `RuleSet`；
- 管理端配置的严格解析和规范化；
- 受支持角色及玩法能力目录；
- 配置交叉校验；
- 管理配置到运行时 `RuleSet` 的编译；
- `RuleSet` 到 canonical snapshot 的序列化；
- snapshot 到 `RuleSet` 的兼容反序列化；
- canonical JSON 与 SHA-256 内容哈希。

角色的 `team`、`model_group`、`category`、中文名称及派生 action 由服务端能力目录决定，管理端只能提交角色数量。

### 4.2 规则目录服务

规则目录服务负责：

- 草稿和修订生命周期；
- 默认规则和展示排序；
- 发布事务和并发控制；
- 管理端列表、详情和修订历史；
- C 端已发布目录；
- 规则使用量和运营告警；
- 审计所需的 before/after 摘要；
- 将持久化修订转换为领域层可执行快照。

游戏引擎、runner 和 replay 不调用规则目录服务。它们只消费已确定的快照或 `RuleSet`。

### 4.3 运行创建服务

运行创建服务负责在一个受控事务边界内：

1. 锁定稳定规则实体；
2. 确认其处于 published；
3. 比较客户端 `expected_rule_revision_id`；
4. 读取并校验当前发布修订及内容哈希；
5. 持久化 Live run 的 revision 引用和完整快照；
6. 在持久化成功后启动后台任务；
7. 将同一编译结果传给 runner。

管理端的 publish、archive、restore 和 set-default 必须锁定同一稳定规则实体，从而与开局选择形成明确的串行化边界。

### 4.4 前端边界

- `apps/admin-web` 管理草稿和发布流程；
- `packages/game-client` 定义公共目录、运行快照和创建请求契约；
- `apps/mobile-web` 读取已发布目录、选择默认规则并处理 revision 冲突；
- Live、历史和回放继续读取对局保存的规则快照，不查询当前目录。

## 5. 一期规则配置模型

### 5.1 基础字段

- `id`：3–80 个字符，匹配 `^[a-z][a-z0-9_]{2,79}$`，创建后不可修改；
- `name`：1–120 个可见字符，禁止控制字符；
- `description`：0–1000 个字符，仅用于运营和 C 端展示，不直接注入模型指令；
- `complexity`：1–40 个字符；
- `estimated_duration`：1–40 个字符；
- `rule_tags`：最多 8 项，每项 1–20 个字符，去重并保持提交顺序；
- `display_order`：非负整数；
- `is_default`：稳定规则级属性，只能由专用转换操作修改。

`display_order` 和 `is_default` 属于稳定规则实体元数据，不进入 revision 内容哈希；其余基础字段属于修订内容。

所有受管理文本字段（包括 `description`）必须先执行 NFKC 规范化，再执行 trim，规范化后的配置才是 schema-v1 canonical JSON、内容哈希和运行快照的唯一真源。官方 `starter_6.description` 固定为 `更短的官方入门局,适合快速观察模型策略。`，其 schema-v1 配置哈希固定为 `f2c52827ff3eea2725fbf2f1a01436f69c7e6465a64dec9a92bd7a07a9368f4c`，当前 legacy 完整运行快照哈希固定为 `02f31f4aa42e54f83836bf2d9b68c25291181c91a722136ed6a0a9a0e40ea4fc`。

这是有意的破坏性规范化决定：schema/canonical 一致性优先。使用全角逗号的旧 `starter_6` 配置和 legacy 快照不受支持，parser 必须拒绝，迁移和历史回填也不得将其映射到当前官方修订；通用 schema-v1 parser 和其余精确匹配的 current legacy parser 继续永久保留。

### 5.2 角色字段

管理配置使用稳定角色 ID：

- `werewolf`
- `villager`
- `seer`
- `guard`
- `witch`
- `hunter`
- `idiot`

角色数量规则：

- 所有数量必须是非负整数；
- `werewolf` 和 `villager` 最大值为 12；
- `seer`、`guard`、`witch`、`hunter`、`idiot` 只能是 0 或 1；
- `player_count` 由所有角色数量之和推导，不能由管理端单独提交；
- `player_count` 必须在 6–12；
- 至少有一名狼人和一名好人；
- 初始狼人数量必须小于初始好人数量，防止开局即满足狼人胜利条件；
- 同一角色只允许一个配置项。

编译器将稳定角色 ID 转换为现有引擎需要的中文角色名、阵营、模型分组和角色分类。

### 5.3 玩法字段

- `win_condition`：`wolves_gte_others | slaughter_side`；
- `sheriff_enabled`：布尔值；
- `sheriff_vote_weight`：`1 | 1.5 | 2`；
- `speech_policy`：`sequential | sheriff_directed`；
- `werewolf_self_explosion_enabled`：布尔值；
- `sheriff_badge_bomb_policy`：`none | double`。

交叉约束：

- `slaughter_side` 必须同时存在狼人、至少一名神职和至少一名村民；
- 警长关闭时，`sheriff_vote_weight` 必须为 1，`speech_policy` 必须为 `sequential`；
- `sheriff_directed` 只能在警长开启时使用；
- 自爆关闭时，`sheriff_badge_bomb_policy` 必须为 `none`；
- `double` 只能在自爆和警长都开启时使用；
- 未知枚举、未知角色和未知字段全部拒绝，不做默认降级。

### 5.4 派生字段

以下字段由编译器生成：

- `player_count`
- `roles: RoleSpec[]`
- `night_actions`
- `day_actions`
- `role_summary`
- `team`
- `model_group`
- `category`
- 用于模型的结构化规则文本

`night_actions` 和 `day_actions` 在一期是编译产物，不是运营输入。它们保持现有引擎执行能力和事件协议。

## 6. 数据模型

### 6.1 `rule_sets`

- `id String(80)`，主键；
- `status String(20)`：`draft | published | archived`；
- `current_published_revision_id UUID NULL`；
- `draft_revision_id UUID NULL`；
- `is_default Boolean NOT NULL DEFAULT false`；
- `display_order Integer NOT NULL DEFAULT 0`；
- `lock_version Integer NOT NULL DEFAULT 1`；
- `created_by_user_id`；
- `updated_by_user_id`；
- `archived_by_user_id NULL`；
- `created_at`；
- `updated_at`；
- `archived_at NULL`。

约束：

- `lock_version >= 1`；
- 全库最多一个 `is_default=true`；
- 默认规则必须是 published；
- draft 状态必须存在 `draft_revision_id`；
- published 状态必须存在 `current_published_revision_id`；
- archived 状态至少保留一个 current published 或 draft 指针，但不会进入 C 端目录；
- 默认规则不能单独归档，必须在同一事务中切换替代默认规则。

### 6.2 `rule_set_revisions`

- `id UUID`，主键；
- `rule_set_id String(80)`，外键，`ON DELETE RESTRICT`；
- `revision_no Integer`；
- `state String(20)`：`draft | published | superseded`；
- `schema_version Integer`，一期固定为 1；
- `content_hash String(64) NULL`，草稿允许为空，发布时必须存在；
- `lock_version Integer NOT NULL DEFAULT 1`；
- `name String(120)`；
- `description Text`；
- `player_count Integer`；
- `complexity String(40)`；
- `estimated_duration String(40)`；
- `config JSON`，保存完整规范化配置；
- `created_by_user_id`；
- `updated_by_user_id`；
- `published_by_user_id NULL`；
- `publish_reason Text NULL`；
- `created_at`；
- `updated_at`；
- `published_at NULL`。

约束：

- `(rule_set_id, revision_no)` 唯一；
- 每个规则最多一个 draft；
- 每个规则最多一个当前 published，其余发布历史为 superseded；
- published 和 superseded 修订不可更新、不可删除；
- 发布内容必须具有 canonical config、schema version 和 content hash。

### 6.3 对局关联

`live_runs` 新增：

- `rule_set_revision_id UUID NULL`
- `rule_set_revision_no Integer NULL`
- `rule_set_content_hash String(64) NULL`

保留已有 `rule_set_id` 和 `rule_set JSON`。

`game_sessions` 新增：

- `rule_set_id String(80) NULL`
- `rule_set_revision_id UUID NULL`
- `rule_set_revision_no Integer NULL`
- `rule_set_content_hash String(64) NULL`

保留已有 `rule_set JSON`。历史未知或无法精确匹配的快照允许 revision 引用为空。

## 7. 生命周期与事务语义

### 7.1 创建

- 创建稳定规则实体和 revision 1 草稿；
- 新规则不会进入 C 端目录；
- ID 从创建成功起不可变；
- 一期不提供物理删除；从未发布的规则归档时保留其草稿，恢复后回到 draft。

### 7.2 编辑

- draft 直接按 `expected_lock_version` 更新；
- published 或 archived 规则首次编辑时，从当前发布修订复制出 `revision_no + 1` 草稿；
- 管理端只更新草稿；
- 更新发布内容的请求返回冲突错误。

### 7.3 发布

发布事务必须：

1. 锁定 `rule_sets`；
2. 校验规则及草稿的 expected version；
3. 执行完整领域校验和 snapshot round-trip；
4. 生成 canonical JSON 和 SHA-256 hash；
5. 将原当前发布版改为 superseded；
6. 将草稿冻结为 published；
7. 更新当前发布指针并清空 draft 指针；
8. 将稳定规则状态改为 published；
9. 写入成功审计；
10. 原子提交。

发布 archived 规则的新草稿会同时恢复该规则。恢复旧发布版则使用独立 restore 操作。

### 7.4 归档与恢复

- 已发布规则 archive 时保留当前发布指针和所有修订；未发布规则保留草稿指针；
- archive 后不出现在 C 端目录，也不能创建新对局；
- 已运行对局不查询当前状态，因此继续运行和恢复；
- restore 不创建新修订：存在当前发布版时恢复为 published，否则恢复为 draft；
- 默认规则归档必须与替代默认规则切换在同一事务中完成。

### 7.5 设置默认

- 目标必须是 published；
- 锁定当前默认和目标规则；
- 在同一事务中清除旧默认并设置新默认；
- 更新双方 lock version；
- 记录原因和审计。

## 8. API 设计

### 8.1 管理端读取

- `GET /api/v1/admin/rule-set-options`
- `GET /api/v1/admin/rule-sets`
- `GET /api/v1/admin/rule-sets/{rule_set_id}`

列表支持：

- `q`
- `status`
- `player_count`
- `page`
- `page_size`
- `sort`

详情返回稳定规则、当前发布摘要、当前草稿、修订历史、使用量摘要和运营告警。

`rule-set-options` 返回支持角色、枚举、人数限制和字段约束，是 Admin Web 表单选项的唯一真源。

### 8.2 管理端写入

- `POST /api/v1/admin/rule-sets`
- `PATCH /api/v1/admin/rule-sets/{rule_set_id}/draft`
- `POST /api/v1/admin/rule-sets/{rule_set_id}/validate`
- `POST /api/v1/admin/rule-sets/{rule_set_id}/publish`
- `POST /api/v1/admin/rule-sets/{rule_set_id}/archive`
- `POST /api/v1/admin/rule-sets/{rule_set_id}/restore`
- `POST /api/v1/admin/rule-sets/{rule_set_id}/set-default`
- `POST /api/v1/admin/rule-sets/{rule_set_id}/duplicate`

所有写请求要求 Admin Session 和 CSRF。草稿写入要求 revision `expected_lock_version`；状态转换同时要求稳定规则和草稿的 expected version。

发布、归档、恢复和设置默认要求 3–500 个字符的原因。duplicate 创建新的稳定 ID 和 revision 1 草稿，不复制发布、默认或审计状态。

### 8.3 校验响应

`validate` 返回：

- `valid: boolean`
- `errors: {code, path, message}[]`
- `warnings: {code, path, message}[]`
- `compiled_snapshot`：仅在 valid 时返回
- `content_hash`：仅在 valid 时返回
- `rule_text_preview`：仅在 valid 时返回

错误阻止发布。玩家档案数量不足、静态语音覆盖等跨资源问题作为警告展示，运行创建仍执行自己的实时校验。

### 8.4 C 端目录与开局

保留 `GET /api/v1/games/rule-sets`，实现切换为数据库已发布目录。排序为：

1. `is_default DESC`
2. `display_order ASC`
3. `id ASC`

目录项类型为 `RuleSetCatalogItem`，至少包含：

- `id`
- `revision_id`
- `revision_no`
- 兼容字段 `version`
- `schema_version`
- `content_hash`
- `is_default`
- `name`
- `description`
- `player_count`
- `roles`
- `role_summary`
- `win_condition`
- 警长、自爆、难度、时长和标签摘要

数据库目录中的兼容字段 `version` 固定派生为 revision number 的十进制字符串，例如 revision 2 返回 `"2"`；历史已保存 snapshot 的 `version="2026.04"` 不重写。

`POST /api/v1/games/runs` 增加可选字段：

- `expected_rule_revision_id`

兼容期未提交 revision 的旧客户端使用当前 published revision，并记录兼容指标。新客户端必须提交列表中获得的 revision。

### 8.5 错误契约

- `422 rule_set_validation_failed`
- `409 rule_set_version_conflict`
- `409 rule_revision_changed`
- `409 rule_set_unavailable`
- `409 default_rule_required`
- `503 rule_set_store_unavailable`

`rule_revision_changed` 返回当前 `RuleSetCatalogItem`，供 Mobile 刷新并提示用户。数据库不可用时不回退到内存旧规则。

## 9. RBAC、CSRF 与审计

新增权限：

- `rules.read`
- `rules.write`
- `rules.publish`
- `rules.archive`
- `rules.set_default`

角色分配：

- Viewer：`rules.read`
- Operator：`rules.read`
- Content Editor：`rules.read`、`rules.write`
- Super Admin：全部规则权限

只有 Super Admin 能使配置影响新对局。前端权限控制只负责交互提示，服务端权限依赖是最终边界。

审计 action：

- `admin.rule_set.create`
- `admin.rule_set.update`
- `admin.rule_set.validate`
- `admin.rule_set.publish`
- `admin.rule_set.archive`
- `admin.rule_set.restore`
- `admin.rule_set.set_default`
- `admin.rule_set.duplicate`

成功、failure、conflict 和 rejected 都记录。审计 before/after 保存 ID、revision、status、hash 和 changed fields，不保存整份大 JSON；完整内容由不可变 revision 保存。

规则名称、描述和标签经过长度、控制字符和 Unicode 规范化。模型规则文本由结构化字段生成，description 不作为任意模型指令注入。

## 10. Admin Web 设计

新增导航 `/content/rules`。

### 10.1 列表页

展示：

- 名称和稳定 ID；
- 状态；
- 默认标记；
- 当前修订；
- 人数和角色摘要；
- 最近发布时间和更新人；
- 历史对局数；
- 是否存在未发布草稿；
- 运营告警数量。

筛选、分页和排序写入 URL。页面覆盖 loading、empty、error、forbidden 和 partial warning 状态。

### 10.2 编辑页

分为：

1. 基础信息；
2. 阵容；
3. 玩法；
4. 编译预览；
5. 修订历史。

编译预览展示：

- 最终角色与人数；
- 派生夜间/白天行动；
- 胜负条件；
- 警长和自爆有效设置；
- canonical snapshot 摘要；
- 将提供给模型的规则文本；
- 校验错误和运营告警。

页面不提供原始 JSON 编辑。409 冲突时保留本地脏表单，展示服务器当前版本，由用户选择刷新或复制内容后重试。

### 10.3 状态转换

发布、归档、恢复和默认切换使用原因确认对话框，展示影响范围。只有具备对应权限时才显示操作入口。

Admin preview mode 增加规则模块的只读 fixtures，不能模拟真实发布成功。

## 11. Mobile 与共享客户端

`packages/game-client` 将当前混用的 `RuleSetSummary` 拆为：

- `RuleSetCatalogItem`
- `RuleSetSnapshot`

`CreateGameRunRequest` 增加 `expected_rule_revision_id`。

Mobile 行为：

- 优先选择 `is_default=true`，不再依赖数组第一项表达默认；
- 规则切换继续按 `player_count` 调整座位；
- 没有专属规则图片时沿用当前无图片降级；
- 开局提交选中 revision；
- 收到 `rule_revision_changed` 时刷新目录并展示规则已更新；
- 如果人数变化，重新裁剪阵容并要求用户确认；
- 收到 `rule_set_unavailable` 时取消当前选择并回到新默认规则；
- Live、历史和回放只展示保存的 snapshot。

目录查询可保留当前 15 秒前端 stale time，revision 前置条件负责最终一致性。

## 12. 运行、恢复、回放与提示词

### 12.1 新建对局

- 开局服务确定 revision 并校验 hash；
- Live run 在后台线程启动前持久化 revision 和 snapshot；
- runner 接收编译后的 `RuleSet`，不再接收 ID 后自行查询；
- `run_params`、`GameState` 和 checkpoint 写入相同 snapshot 元数据；
- `run_created` 事件继续携带规则快照摘要。

### 12.2 恢复

- 新 checkpoint 写入 `rule_revision_id`、`rule_revision_no`、`content_hash` 和完整 snapshot；
- reader 同时接受 checkpoint schema v1 和 v2；
- v1 从 `state_at_round_start.rule_set` 恢复；
- v2 校验 snapshot hash；
- orphan reaper 走同一 snapshot 恢复逻辑；
- 当前目录状态、名称、默认项或 archived 状态不影响恢复；
- 不支持的 snapshot schema 明确失败并写入可诊断错误。

### 12.3 回放和 Admin 查询

- replay 继续以 `GameState.rule_set` 为历史展示真源；
- Admin game 列表使用 game session 的规范化 ID/revision 查询；
- Admin live 列表使用持久化 revision 元数据或 Live 快照，不再调用静态 `get_rule_set()`；
- 稳定 ID 过滤表示跨修订聚合，revision 过滤表示精确版本；
- 一期没有新增 action，现有 replay adapter 和 voice event 协议不扩展。

### 12.4 Prompt

- `render_rule_text()` 从编译后规则生成；
- 警徽票权使用实际 `sheriff_vote_weight`；
- 自爆文案使用实际 badge policy；
- 关闭警长、自爆或特殊角色时不渲染相关规则；
- action instruction 从 world state 中读取有效规则参数；
- 不允许 description 覆盖或追加任意系统指令。

## 13. 迁移与发布策略

采用 expand → switch → contract。

### 13.1 Expand

- 创建 `rule_sets` 和 `rule_set_revisions`；
- 给 Live 和 game session 增加 nullable revision/hash 字段及查询索引；
- Alembic 迁移内使用固定 JSON 导入四套当前规则；
- 四套规则均为 revision 1、published；
- `classic_8` 设置为唯一默认；
- 迁移不得 import 运行时代码常量，保证历史迁移稳定。

### 13.2 兼容部署

- 部署 snapshot v1/v2 兼容 reader；
- 部署数据库目录读取与 legacy 静态目录切换能力；
- legacy 模式仅用于显式灰度阶段；
- 数据库模式下数据库异常直接返回 503，不静默回退；
- 旧游戏继续依赖其 JSON 快照。

### 13.3 历史回填

- 从 `game_sessions.rule_set.id` 回填规范化稳定 ID；
- 仅在 canonical hash 与某个种子修订完全一致时回填 revision FK；
- 未匹配快照保留原 JSON，revision 字段保持 NULL；
- 不重写历史 snapshot 的名称、版本或内容。
- `starter_6` 仅接受上述 ASCII 逗号版本参与精确回填；旧全角逗号版本保持未匹配，不是 migration/backfill candidate。

### 13.4 Switch 与 Contract

- 切换 C 端目录和开局服务到数据库；
- 上线 Admin 管理和 Mobile revision 支持；
- 观察冲突、恢复失败和规则对局指标；
- 稳定后移除静态注册表作为运行时目录真源；
- 永久保留 legacy snapshot parser 和 v1 checkpoint reader。

## 14. 测试设计

### 14.1 领域测试

- 每条字段和组合约束的合法/非法样例；
- 未知字段、角色和枚举拒绝；
- canonical JSON 和 hash 稳定性；
- snapshot round-trip；
- 四套现有规则 golden snapshot；
- 四套现有规则的引擎行为回归。

### 14.2 数据库与服务测试

- 创建、编辑、发布、替代、归档、恢复、复制、默认切换；
- 已发布修订不可更新或删除；
- 单草稿、单当前发布版和单默认约束；
- revision 和稳定规则乐观锁；
- 并发发布、归档、开局和默认切换；
- 审计成功、失败和冲突事件。

### 14.3 API 测试

- 401、403、CSRF 和各角色权限矩阵；
- Content Editor 只能编辑草稿；
- Super Admin 发布、归档和设默认；
- 校验错误路径和稳定 Problem Details code；
- C 端只看到 published；
- revision mismatch 和 archived 规则；
- 数据库不可用返回 503；
- 兼容客户端未传 revision 的行为和指标。

### 14.4 运行与恢复测试

- API 展示 snapshot 与 engine 实际规则完全一致；
- API 选版和后台启动之间发布新修订不会产生规则漂移；
- 发布新修订后旧 checkpoint 使用旧规则恢复；
- archived 后旧对局继续运行和恢复；
- orphan recovery 使用持久化 snapshot；
- v1/v2 checkpoint；
- hash mismatch 和不支持 schema；
- Prompt 中票权、自爆和角色规则与配置一致。

### 14.5 前端与 E2E

- Admin 列表、编辑、预览、权限、确认和冲突保留脏表单；
- Mobile 默认规则、无图片降级、revision 冲突、人数变化和规则下架；
- 共享客户端目录项/快照契约；
- 创建草稿 → 发布 → 设默认 → Mobile 可见 → 创建 Live；
- 发布下一修订后，旧 Live/replay 保持旧版，新对局使用新版；
- 归档后禁止新局但历史仍可查看。

## 15. 观测与告警

新增指标：

- 规则发布成功、失败和冲突次数；
- 开局 revision 冲突次数；
- 按稳定规则 ID 和 revision number 聚合的新建、完成和失败对局；
- snapshot 解析失败次数及原因；
- checkpoint 恢复失败次数及原因；
- 未提交 expected revision 的兼容开局次数；
- published 默认规则数量。

日志只记录稳定 ID、revision number、schema version 和 hash 前缀，不记录完整规则 JSON。

告警条件：

- published 默认规则数量不等于 1；
- snapshot 解析或 hash mismatch 持续出现；
- 新修订发布后对局失败率显著高于该规则上一修订；
- legacy 无 revision 开局在兼容期结束后仍持续出现。

## 16. 开发里程碑

### 里程碑 1：领域模型与版本化目录

- 领域 schema、编译器、校验器、snapshot 和 hash；
- 数据表、迁移、四套规则种子和历史兼容；
- repository/service 和目录读取；
- 领域、迁移和服务测试。

### 里程碑 2：运行与恢复链路

- 原子选版与 Live 持久化；
- runner 接收 snapshot；
- checkpoint v2 与 v1 reader；
- orphan recovery、Admin game/live 历史语义；
- Prompt 动态规则文本；
- 运行、恢复和回放测试。

### 里程碑 3：Admin 管理能力

- Admin API、RBAC、CSRF、审计和错误契约；
- Admin 列表、编辑、预览、修订历史和转换对话框；
- preview fixtures、contract、flow 和 E2E 测试。

### 里程碑 4：C 端与灰度切换

- 共享类型拆分和 revision request；
- Mobile 默认选择、冲突和下架处理；
- 数据库目录切换、兼容指标和灰度；
- 完整跨端 E2E、观测和 runbook 更新。

## 17. 验收标准

- 当前四套规则迁移前后运行行为一致；
- 管理端无法发布引擎不支持的角色或玩法组合；
- 同一对局的目录选择、Live 展示、engine 执行、checkpoint 恢复和 replay 展示具有相同 revision/hash；
- 发布新修订或归档规则不会改变任何已启动对局；
- Content Editor 无法发布、归档或设置默认规则；
- Super Admin 的发布和状态转换均要求原因并完整审计；
- Mobile 不依赖目录顺序表达默认规则；
- Mobile 能处理 revision 变化、规则下架和人数变化；
- 历史未知快照仍可展示，能解析的 v1 checkpoint 仍可恢复；
- 数据库不可用时目录和开局明确返回 503，不使用过期内存规则；
- 生产切换后静态注册表不再是运行时规则真源。
