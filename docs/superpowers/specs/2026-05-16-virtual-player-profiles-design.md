# 可复用虚拟玩家档案库设计

## 目标

把当前“每局玩家配置”的构想升级为可保存、可复用的虚拟玩家档案库。用户可以提前创建虚拟玩家，设置模型、性格和人物形象；创建对局时按座位选择这些档案；开局后系统把档案解析成本局玩家快照，进入 AI 决策、直播观赛、回放和恢复流程。

第一版采用“全局虚拟玩家库”，不强依赖登录账号。数据库表预留 `owner_user_id`，后续接入账号系统时可以自然变成用户私有档案。已经开局的对局永远使用开局时的玩家快照，不受之后编辑档案影响。

## 当前上下文

后端已有 SQLAlchemy、Alembic 和 `users` 表基础，但没有虚拟玩家持久化模型。狼人杀运行数据主要由创建请求、内存中的 live registry、日志文件和 resume checkpoint 承载。

当前玩家运行模型仍然较轻：

- 创建对局请求只有 `villager_model` 和 `werewolf_model` 两个默认模型。
- `initialize_game_state()` 随机选择玩家姓名，随机发身份，再按身份阵营分配模型。
- `Player` 目前输出 `name`、`role`、`model` 等运行状态字段。
- `prompts_zh._render_base()` 已经能读取 `world_state["personality"]`，但 `GameEngine._world_state()` 现在固定传空字符串。
- 前端创建页只配置规则、种子、最大轮数和演示节奏。
- 直播和回放页面从 `game_started` / replay state 读取玩家列表，并展示姓名、身份、模型和状态。

已有 `2026-05-15-player-configuration-design.md` 设计了“本局按座位配置模型、性格、皮肤”。本设计继承那条运行链路，但新增可保存的档案实体和档案管理体验。

## 推荐方案

新增“虚拟玩家档案库 + 对局玩家快照”两层模型。

虚拟玩家档案是可编辑的长期配置：

- 昵称。
- 模型。
- 性格预设 ID。
- 性格文本。
- 人物形象 ID。
- 头像或形象 prompt。
- 标签。
- 可选用户归属。

对局玩家快照是开局时冻结下来的配置：

- 座位号。
- 来源档案 ID。
- 开局时的昵称、模型、性格、形象和标签。

创建对局时，用户可以给每个座位选择一个已保存档案，也可以对本局做临时覆盖。后端会把档案和覆盖项规范化成 `player_configs` 快照，然后交给狼人杀引擎。角色仍由规则集和 seed 随机发牌，虚拟玩家档案不绑定身份。

## 备选方案

### 方案 A: 只做每局临时玩家配置

优点是实现最短，不需要数据库和档案管理页面。缺点是用户每次都要重新配置模型、性格和形象，无法沉淀常用玩家，不满足“可保存、可复用”的目标。

### 方案 B: 只做阵容模板

优点是创建对局最快，用户可以一键加载 8 人或 12 人阵容。缺点是单个虚拟玩家不能独立复用，编辑和组合会更复杂。阵容模板更适合作为第二阶段能力。

### 方案 C: 虚拟玩家档案库，创建对局时按座位选用

这是推荐方案。它先打稳最小复用单元：单个虚拟玩家。以后可以自然增加阵容模板，把多个档案组合成固定阵容。

## 后端数据模型

新增 SQLAlchemy 模型 `VirtualPlayerProfile`，对应表 `virtual_player_profiles`。

建议字段：

```python
class VirtualPlayerProfile(Base):
    __tablename__ = "virtual_player_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    personality_id: Mapped[str] = mapped_column(String(40), nullable=False, default="balanced")
    personality_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appearance_id: Mapped[str] = mapped_column(String(40), nullable=False, default="default")
    avatar_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

`owner_user_id` 第一版写入 `NULL`。这样当前应用不需要登录也能工作；后续有账号体系后可以按用户过滤，同时兼容已有全局档案。

运行时新增轻量数据结构：

```python
@dataclass(frozen=True)
class PlayerConfig:
    seat: int
    profile_id: str | None = None
    name: str | None = None
    model: str | None = None
    personality_id: str = "balanced"
    personality: str = ""
    appearance_id: str = "default"
    avatar_prompt: str = ""
    tags: tuple[str, ...] = ()
```

`Player` 扩展：

```python
@dataclass
class Player:
    name: str
    role: str
    model: str
    personality_id: str = "balanced"
    personality: str = ""
    appearance_id: str = "default"
    avatar_prompt: str = ""
    profile_id: str | None = None
    tags: list[str] = field(default_factory=list)
```

`Player.to_dict()` 输出这些字段。`checkpoint.player_from_dict()` 对旧记录缺失字段使用默认值，保证历史回放和未完成对局能继续读取。

## API 设计

新增档案管理接口：

- `GET /api/v1/player-profiles`
- `POST /api/v1/player-profiles`
- `GET /api/v1/player-profiles/{profile_id}`
- `PATCH /api/v1/player-profiles/{profile_id}`
- `DELETE /api/v1/player-profiles/{profile_id}`

`GET` 返回按 `updated_at desc` 排序的档案列表。第一版不分页；如果档案数量未来变大，再加 `limit` 和 `cursor`。

复制档案不新增专门接口。前端读取原档案后，用相同字段调用 `POST /api/v1/player-profiles` 创建副本，并把名称改成用户可区分的新名称。

创建请求示例：

```json
{
  "display_name": "冷静的阿夜",
  "model": "MiniMax-M2.7",
  "personality_id": "cautious",
  "personality_text": "谨慎保守，优先收集信息，避免过早暴露关键判断。",
  "appearance_id": "moonlit",
  "avatar_prompt": "银发、冷静、观察型玩家，冷月银蓝色调",
  "tags": ["控场", "慢热"]
}
```

创建对局接口 `POST /api/v1/games/runs` 新增可选字段 `player_configs`：

```json
{
  "rule_set_id": "classic_8",
  "seed": 42,
  "max_rounds": 8,
  "villager_model": "deepseek-v4-flash",
  "werewolf_model": "deepseek-v4-flash",
  "player_configs": [
    {
      "seat": 1,
      "profile_id": "0f4cfad8-4a98-4557-a28c-1c0f5e74e1d4"
    },
    {
      "seat": 2,
      "profile_id": "c39acdc7-4271-4ad3-a4a3-966b8f284dd4",
      "model": "qwen3.6-plus"
    }
  ]
}
```

规范化规则：

- `profile_id` 存在时，后端读取档案作为基础值。
- 同一座位同时传入 `profile_id` 和覆盖字段时，覆盖字段只影响本局快照，不修改档案。
- 不传 `player_configs` 时保持当前行为。
- 可以只配置部分座位；缺失座位由后端补默认随机玩家。
- `seat` 必须在 `1..rule_set.player_count`，且不能重复。
- `profile_id` 不存在返回 422。
- `display_name` / `name` 去除首尾空白后不能为空，最长 80 字符。
- `model` 去除首尾空白后不能为空，最长 120 字符。
- `personality_id` 必须存在于后端预设库。
- `appearance_id` 必须存在于后端预设库。
- `tags` 第一版最多 8 个，每个最长 20 字符。

`LiveGameRun.to_summary()` 和 `run_created` 事件返回规范化后的 `player_configs`，用于前端在直播页或运行详情里展示本局配置摘要。

## 性格和形象预设

后端维护稳定预设注册表，前端只使用 ID 和展示文案。

性格预设第一版：

- `balanced`: 稳健、根据证据推进，不轻易极端站边。
- `aggressive`: 主动施压、抓矛盾、推动投票。
- `cautious`: 谨慎保守，优先收集信息，避免过早暴露关键判断。
- `deceptive`: 善于混淆视听，适合狼人策略，但不改变阵营目标。
- `analytical`: 重视票型、发言顺序和行为一致性。

形象预设第一版：

- `default`: 当前按名字生成头像的兼容样式。
- `crimson`: 深红阵营感。
- `moonlit`: 冷月银蓝。
- `ember`: 琥珀火光。
- `verdant`: 暗绿色森林。

`personality_text` 是最终进入 prompt 的文本。创建或更新档案时，如果用户没有自定义性格文本，后端用 `personality_id` 填充默认文本。`appearance_id` 和 `avatar_prompt` 只影响视觉展示，不进入 prompt。

## 游戏运行数据流

创建流程：

1. 前端读取虚拟玩家档案列表。
2. 用户在创建对局页为座位选择档案或临时覆盖字段。
3. API 校验规则集和 `player_configs`。
4. API 从数据库读取 `profile_id` 对应档案。
5. API 合并档案和本局覆盖项，生成完整座位快照。
6. `LiveRunRegistry.create_run()` 保存快照并发布 `run_created`。
7. 后台线程调用 `run_game(player_configs=...)`。
8. `initialize_game_state()` 按座位快照确定玩家姓名、模型、性格和形象，再随机发身份。
9. 每个玩家最终模型规则为：座位快照模型优先；否则狼人身份使用 `werewolf_model`；其他身份使用 `villager_model`。
10. `GameEngine._world_state()` 写入 `player.personality`。
11. `game_started` 发布完整玩家档案。
12. 日志、回放和 resume checkpoint 通过 `Player.to_dict()` 保存最终快照。

恢复流程：

- resume 使用 checkpoint 中的 `state_at_round_start.players`，不重新读取数据库档案。
- `run_params` 继续保存 `player_configs` 快照，便于诊断。
- 如果某个虚拟玩家档案后来被编辑或删除，旧对局恢复仍按 checkpoint 里的快照继续。

## 前端体验

新增“虚拟玩家库”页面或面板，入口放在对局大厅附近。第一版以列表和编辑抽屉为主，不做复杂人物资产工作台。

档案库能力：

- 查看所有虚拟玩家。
- 创建档案。
- 编辑档案。
- 复制档案。
- 删除档案。
- 按名称或标签快速过滤。

### 玩家库布局参考

根据后续参考图，`/players` 的默认浏览态采用“左侧筛选栏 + 右侧玩家卡片矩阵”的布局，而不是三栏编辑工作台。

桌面端结构：

- 外层使用沉浸式暗色哥特边框容器，页面主视觉应接近一张“虚拟玩家名册”，避免营销页和大面积说明文案。
- 顶部主操作只保留在全局导航栏，包含“新建虚拟玩家”和“返回大厅”。玩家库内容区不再重复放置“新建虚拟玩家”按钮。
- 左侧筛选栏固定在主容器内，宽度约 160 到 200 像素，标题为“虚拟玩家库”，依次放搜索、模型筛选、性格筛选、排序或筛选方式，以及“只看收藏”按钮。
- 右侧为卡片网格，桌面优先 3 列；宽屏可以保持 3 列并限制单卡最大宽度，避免卡片被拉得过长。卡片间距紧凑但必须留出清晰边界。
- 移动端先显示顶部操作和筛选折叠入口，再用单列卡片列表；筛选栏收起为抽屉或折叠区，不占据首屏宽度。

玩家卡片结构：

- 卡片采用固定高度或稳定最小高度，保持整齐矩阵，不因标签数量或按钮 hover 导致布局跳动。
- 左侧为圆形头像或系统头像，右侧上方为玩家昵称，过长时单行截断。
- 昵称旁或右上角展示性格、策略或收藏状态的短徽标。徽标文字必须短，不挤压昵称。
- 模型使用次级小字展示，例如 `deepseek-v4-flash`。
- 标签、简介和策略摘要最多展示 2 到 3 行，超出省略，不把卡片撑高。
- 底部固定三个操作：“编辑”“复制”“删除”。操作按钮大小一致，移动端允许换行但不能相互重叠。
- 选中或 hover 时只强化边框、阴影或角标，不改变卡片尺寸。

编辑体验：

- 默认浏览态只展示筛选栏和卡片网格。
- 点击导航栏“新建虚拟玩家”或卡片“编辑”后，打开超大弹窗承载完整编辑器；默认页面不能长期拆成“列表 + 编辑器 + 预览”三栏。
- 保存或取消后返回卡片矩阵，并保留当前搜索、筛选和排序状态。

创建对局页新增“虚拟玩家”模块：

- 根据选中规则集的 `player_count` 生成座位。
- 每个座位可以选择档案。
- 展示档案名称、模型、性格标签和形象 swatch。
- 支持本局临时覆盖模型、性格或形象。
- 支持清空座位配置。
- 支持“随机填充空座位”，从档案库中选择未使用档案。
- 切换规则集时保留前 N 个座位配置，多余座位移除，新增座位为空。

直播和回放展示：

- 座位盘和圆桌舞台根据 `appearance_id` 渲染头像底色、边框或纹理。
- 聚焦玩家详情展示模型、性格和档案来源。
- 回放玩家列表展示当局快照，不跳转依赖当前档案状态。
- 历史回放缺少新字段时使用默认性格和默认形象。

## 错误处理

档案 API 返回 422 的情况：

- 昵称为空或超过 80 字符。
- 模型为空或超过 120 字符。
- 未知 `personality_id`。
- 未知 `appearance_id`。
- `avatar_prompt` 超过 500 字符。
- 标签数量超过 8 个，或单个标签超过 20 字符。

创建对局 API 返回 422 的情况：

- `player_configs` 数量超过规则人数。
- `seat` 越界或重复。
- `profile_id` 不存在。
- 覆盖字段不合法。
- 规范化后某个座位的模型为空。

模型是否有可用 provider 仍沿用当前模型调用时的错误机制。第一版不新增模型探活接口；如果某个虚拟玩家使用未注册模型，运行失败会进入现有 `game_failed` 和 checkpoint 恢复路径。

## 数据迁移和兼容

新增 Alembic 迁移创建 `virtual_player_profiles` 表和索引。

兼容策略：

- 旧创建对局请求不传 `player_configs` 时行为不变。
- 旧 replay state 缺少新字段时前端显示默认性格和默认形象。
- 旧 checkpoint 缺少新字段时后端恢复为默认值。
- 已保存档案被删除后，旧对局不受影响，因为运行日志和 checkpoint 保存的是快照。

第一版可以在迁移后写入 5 个示例虚拟玩家档案作为种子数据，也可以只由前端空状态引导创建。推荐不在迁移里写业务示例数据，避免测试和生产环境出现意外默认档案；前端用空状态引导即可。

## 测试计划

后端测试：

- Alembic 迁移创建 `virtual_player_profiles`。
- 档案 CRUD 能创建、读取、更新和删除档案。
- 复制档案通过读取原档案后调用创建接口完成，不需要专门 copy API。
- 档案校验覆盖空名称、未知性格、未知形象和过长标签。
- `POST /games/runs` 接收 `profile_id` 并规范化为本局快照。
- 本局覆盖字段不修改原档案。
- `initialize_game_state()` 使用座位快照生成玩家字段。
- 模型为空时按最终身份回退到阵营默认模型。
- `_world_state()` 包含当前玩家性格文本。
- `Player.to_dict()` 和 `player_from_dict()` 兼容新旧字段。
- resume 使用 checkpoint 中的玩家快照，不重新读取数据库档案。

前端测试：

- 档案列表展示空状态和已有档案。
- `/players` 默认浏览态展示左侧筛选栏和右侧 3 列玩家卡片网格。
- 玩家卡片展示头像、昵称、模型、短标签和编辑、复制、删除操作。
- 创建、编辑、删除档案调用正确 API。
- 复制档案调用创建接口生成副本。
- 创建对局页按规则人数渲染座位选择器。
- 选择档案后提交 payload 包含 `profile_id`。
- 临时覆盖模型或性格后提交 payload 包含覆盖字段。
- 切换规则集时座位配置数量正确调整。
- `deriveLiveSpectatorState()` 读取 `personality_id` 和 `appearance_id`。
- 直播座位盘和回放玩家列表缺字段时不崩溃。

验证命令：

```bash
cd apps/api && uv run pytest
cd apps/web && pnpm test -- --run
cd apps/web && pnpm build
```

视觉验证：

- 启动前端开发服务器，打开 `/games` 检查虚拟玩家库入口和创建对局模块。
- 打开 `/players`，确认首屏符合参考图的左筛选栏、右卡片矩阵、右上角主操作布局。
- 在桌面宽度确认玩家卡片稳定为 3 列，头像、徽标、模型、标签和底部操作不重叠。
- 在移动宽度确认筛选区折叠或纵向排列，卡片单列展示且按钮文字不溢出。
- 创建至少 3 个虚拟玩家档案，分别设置不同模型、性格和形象。
- 用这些档案发起一局对局，打开 `/games/live/:runId` 检查直播座位盘和聚焦玩家详情。
- 完成或中断对局后打开回放，确认玩家快照和直播展示一致。

## 非目标

- 第一版不做阵容模板。
- 第一版不做头像图片生成和图片上传。
- 第一版不做模型 API key 配置 UI。
- 第一版不做模型可用性探活。
- 第一版不把人物形象写入 prompt。
- 第一版不改变狼人杀规则、发牌逻辑、胜负条件或行动 schema。
- 第一版不要求历史回放补写新字段。

## 后续扩展

后续可以在这个基础上增加：

- 阵容模板：把多个虚拟玩家档案保存成 6 人、8 人或 12 人阵容。
- 用户私有档案：启用 `owner_user_id` 过滤。
- 档案导入导出：分享虚拟玩家 JSON。
- 头像生成：根据 `avatar_prompt` 生成静态头像或动效头像。
- 模型健康检查：提前提示某个档案的模型不可用。

## 自查

- 设计满足“可保存、可复用”，并保留开局快照，避免档案编辑影响历史对局。
- 全局档案库不阻塞未来账号系统，`owner_user_id` 已预留。
- 档案、对局快照和运行时玩家职责边界清晰。
- 性格进入 prompt，形象只影响视觉，模型只控制 provider 调用。
- 错误处理、兼容策略和测试范围覆盖 API、运行时、恢复、直播和回放。
