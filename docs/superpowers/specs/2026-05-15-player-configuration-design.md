# 玩家配置升级设计

## 目标

下一个版本把“玩家”从当前的姓名、身份、模型，升级为可配置的对局档案。创建对局时，用户可以按座位设置模型、性格和皮肤；开局后这些配置会进入 AI 决策、直播观赛、回放和恢复流程。

本版本采用“每局玩家配置 + 内置预设库”的方式，不做账号级长期档案。这样能复用现有对局创建、直播事件和回放日志结构，同时给以后添加“我的常用玩家档案”留下稳定数据形状。

## 当前上下文

后端当前使用两组模型参数：

- `CreateGameRunRequest.villager_model`
- `CreateGameRunRequest.werewolf_model`

`runner.run_game()` 把这两组模型传给 `initialize_game_state()`。`initialize_game_state()` 按规则集随机抽玩家姓名和身份，狼人阵营使用 `werewolf_model`，其他身份使用 `villager_model`，然后创建 `Player(name, role, model)`。

`Player.to_dict()` 已经把 `model` 写入状态。直播的 `game_started` 事件会发布完整玩家列表，前端 `deriveLiveSpectatorState()` 从事件中读取 `name`、`role` 和 `model`。回放与恢复则通过 `game_complete.json`、`game_partial.json`、`game_logs.json` 和 `resume_checkpoint.json` 保存这些字段。

prompt 层已经有性格入口：`prompts_zh._render_base()` 会读取 `world_state["personality"]`，但 `GameEngine._world_state()` 目前固定传空字符串。

前端大厅创建页 `CreateGameRunForm` 当前只配置规则、种子、最大轮数和演示节奏。直播舞台与座位盘当前用玩家姓名生成稳定头像样式，并展示模型文本。

## 推荐方案

新增按座位配置的 `player_configs`，并保留旧的 `villager_model` / `werewolf_model` 作为兼容默认值。

每个座位配置包含：

- `seat`: 1-based 座位号。
- `name`: 可选昵称；为空时继续使用随机姓名。
- `model`: 可选模型；为空时按身份阵营回退到旧模型默认值。
- `personality_id`: 性格预设 ID。
- `personality`: 最终进入 prompt 的性格文本。
- `skin_id`: 皮肤预设 ID。

角色仍由规则集和 seed 随机发牌。配置绑定座位和玩家姓名，不绑定预设身份。这样用户可以配置“1 号玩家用强模型、谨慎性格、红色皮肤”，但不会提前知道 1 号是什么身份。

## 数据模型

后端新增轻量数据结构：

```python
@dataclass(frozen=True)
class PlayerConfig:
    seat: int
    name: str | None = None
    model: str | None = None
    personality_id: str = "balanced"
    personality: str = ""
    skin_id: str = "default"
```

`Player` 扩展为：

```python
@dataclass
class Player:
    name: str
    role: str
    model: str
    personality: str = ""
    personality_id: str = "balanced"
    skin_id: str = "default"
```

`Player.to_dict()` 输出新字段。`checkpoint.player_from_dict()` 对旧记录缺失字段使用默认值，保证历史回放和未完成对局可以继续读取。

前端类型同步扩展：

```ts
export type PlayerConfig = {
  seat: number;
  name?: string;
  model?: string;
  personality_id?: string;
  personality?: string;
  skin_id?: string;
};

export type RawPlayer = {
  name: string;
  role: string;
  model: string;
  personality?: string;
  personality_id?: string;
  skin_id?: string;
};
```

## 创建对局 API

`POST /api/v1/games/runs` 请求新增可选字段：

```json
{
  "rule_set_id": "classic_8",
  "seed": 42,
  "max_rounds": 8,
  "event_pacing": "standard",
  "villager_model": "deepseek-chat",
  "werewolf_model": "deepseek-chat",
  "player_configs": [
    {
      "seat": 1,
      "model": "MiniMax-M2.7",
      "personality_id": "aggressive",
      "skin_id": "crimson"
    }
  ]
}
```

兼容规则：

- 不传 `player_configs` 时，行为与当前版本一致。
- `player_configs` 可以少于规则人数；缺失座位由后端补默认配置。
- `player_configs` 不能超过规则人数。
- `seat` 必须在 `1..rule_set.player_count` 内且不能重复。
- `model` 为空时，狼人身份使用 `werewolf_model`，其他身份使用 `villager_model`。
- `personality_id` 或 `skin_id` 未知时返回 422，避免前端和回放出现不可解释状态。
- `personality` 为空时由后端根据 `personality_id` 填充预设文本。

`LiveGameRun` 和 `run_created` 可以返回 `player_configs` 的规范化结果，方便前端展示本局配置摘要。`game_started` 事件必须返回每名玩家的最终 `model`、`personality_id`、`personality` 和 `skin_id`。

## 性格设计

性格是 AI 行为风格，不是规则覆盖。性格文本进入 prompt，但必须排在规则、身份、可选项和 JSON 输出约束之后理解。

内置预设先提供少量稳定选项：

- `balanced`: 稳健、根据证据推进，不轻易极端站边。
- `aggressive`: 进攻性强，主动施压、抓矛盾、推动投票。
- `cautious`: 谨慎保守，优先收集信息，避免过早暴露关键判断。
- `deceptive`: 善于混淆视听，适合狼人策略，但不改变阵营目标。
- `analytical`: 重视票型、发言顺序和行为一致性。

后端负责把预设渲染成中文 prompt 片段。前端只保存 ID 和展示文案，避免把 prompt 细节散落到 UI 里。

## 皮肤设计

皮肤只影响视觉，不影响模型调用、身份、胜负或 prompt。`skin_id` 是稳定协议字段，前端根据它渲染头像、边框、背景纹理或色彩组合。

内置皮肤先保持低风险：

- `default`: 当前按名字生成头像的兼容样式。
- `crimson`: 深红阵营感皮肤。
- `moonlit`: 冷月银蓝皮肤。
- `ember`: 琥珀火光皮肤。
- `verdant`: 暗绿色森林皮肤。

角色视觉仍然优先表达游戏信息，例如狼人红色、预言家金色、出局灰阶。皮肤作为头像底色和装饰层存在，不能盖过角色标签、发言高亮和死亡状态。

## 前端体验

大厅创建页新增“玩家配置”模块，放在官方规则详情之后或作为创建表单的第二个区域。默认使用紧凑视图，避免首屏变成重型后台表格。

交互规则：

1. 根据选中规则集的 `player_count` 生成座位配置。
2. 每个座位展示座位号、昵称输入、模型选择、性格选择和皮肤 swatch。
3. 提供“应用到全部玩家”的模型和性格快捷操作。
4. 提供“随机皮肤/性格”操作，使用当前 seed 或本地随机均可，但提交时必须是明确配置。
5. 切换规则集时，保留前 N 个座位配置，新增座位补默认配置，多余座位丢弃。
6. 提交前进行前端校验；后端仍做最终校验。

直播页和回放页：

- 座位盘和圆桌舞台使用 `skin_id` 渲染头像。
- 聚焦玩家详情展示模型和性格标签。
- 调试信息继续展示实际调用的模型。
- 历史回放缺少新字段时使用默认皮肤和均衡性格。

## 后端数据流

创建流程：

1. API 读取规则集并校验 `player_configs`。
2. 规范化配置，补齐缺失座位。
3. `LiveRunRegistry.create_run()` 保存规范化配置并发布 `run_created`。
4. 后台线程调用 `run_game(player_configs=...)`。
5. `initialize_game_state()` 先确定座位姓名，再随机发身份。
6. 每个玩家根据座位配置和身份模型回退规则生成最终 `Player`。
7. `GameEngine._world_state()` 写入 `player.personality`。
8. `game_started` 事件发布完整玩家档案。
9. save/checkpoint/resume/replay 按 `Player.to_dict()` 保存和恢复。

恢复流程：

- checkpoint 中的 state 已包含最终玩家档案，resume 不重新读取创建请求里的配置。
- `run_params` 仍保存 `player_configs`，用于运行摘要和诊断。
- 旧 checkpoint 缺少 `player_configs` 时按旧字段恢复。

## 错误处理

API 返回 422 的情况：

- `player_configs` 数量超过规则人数。
- `seat` 小于 1 或大于规则人数。
- `seat` 重复。
- `model` 非字符串或为空白字符串。
- `personality_id` 不在预设库中。
- `skin_id` 不在预设库中。
- `name` 为空白或长度超过后端限制。

模型是否有可用 provider 仍沿用当前模型调用时的错误机制。本版本不新增模型探活接口；如果某个玩家使用未注册模型，运行失败会进入现有 `game_failed` / checkpoint 恢复路径。

## 测试计划

后端测试：

- `initialize_game_state()` 在无 `player_configs` 时仍按阵营模型分配。
- 传入逐座位配置后，玩家拥有对应 `model`、`personality_id`、`personality` 和 `skin_id`。
- 模型为空时按最终身份回退到 `villager_model` 或 `werewolf_model`。
- `_world_state()` 包含当前玩家性格。
- `Player.to_dict()` 和 `player_from_dict()` 兼容新旧字段。
- `POST /runs` 接收 `player_configs` 并把规范化配置传入后台线程。
- 非法 seat、重复 seat、未知性格和未知皮肤返回 422。
- resume 使用 checkpoint 里的玩家档案，不丢失新字段。

前端测试：

- `CreateGameRunForm` 根据规则人数渲染座位配置。
- 修改座位模型、性格和皮肤后提交 payload 正确。
- 切换规则集时配置数量按人数调整。
- `deriveLiveSpectatorState()` 从 `game_started` 读取 `personality_id` 和 `skin_id`。
- 座位盘和直播舞台把 `skin_id` 映射到稳定视觉类名。
- 历史回放缺字段时不崩溃，并显示默认配置。

验证命令：

```bash
cd apps/api && uv run pytest
cd apps/web && pnpm test -- --run
cd apps/web && pnpm build
```

视觉验证：

- 启动前端开发服务器，打开 `/games` 检查玩家配置模块的桌面和移动布局。
- 创建一局带不同皮肤和性格的对局，打开 `/games/live/:runId` 检查直播座位盘和聚焦详情。

## 非目标

- 不做账号系统里的长期玩家档案。
- 不新增模型供应商管理页面。
- 不做模型 API key 配置 UI。
- 不改变狼人杀规则、发牌逻辑、胜负条件或行动 schema。
- 不把皮肤写入 prompt。
- 不要求历史回放补写新字段。

## 自查

- 设计聚焦在每局玩家配置，没有拆成账号档案、模型管理和规则编辑多个子系统。
- 新字段都有默认值，旧对局、旧 checkpoint 和旧前端请求可兼容。
- 性格、模型、皮肤的职责边界清晰：模型控制调用，性格控制 prompt 风格，皮肤控制展示。
- API 校验规则明确，没有留未定项。
- 测试计划覆盖后端协议、运行时行为、恢复流程、前端提交和直播展示。
