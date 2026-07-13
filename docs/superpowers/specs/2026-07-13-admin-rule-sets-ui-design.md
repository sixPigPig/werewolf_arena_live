# Admin 游戏规则配置入口设计

日期：2026-07-13  
状态：已确认，待实施

## 背景

系统已经具备数据库规则目录、不可变修订、发布与默认切换、历史用量、审计、并发版本控制和生产切换保护，但 Admin Web 尚未提供对应入口。当前运营人员只能通过 API 管理规则，不满足“由管理端配置规则”的完整目标。

本设计补齐 Admin Web 规则管理能力。页面复用现有 `/api/v1/admin/rule-sets*` API 和 RBAC，不改变规则目录、运行时快照或历史兼容协议。

## 目标

- 在 Admin 的“内容资产”分组增加“游戏规则”入口。
- 让运营人员通过结构化表单完成规则创建、复制、草稿编辑、服务端校验、发布、默认切换、归档和恢复。
- 展示规则文本预览、校验错误与警告、稳定规则用量、历史修订及每个修订的使用量。
- 使用服务端 lock version 防止并发覆盖，并保持所有高风险操作的原因、CSRF、RBAC 和审计约束。
- 页面不暴露原始规则 JSON、内部异常、SQL、玩家隐私或历史对局快照。

## 非目标

- 不新增原始 JSON 编辑模式。
- 不在浏览器复制后端规则编译、hash 或最终合法性判断。
- 不修改公开规则目录、开局快照固定、checkpoint 或历史兼容 reader。
- 不实现拖拽排序；展示顺序使用非负整数输入。
- 不提供删除规则能力；生命周期仍是草稿、已发布和已归档。

## 信息架构

### 导航

在 `apps/admin-web/src/app/admin-navigation.ts` 的“内容资产”分组增加：

- 标识：`rules`
- 标签：`游戏规则`
- 描述：`阵容、流程与发布版本`
- 路径：`/content/rules`
- 权限：`rules.read`

### 路由

- `/content/rules`：规则列表。
- `/content/rules/new`：新建规则。
- `/content/rules/:ruleSetId`：规则详情与编辑。

路由使用现有 `AdminSessionBoundary` 和 `RequireAdminPermission`。列表、详情和新建入口至少要求 `rules.read`；写按钮再按细分权限禁用或隐藏。直接访问无权限路由进入现有 403 页面。

## 页面设计

### 规则列表

列表展示：

- 规则名称和稳定规则 ID；
- 状态：草稿、已发布、已归档；
- 默认规则标记；
- 当前发布修订和草稿修订；
- 玩家人数与角色摘要；
- 展示顺序；
- 更新时间。

列表支持：

- 名称或规则 ID 搜索；
- 状态筛选；
- 服务端排序；
- 服务端分页；
- 空状态、加载失败和显式重试；
- 新建规则、复制现有规则、进入详情。

复制操作要求填写新的规则 ID 和名称。复制成功后进入新规则详情，不修改来源规则。

### 规则编辑页

编辑页采用结构化表单，不提供原始 JSON 输入。

基础信息区域：

- 稳定规则 ID：仅新建时可填写，创建后只读；
- 名称；
- 描述；
- 复杂度；
- 预计时长；
- 标签；
- 展示顺序。

阵容区域按照服务端 options 返回的角色顺序渲染数量输入：狼人、村民、预言家、守卫、女巫、猎人和白痴。页面实时显示玩家总数和角色摘要，但最终合法性由服务端校验决定。

规则区域：

- 胜利条件；
- 是否启用警长；
- 警长票权；
- 发言规则；
- 是否允许狼人自爆；
- 自爆时警徽处理策略。

警长关闭时，前端将警长票权和警徽策略归一到服务端接受的安全值，并禁用无意义控件。控件选项全部来自 `/api/v1/admin/rule-set-options`，避免前后端枚举漂移。

页面右侧或窄屏下方展示：

- 当前状态、默认标记、修订号和 content hash 前缀；
- 稳定规则累计 game/live 用量；
- 最近一次服务端校验的错误和警告；
- 校验通过后的规则文本预览；
- 保存、校验和发布门禁说明。

页面底部展示最多 50 条历史修订，包含修订号、状态、发布时间、发布人、hash 前缀、game/live 用量。历史配置只读展示，不允许把旧修订直接改写为当前修订。

## 生命周期操作

### 保存草稿

- 新建规则调用 `POST /api/v1/admin/rule-sets`。
- 已有规则调用 `PATCH /api/v1/admin/rule-sets/{ruleSetId}/draft`。
- 更新请求携带最新 `expected_rule_set_lock_version` 和 `expected_revision_lock_version`。
- 保存成功后更新本地 baseline、query cache 和版本号，页面不再标记为未保存。

### 校验

- 只有已保存且存在草稿修订时才能调用 `POST /validate`。
- 校验请求携带草稿 revision lock version。
- 错误按 `path` 映射到字段并在汇总区同时展示；警告不阻止继续编辑或保存。
- `valid=true` 时展示服务端生成的规则文本预览和 content hash。
- 任意字段发生变化后，之前的校验结果失效，必须重新保存并校验。

### 发布

发布按钮仅在以下条件全部满足时启用：

- 用户拥有 `rules.publish`；
- 当前表单无未保存修改；
- 当前草稿已经通过服务端校验；
- 校验对应当前 revision lock version；
- 用户在确认弹窗中填写长度合规的操作原因。

发布调用 `POST /publish`，携带 rule set 和 revision 两个 lock version。成功后重新读取详情和列表。

### 设置默认、归档和恢复

- 设置默认要求 `rules.set_default`，并携带目标规则及前一默认规则的 lock version。
- 归档要求 `rules.archive`。若归档当前默认规则，确认弹窗必须选择替代的已发布规则并携带替代规则 lock version。
- 恢复要求 `rules.archive`，恢复后规则回到服务端定义的可编辑生命周期。
- 所有操作必须填写原因，成功后刷新详情、列表及相关 query cache。

## 权限模型

Admin Web 的 `AdminPermission` 增加：

- `rules.read`
- `rules.write`
- `rules.publish`
- `rules.archive`
- `rules.set_default`

权限行为：

- `rules.read`：导航、列表、详情、历史与用量；
- `rules.write`：新建、复制、修改和保存草稿；
- `rules.publish`：发布；
- `rules.archive`：归档与恢复；
- `rules.set_default`：设置默认。

前端权限只用于交互收敛；后端依然是最终授权边界。

## 前端模块边界

新增 `apps/admin-web/src/features/rule-sets/`：

- `types.ts`：前端领域类型和 API DTO；
- `parsers.ts`：严格解析服务端响应，拒绝缺字段、错误枚举和非预期敏感字段；
- `api.ts`：只负责 HTTP 请求与请求 DTO；
- `query-keys.ts`：列表、详情和 options query key；
- `form.ts`：表单映射、即时校验、字段错误映射和 dirty 比较；
- `RuleSetsPage.tsx`：列表、筛选、分页和复制入口；
- `RuleSetEditorPage.tsx`：结构化编辑器、校验预览、用量和历史修订；
- `RuleSetTransitionDialog.tsx`：发布、默认切换、归档和恢复确认。

路由懒加载定义继续集中在现有 `routes/lazy-pages.tsx` 和 `routes/definitions.tsx`。样式复用现有 Admin token 和 CSS 组件，不引入新的 UI 或表单依赖。

## 状态与错误处理

- 使用 TanStack Query 管理 options、列表和详情缓存。
- 表单 baseline 使用服务端最新响应建立；dirty 状态触发现有 `useBlocker` 和 `useBeforeUnload` 离开保护。
- 409/412 或版本冲突 Problem Details 不覆盖本地草稿，展示“重新加载最新版本”操作。
- 404 显示规则不存在或已移除。
- 422 校验错误映射到字段与汇总区。
- 503 显示规则目录暂不可用并提供重试，不使用静态数据兜底。
- 高风险操作 pending 期间禁用重复提交。
- 页面不渲染原始异常、SQL、完整 snapshot、玩家信息或 revision UUID；只显示服务端允许的稳定字段和 hash 前缀。

## 可访问性与响应式

- 所有输入具有显式 label、说明和字段级错误关联。
- 弹窗具备标题、描述、焦点进入和取消路径；危险操作按钮使用明确文案。
- 状态不能只依赖颜色，必须同时显示文字。
- 表格在窄屏转换为可读卡片或允许受控横向滚动；编辑页右侧摘要在窄屏移动到表单下方。
- 所有操作可通过键盘完成，loading 和错误状态使用可被辅助技术读取的文本。

## 测试策略

采用测试驱动开发，每项生产行为先写失败测试。

### 单元与契约测试

- DTO parser 接受合法响应并拒绝错误状态、错误类型、缺少 lock version、完整 snapshot 或其他非预期字段。
- 表单映射、人数计算、即时校验、警长字段归一和服务端 path 错误映射。
- API 方法的 URL、method、CSRF、body 和 Problem Details 传播。

### 页面流程测试

- 导航项按 `rules.read` 显示，路由权限正确。
- 列表搜索、筛选、排序、分页、空状态和错误重试。
- 新建、编辑、复制和未保存离开保护。
- 保存后校验、字段修改使校验失效、校验错误/警告及规则文本预览。
- 无有效服务端校验时不能发布。
- 发布、默认切换、归档、替代默认规则选择和恢复。
- 409/412 冲突保留本地输入并支持重新加载。
- 只读用户可查看但不能执行写操作。

### 回归验证

- Admin Web 全量 Vitest、TypeScript build 和 ESLint。
- API 现有 Admin rule-set 契约测试保持通过。
- 路由、导航和权限快照不影响玩家、语音、运行、对局和系统安全页面。

## 完成标准

- 拥有 `rules.read` 的用户可以从“内容资产 → 游戏规则”进入列表和详情。
- 相应权限用户可以完成规则的完整管理生命周期，无需直接调用 API。
- 页面只允许发布当前已保存且服务端校验通过的草稿。
- 并发冲突不会覆盖其他管理员的修改。
- 历史修订、用量和规则文本预览可见，但原始 snapshot 和敏感数据不可见。
- Admin Web 全量测试、构建、lint 和后端规则 API 回归均通过。
