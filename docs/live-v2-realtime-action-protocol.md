# Live V2 实时动作与能力驱动直播协议

> 状态：开场、首夜和首日开场已经通过历史验收。2026-07-23 用户明确授权完整对局工作包；具备可执行冻结能力快照的 6–12 人新对局现在从首个观众 ready 开始，连续执行每个实时模型动作、同源 TTS、语音保存、夜晚、白天、警长、投票、死亡响应和胜负结算，直到 `game_completed` 或明确 `failed`。无完整能力快照的预览对局仍保留原两句停点。

## 1. 已验收基础切片（历史）

打通一个可以由用户亲自观察的最小垂直切片：

> Mobile 用户点击进入实时观赛后，服务端先正式开局，再实时请求模型生成法官开场句，完成实时 TTS、官方音频时钟和独立语音保存；确定性地把阶段从 `opening` 推进到 `first_night` 后，再发起第二次真实模型与 TTS 请求，生成“天黑请闭眼”性质的入夜播报并保存第二份语音资产。此处描述的是已经验收的基础停点；当前扩大切片由第 17、18 节继续推进。

两句话都不读取静态 `game_intro`，也不从旧对局、旧直播或 Replay 中获取。旧 V2 对局统一标记为 `legacy / legacy_frozen`，不得在升级后续跑本切片。

## 2. 基础切片当时明确不做（历史）

- 不开始第三句话或第三个动作。
- 普通直播不公开任何玩家身份或阵营；上帝视角可以读取已经冻结的全部身份。
- 不实现投票、技能或胜负结算。
- 不接收、存储、聚合真实弹幕，只固定弹幕影响输入接口。
- 不实现 Replay、追播、暂停、倍速、Seek 或历史音频补发。
- 不实现模型重试、备用模型或 TTS 备用供应商；失败后明确停止。
- 不唤醒狼人，不产生狼人相认、商议、选刀或任何首夜秘密动作。
- 不提交或推送代码。

## 3. 不复用边界

V2 只允许共享框架和运行基础设施：FastAPI、SQLAlchemy、数据库连接、第三方 SDK，以及密钥、Endpoint 等环境配置值。

V2 不导入、不包装以下旧业务实现：

- 旧游戏规则编排、领域类型和持久化 repository。
- 旧模型调用和 provider 编排。
- 旧 streaming、speech gate 和文本补救逻辑。
- 旧 TTS materializer、voice stream 和 speech delivery。
- 旧 Live director、timeline、播放 ACK、补播和抢占逻辑。
- Replay 的 cursor、audio clock 和 `holdAdvance`。
- 旧 Mobile/Admin 的游戏类型、parser、API、状态 hook 和 UI 组件。

下一步必须增加导入边界测试；V2 一旦导入上述旧业务模块，测试直接失败。把旧实现复制、改名或轻微改写后放入 V2 目录同样属于复用，不允许用路径变化绕过门禁。

## 4. 责任划分

| 组件 | 唯一责任 | 不得负责 |
| --- | --- | --- |
| V2 Action Engine | 严格串行驱动两个已批准动作 | 播放历史、等待客户端 ACK、自由决定规则阶段 |
| V2 Model Client | 发起一次真实模型流并返回增量 | 决定游戏规则、公开原始 token |
| V2 Response Decoder | 提取完整非空播报文本；玩家决策只解析必需字段 | 评价句数、标点、长度、引号、Markdown、换行或表达风格 |
| V2 TTS Client | 把已确认的完整发言转换为流式 PCM | 决定展示顺序 |
| V2 Live Broadcaster | 建立官方音频时钟并广播当前内容 | 读取数据库历史追播 |
| V2 Voice Recorder | 顺序保存广播所用的同一份 PCM，并原子完成语音资产 | 调整广播顺序、触发补播、向公开直播暴露历史音频 |
| V2 Repository | 保存动作证据和当前投影 | 充当直播播放队列 |
| Mobile V2 Client | 消费当前快照和未来帧并播放 PCM | 推动全局游戏、请求缺失历史块 |

规则推进仍然是确定性代码。大模型负责动作中的内容或选择；规则合法性、阶段转换、胜负判断不能由模型自由决定。

## 5. 身份与序列

本切片使用以下稳定标识：

- `game_id`：V2 对局。
- `run_id`：本次运行。
- `action_id`：一次实时模型动作。
- `presentation_seq`：全场唯一且单调递增的公开展示序列。
- `presentation_id`：一个公开展示单元。
- `speech_id`：一次发言；未来可以包含多个句段。
- `segment_index`：发言内句段序号，从 0 递增。
- `chunk_index`：一个句段内的音频块序号，从 0 递增。
- `voice_asset_id`：一段已保存 V2 语音资产；第一切片与 segment 一一对应。
- `record_seq`：持久化审计序号，只用于记录，不作为直播 cursor。
- `phase_seq`：确定性游戏阶段序号；新对局从 1 开始，入夜时原子递增为 2。

基础切片恰好有两个 action、两个 speech、两个 presentation、两个 segment 和两份 voice asset；`presentation_seq` 必须严格为 1、2。首夜扩大切片的实际数量由能力计划和响应激活决定，不能继续写死为两个。

创建自现有大厅的 V2 对局还会生成一个独立的 `assignment_id`。服务端使用全新的私密随机种子，依据冻结的玩家与角色快照确定性洗牌，并在创建对局的同一数据库事务中写入：

- `v2_role_assignment_batches`：只保存私密种子、身份结果摘要和人数。
- `v2_role_assignments`：按座位保存 `player_id`、角色和阵营。
- `roles_assigned`：只记录 `assignment_id`、分配人数和 `private_sealed` 可见性，不记录座位身份内容。

这些记录不进入普通 Live snapshot，也不通过 Mobile 自行隐藏。直接创建、没有大厅快照的旧式 V2 测试对局保持 `unavailable`，不会伪造身份。

## 6. ActionContext 与弹幕影响预留

每一次模型请求都必须由 Action Engine 生成独立的 `ActionContext`。开场动作结构为：

```json
{
  "schema_version": 1,
  "action_id": "v2_action_...",
  "action_type": "judge_opening_speech",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "phase_id": "opening",
  "actor": {
    "kind": "judge",
    "id": "judge"
  },
  "objective": "生成本场直播的法官开场播报",
  "output_contract": {
    "kind": "public_speech",
    "language": "zh-CN"
  },
  "influence": {
    "schema_version": 1,
    "status": "disabled",
    "captured_at": null,
    "strength": 0,
    "signals": []
  }
}
```

入夜动作必须创建新的 `action_id`，并把以下字段替换为：

```json
{
  "action_type": "judge_nightfall_announcement",
  "phase_id": "first_night",
  "objective": "生成宣布本局进入首夜并提醒所有玩家闭眼的法官播报"
}
```

本步的 `influence` 只能是上述禁用值。未来弹幕系统只能生产这个字段，不能绕过 Action Engine 直接修改规则、提示词、展示状态或音频队列。

## 7. 服务端状态机

### 7.1 动作状态

| 当前状态 | 唯一输入 | 动作 | 下一状态 | 对外表现 |
| --- | --- | --- | --- | --- |
| `waiting_to_start` | 首个已完成音频解锁的普通或上帝客户端发送各自的 ready 消息 | 原子写入 `game_started` 和 `run.started_at` | `ready` | 返回开局后的当前受众 snapshot |
| `ready` | 同一个首次 ready 已完成正式开局 | 创建 `action_id` 和 ActionContext | `model_streaming` | `live.state_changed: generating` |
| `model_streaming` | 新 V2 模型客户端返回增量 | 仅在服务端累积和检查，不公开原始 token | `model_streaming` | 无公开字幕 |
| `model_streaming` | 模型流结束且得到非空播报文本 | 持久化完整文本并封口 speech；不限制句数、标点、引号或排版 | `sentence_committed` | 依次发送 `presentation.opened`、`speech.segment_committed` |
| `sentence_committed` | 新 V2 TTS 客户端返回首个有效 PCM 块 | 创建状态为 `writing` 的 `voice_asset_id`，同一 PCM 块同时送入 recorder 和 broadcaster | `audio_streaming` | 发送带相同展示标识的音频帧 |
| `audio_streaming` | TTS 正常结束 | 冻结最终 sample 数，停止接收新块，等待广播时钟和 recorder 收尾 | `finalizing` | `live.state_changed: finalizing`，保持当前 presentation |
| `finalizing` | 开场官方时钟走完，且第一份语音资产已保存 | 关闭第一个 presentation、speech 和 action | `opening_speech_closed` | `presentation.closed`，随后确定性阶段转换 |
| `opening_speech_closed` | Repository 原子确认开场完成 | `phase_seq + 1`，进入 `first_night / nightfall_ready` | `nightfall_ready` | `game.phase_changed`，随后第二次 `live.state_changed: generating` |
| `finalizing` | 入夜官方时钟走完，且第二份语音资产已保存 | 关闭第二个 presentation、speech 和 action | `nightfall_announced` | `presentation.closed`，随后 `live.state_changed: awaiting_observation` |
| 任意非终态 | 明确的模型、质量、TTS、录音、广播或协议错误 | 记录唯一失败分类，停止当前资源 | `failed` | `presentation.failed` 或 `live.state_changed: failed` |

只有入夜动作的 `succeeded` 和任一动作的 `failed` 是本切片终态。开场动作成功后只能由确定性编排器创建已批准的入夜动作；不能由客户端按钮、模型输出或播放 ACK 决定是否推进。

`client.ready` 和 `god_view.ready` 是正式开局的一次性启动门禁，用来确保浏览器已通过用户手势解锁音频。创建对局、读取普通快照、读取上帝身份或只打开页面都不得填写 `run.started_at`、写入 `game_started` 或请求模型/TTS。它们不是播放 ACK，不能在两个动作之间控制推进。两种 ready 汇聚到同一个按 `game_id` 唯一的串行编排任务。

### 7.2 游戏阶段状态

```text
opening / opening_ready
  -> opening / opening_speech_closed
  -> first_night / nightfall_ready
  -> first_night / nightfall_announced
```

- 阶段转换只能在第一份语音资产成功保存且开场音频官方时钟结束后发生。
- `game.phase_changed` 必须先于第二个 action 的 `generating`、字幕和音频。
- 旧对局使用 `legacy / legacy_frozen`，即使其传输状态曾是 `ready` 也不能 claim 新动作。
- 失败把 `phase_state` 置为 `failed`，不继续推进。

### 7.3 发言生命周期

第一切片仍遵守完整生命周期：

```text
speech_opened
  -> segment_committed
  -> speech_sealed
  -> tts_stream_started
  -> (audio_broadcast_started + voice_recording_started)
  -> (audio_drained + voice_asset_saved) | explicit_failure
  -> speech_closed
```

- `segment_committed` 之前的模型 token 永不公开。
- 第一完整句提交后立刻关闭模型流；后续迟到 token 永久丢弃。
- `speech_sealed` 后禁止增加文本或音频句段。
- 只有服务器官方音频时钟结束，才能进入 `audio_drained`。
- 只有保存文件的 PCM 与广播 PCM 完全相同、sample 数一致并生成校验值后，才能进入 `voice_asset_saved`。
- `audio_drained` 和 `voice_asset_saved` 缺少任何一个，action 都不能成功。
- 客户端播放结束、断线或 ACK 都不改变服务端生命周期。

### 7.4 展示状态

```text
none -> active -> closed
               -> failed
```

- 任意时刻最多一个 `active` presentation。
- `closed` 或 `failed` 后，当前快照中的 `current_presentation` 必须变为 `null`。
- 新连接只能加入仍在 `active` 的 presentation，并从加入后的音频位置开始。
- 已结束的 presentation 永不重新激活。

## 8. WebSocket 连接

第一切片提供两个相互隔离的受众入口：

```text
GET /api/v2/live/games/{game_id}/ws
GET /api/v2/god-view/games/{game_id}/ws
```

连接规则：

1. 普通入口建立连接后立即发送 `live.snapshot`；上帝入口鉴权成功后发送 `god_view.live_snapshot`。
2. Mobile 必须先通过用户点击解锁 `AudioContext`，再按受众发送一次 `client.ready` 或 `god_view.ready`。
3. 服务端之后只发送连接建立后的当前和未来内容。
4. WebSocket 断开不会暂停或终止全局动作。
5. 重连重新从第 1 步开始，不提交历史 cursor，也不补发断线期间的音频。
6. 普通入口永远只返回普通直播投影；上帝视角使用独立 Router、DTO 和创建对局时签发的访问凭证，不能由普通连接参数提权。
7. 浏览器通过 `Sec-WebSocket-Protocol` 依次提供固定协议 `live-v2-god-view` 和访问凭证；凭证不得进入 URL 查询参数。服务端必须先鉴权、后接受 WebSocket，失败时不得发送任何身份快照。
8. 普通连接和上帝连接都是同一个按 `game_id` 聚合的运行通道的订阅者，不得各自创建 Action Engine、模型流或 TTS 流。

## 9. JSON 控制消息

所有 JSON 消息都有：

```json
{
  "protocol_version": 1,
  "type": "message.type",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "server_time": "2026-07-22T12:00:00.000Z"
}
```

### 9.1 `live.snapshot`：服务端到客户端

```json
{
  "protocol_version": 1,
  "type": "live.snapshot",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "server_time": "2026-07-22T12:00:00.000Z",
  "live_state": "waiting_to_start",
  "game_phase": {
    "phase_seq": 1,
    "phase_id": "opening",
    "phase_state": "opening_ready"
  },
  "latest_presentation_seq": 0,
  "playback_cursor": 0,
  "public_rule": {
    "rule_id": "classic_8",
    "name": "经典 8 人局",
    "version": "1",
    "player_count": 8,
    "roles": [
      {"role": "狼人", "count": 2},
      {"role": "预言家", "count": 1},
      {"role": "守卫", "count": 1},
      {"role": "村民", "count": 4}
    ],
    "max_rounds": 8,
    "sheriff_enabled": false,
    "werewolf_self_explosion_enabled": false,
    "exile_last_words_enabled": true
  },
  "public_players": [
    {
      "seat": 1,
      "player_id": "system-player-01",
      "display_name": "沈砚",
      "avatar_url": "/api/v1/public/player-profiles/system-player-01/avatar"
    }
  ],
  "public_role_assignment": {
    "state": "sealed",
    "assigned_count": 8
  },
  "current_presentation": null
}
```

若重连时正在播报，`current_presentation` 只包含当前展示、当前字幕和加入时的 `join_sample_cursor`，不包含已经发送的音频块。若播报已经结束，则必须为 `null`。

`public_players` 是创建对局时玩家快照的公开、不可变投影，必须按 `seat` 升序排列。每项只能包含 `seat`、`player_id`、`display_name` 和 `avatar_url`；角色、模型、人格、策略、提示词、TTS 配置以及其他内部字段不得进入普通直播协议。Mobile 可以在用户点击进入实时观赛前通过 REST snapshot 展示这些座位；读取座位本身不得创建 action、请求模型或解锁音频。

`public_rule` 是创建时冻结规则的公开投影，只允许规则 ID、名称、版本、玩家人数、角色数量构成、最大轮数和公开玩法开关。规则 revision、内容哈希、阵容质量报告、内部 team/model group、提示词和未来玩家身份分配均不得进入普通直播协议。读取和展示规则快照不得创建 action 或推进游戏阶段。

`public_role_assignment` 只能是 `{state, assigned_count}`。`sealed` 表示服务端已经完成并私密保存全部座位身份，`unavailable` 表示该对局没有可用的身份批次。普通直播不得获得 `assignment_id`、随机种子、摘要、逐座位角色或阵营；Mobile 对额外字段必须失败关闭。

### 9.2 `god_view.identity_snapshot`：服务端到客户端

```json
{
  "protocol_version": 1,
  "type": "god_view.identity_snapshot",
  "api_version": "v2",
  "audience": "spectator_god_view",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "live_state": "waiting_to_start",
  "game_phase": {
    "phase_seq": 1,
    "phase_id": "opening",
    "phase_state": "opening_ready"
  },
  "server_time": "2026-07-22T12:00:00.000Z",
  "rule": {
    "rule_id": "classic_8",
    "name": "经典 8 人局",
    "version": "1",
    "player_count": 8,
    "roles": [
      {"role": "狼人", "count": 2},
      {"role": "预言家", "count": 1},
      {"role": "守卫", "count": 1},
      {"role": "村民", "count": 4}
    ],
    "max_rounds": 8,
    "sheriff_enabled": false,
    "werewolf_self_explosion_enabled": false,
    "exile_last_words_enabled": true
  },
  "players": [
    {
      "seat": 1,
      "player_id": "system-player-01",
      "display_name": "沈砚",
      "avatar_url": "/api/v1/public/player-profiles/system-player-01/avatar",
      "role": "狼人",
      "team": "werewolves"
    }
  ]
}
```

该快照只能通过独立的 `/api/v2/god-view/games/{game_id}/identity-snapshot` 读取，并要求创建对局时签发的 Bearer 凭证。数据库只保存凭证的 SHA-256，不保存原文。响应允许暴露当前游戏身份和阵营，但仍禁止暴露模型 ID、人格/策略提示词、TTS 配置、身份随机种子、摘要和访问凭证本身。

读取上帝身份快照不创建 action、不连接 WebSocket、不请求模型或 TTS，也不改变任何游戏状态。

### 9.3 `god_view.live_snapshot`：服务端到客户端

上帝 WebSocket 鉴权成功后发送独立实时快照。字段必须精确为：

```json
{
  "protocol_version": 1,
  "type": "god_view.live_snapshot",
  "api_version": "v2",
  "audience": "spectator_god_view",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "live_state": "waiting_to_start",
  "game_phase": {
    "phase_seq": 1,
    "phase_id": "opening",
    "phase_state": "opening_ready"
  },
  "latest_presentation_seq": 0,
  "server_time": "2026-07-22T12:00:00.000Z",
  "rule": {},
  "players": [],
  "current_presentation": null
}
```

`rule` 和 `players` 与已通过的上帝身份快照使用相同严格投影；`current_presentation` 只表示当前仍然有效的展示。凭证、随机种子、身份摘要、模型配置和历史音频都不得进入该快照。

### 9.4 ready 消息：客户端到服务端

```json
{
  "protocol_version": 1,
  "type": "client.ready",
  "audio": {
    "encoding": "pcm_s16le",
    "sample_rate": 24000,
    "channels": 1
  }
}
```

上帝连接使用完全相同的音频能力字段，但 `type` 必须为 `god_view.ready`。服务端必须按连接受众验证消息类型，普通连接发送 `god_view.ready` 或上帝连接发送 `client.ready` 都要失败关闭。

每条连接最多接受一次。首个满足条件的任一 ready 必须原子地把对局和 run 从 `waiting_to_start` 改为 `ready`，填写真实 `started_at`，并写入唯一 `game_started`；其 `trigger_audience` 为 `player_public` 或 `spectator_god_view`。后来连接的 ready 只标记该连接具备播放能力。重复消息幂等，任何并发连接都不得创建第二个 `game_started` 或 action。

### 9.5 `live.state_changed`：服务端到客户端

```json
{
  "protocol_version": 1,
  "type": "live.state_changed",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "server_time": "2026-07-22T12:00:01.000Z",
  "live_state": "generating",
  "reason": null
}
```

本切片允许的传输状态为：`waiting_to_start`、`ready`、`generating`、`broadcasting`、`finalizing`、`awaiting_observation`、`failed`。

### 9.6 `game.phase_changed`：服务端到客户端

```json
{
  "protocol_version": 1,
  "type": "game.phase_changed",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "server_time": "2026-07-22T12:00:05.100Z",
  "phase_seq": 2,
  "previous_phase_id": "opening",
  "phase_id": "first_night",
  "phase_state": "nightfall_ready",
  "reveal_presentation_seq": 1
}
```

本切片只允许上述单向阶段转换。普通页和上帝页接收同一事件；该事件不包含任何身份、狼人队友或秘密行动。

### 9.7 `presentation.opened`：服务端到客户端

```json
{
  "protocol_version": 1,
  "type": "presentation.opened",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "server_time": "2026-07-22T12:00:02.000Z",
  "action_id": "v2_action_...",
  "presentation_seq": 1,
  "presentation_id": "v2_pres_...",
  "phase_id": "opening",
  "actor": {
    "kind": "judge",
    "id": "judge"
  },
  "speech_id": "v2_speech_..."
}
```

### 9.8 `speech.segment_committed`：服务端到客户端

```json
{
  "protocol_version": 1,
  "type": "speech.segment_committed",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "server_time": "2026-07-22T12:00:02.010Z",
  "action_id": "v2_action_...",
  "presentation_seq": 1,
  "presentation_id": "v2_pres_...",
  "speech_id": "v2_speech_...",
  "segment_index": 0,
  "text": "模型实时生成的完整法官开场白。"
}
```

字幕必须在第一个音频块之前送达，并与音频使用完全相同的 `presentation_id`、`speech_id` 和 `segment_index`。

### 9.9 `presentation.closed`：服务端到客户端

```json
{
  "protocol_version": 1,
  "type": "presentation.closed",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "server_time": "2026-07-22T12:00:05.000Z",
  "action_id": "v2_action_...",
  "presentation_seq": 1,
  "presentation_id": "v2_pres_...",
  "speech_id": "v2_speech_...",
  "final_segment_index": 0,
  "final_chunk_index": 17,
  "final_sample_cursor": 72000,
  "result": "audio_drained_and_voice_saved",
  "playback_cursor": 1
}
```

该消息只能在官方音频时钟走完最后一个 sample 后发送，不能在 TTS 返回结束或最后一帧刚写入 socket 时提前发送。

### 9.10 失败消息：服务端到客户端

展示尚未打开时，发送 `live.state_changed` 且 `live_state=failed`。展示打开后，发送：

```json
{
  "protocol_version": 1,
  "type": "presentation.failed",
  "game_id": "v2_game_...",
  "run_id": "v2_run_...",
  "server_time": "2026-07-22T12:00:03.000Z",
  "action_id": "v2_action_...",
  "presentation_seq": 1,
  "presentation_id": "v2_pres_...",
  "speech_id": "v2_speech_...",
  "failure_kind": "tts",
  "failure_code": "first_audio_chunk_timeout"
}
```

`failure_kind` 只能明确归类为 `model`、`quality`、`tts`、`recording`、`broadcast` 或 `protocol`。失败后清空当前展示并停止，不生成兜底台词，也不开始下一动作。录音失败不得改用旧语音资产，也不得让广播从历史文件重新开始。

## 10. 二进制音频帧

控制消息使用 JSON 文本帧，PCM 使用二进制帧，避免 Base64 放大数据。

每个二进制帧由以下部分组成：

```text
4 bytes   ASCII magic: LV2A
2 bytes   unsigned big-endian JSON header length
N bytes   UTF-8 JSON header
remaining PCM S16LE payload
```

JSON header 至少包含：

```json
{
  "protocol_version": 1,
  "action_id": "v2_action_...",
  "presentation_seq": 1,
  "presentation_id": "v2_pres_...",
  "speech_id": "v2_speech_...",
  "segment_index": 0,
  "chunk_index": 0,
  "start_sample": 0,
  "sample_count": 4800,
  "sample_rate": 24000,
  "channels": 1,
  "encoding": "pcm_s16le",
  "is_final": false
}
```

服务端为音频块分配 `start_sample`，并以固定的小幅直播提前量发送。官方结束时间由 `broadcast_started_at + final_sample_cursor / sample_rate` 决定，不由某个客户端的播放回调决定。

客户端处理规则：

- 相同 `chunk_index` 的重复帧只处理一次。
- 小于当前展示序列的迟到帧直接丢弃。
- 不属于当前展示、标识不一致、chunk 越序或 sample 不连续时，本地失败关闭当前音频，不猜测、不补拉历史。
- 客户端失败只影响该连接；服务端动作继续按官方时钟推进。

## 11. 重连语义

| 重连时服务端状态 | 快照内容 | 后续音频 |
| --- | --- | --- |
| `ready` / `generating` | 当前状态，无历史 token | 只接收未来正式音频 |
| `broadcasting` / `finalizing` | 当前 actor、subtitle、展示标识和 `join_sample_cursor` | 只接收加入后尚未广播的块；已经过去的部分不补播 |
| `awaiting_observation` | `game_phase=first_night/nightfall_announced`，`current_presentation=null` | 不播放刚结束的任一句话 |
| `failed` | 失败分类，`current_presentation=null` | 不补播、不自动重试 |

客户端不得发送 `Last-Event-ID`、`record_seq`、`presentation_seq` 或音频 cursor 来请求追赶历史。

## 12. 持久化记录与语音资产

直播帧是实时投影，数据库记录是审计证据，两者不能互相充当播放队列。

### 12.1 语音保存规则

- 每个已提交 segment 必须分配独立的 `voice_asset_id`。
- TTS 输出先标准化为 PCM S16LE；同一个有序 PCM 块同时交给 broadcaster 和 recorder，不允许分别请求两次 TTS。
- Recorder 按 `chunk_index` 和 `start_sample` 顺序写入临时资产，拒绝重复、缺块、越序和 sample 不连续。
- TTS 结束后把相同 PCM 封装为一个可独立播放的 WAV 文件，并以原子操作从 `writing` 变为 `ready`。
- 语音资产至少保存 `sample_rate`、`channels`、`sample_count`、`duration_ms`、`pcm_sha256`、文件大小和完成时间。
- 不把每个 PCM 块保存为数据库行；数据库只保存资产元数据，音频文件进入 V2 自己的文件或对象存储命名空间。
- 公开 Live snapshot 和 WebSocket 不返回已保存语音的下载 URL。Admin V2 可以通过独立鉴权接口播放记录语音；未来 Replay 即使使用该资产，也必须走独立 Replay 协议。
- 录音失败必须把资产标记为 `failed` 并使当前 action 失败，不能留下看似成功但没有语音的对局记录。

### 12.2 动作证据事件

每个动作至少记录：

1. `action_opened`
2. `model_request_started`
3. `model_first_token_received`
4. `speech_segment_committed`
5. `speech_sealed`
6. `tts_stream_started`
7. `tts_first_chunk_received`
8. `voice_recording_started`
9. `audio_broadcast_started`
10. `tts_stream_completed`
11. `voice_asset_saved` 或 `voice_recording_failed`
12. `audio_drained` 或明确广播失败事件
13. `speech_closed`
14. `action_succeeded` 或 `action_failed`

两个动作之间额外记录一次 `game_phase_changed`。最终记录必须能证明恰好两个 action、两个 presentation 和两份 ready voice asset，且没有狼人唤醒或秘密动作事件。

不逐块落库模型 delta 或 PCM。完成记录保存模型请求标识、首 token 耗时、完整句耗时、TTS 首块耗时、最终文本、`voice_asset_id`、音频 sample 数、PCM 校验值和失败分类。语音保存是同源分流，不能反向修改直播时钟、插入旧块或要求客户端追播。

### 12.3 V2 语音资产元数据

V2 使用全新语音资产记录，不复用旧 `voice_utterances`、`voice_audio_chunks` 或 `voice_materialization_jobs`。最小字段为：

- `voice_asset_id`
- `game_id`、`run_id`、`action_id`
- `presentation_id`、`speech_id`、`segment_index`
- `state`: `writing | ready | failed`
- `storage_key` 和 `mime_type`
- `sample_rate`、`channels`、`sample_count`、`duration_ms`
- `pcm_sha256`、`size_bytes`
- `created_at`、`completed_at`

`storage_key` 只在服务端和受权 Admin 接口使用，不能出现在普通直播响应中。

## 13. 已冻结的基础切片实现

当前实时链路由独立 V2 Action Engine、V2 模型客户端、V2 TTS 客户端、V2 WebSocket broadcaster、V2 Voice Recorder、V2 repository 和独立 PCM 播放器实现。它们不导入旧游戏、旧 Live、Replay、旧模型/TTS 或旧记录业务代码。

本步只扩展已经独立编写并通过验收的 V2 模块：同一个串行编排器使用两份全新的 ActionContext 分别请求模型与 TTS，不复制第二套动作引擎，也不接入任何 V1/旧直播实现。

## 14. 基础切片当时修改的模块（历史）

- API：新增持久化 `game_phase`、开场到入夜串行编排、第二个真实模型/TTS 动作和 `game.phase_changed`。
- Mobile：普通页和上帝页同步进入首夜场景；每个 `presentation.closed` 后清除旧字幕，不追播已结束音频。
- 文档与测试：验证严格的 1→2 presentation 序列、两个视角同源、恰好两次模型/TTS、两份语音资产，以及无狼人秘密事件。
- 数据库和 Admin：为 V2 对局新增阶段字段；旧对局冻结为 legacy，新对局从 opening 开始；Admin 继续展示两份独立语音记录。

## 15. 基础切片自动化验收标准（历史）

- V2 对被禁止的旧业务模块保持零导入。
- 普通 `client.ready` 和上帝 `god_view.ready` 并发时只创建一条全局串行流程；重复消息不得额外创建动作。
- 真实模型调用产生可追踪的 provider request 标识或本地 attempt 标识。
- 记录首 token 时间和第一完整句时间。
- 模型原始 token 不出现在公开 WebSocket 帧。
- 字幕先于首个音频块，且字幕和所有音频块共享相同展示标识。
- 音频 `chunk_index` 和 `start_sample` 严格递增。
- 官方时钟结束前不得发送 `presentation.closed`。
- 保存语音的 PCM 校验值和 sample 数必须与实际广播源完全一致。
- 语音资产未进入 `ready` 时 action 不得成功；录音失败必须归类为 `recording` 并停止。
- 普通 Live 协议不得暴露已保存语音的下载地址，Admin V2 受权接口可以播放。
- 客户端不发送播放 ACK，服务端也不等待播放 ACK。
- 刷新或重连后不播放已经结束的任一句话。
- 开场失败不得进入首夜；入夜失败不得生成兜底或开始狼人动作。
- 普通直播帧不包含模型内部提示、原始响应或秘密上下文。
- 普通身份快照即使携带上帝凭证也只返回封存状态，不能提权。
- 上帝身份快照缺少或使用错误凭证时返回拒绝，不返回部分身份。
- 上帝身份快照只包含公开玩家字段、角色和阵营，不包含玩家配置或访问凭证。
- 上帝 WebSocket 使用子协议携带凭证，URL、快照和持久化记录中都不出现凭证明文。
- 错误或缺失凭证必须在任何 `god_view.live_snapshot` 发出前拒绝连接。
- 普通和上帝页面同时观赛时全局恰好两次模型调用、两次 TTS、两个 presentation 和两份语音资产，而不是每个视角各执行一份。
- `presentation_seq` 必须为 1、2，`game.phase_changed` 恰好一次并位于两个 action 之间。
- 最终阶段必须是 `first_night / nightfall_announced`，且记录中没有狼人唤醒、相认、决策或选刀事件。
- 上帝实时快照在动作结束后 `current_presentation` 为 `null`，重连不补发字幕或音频。

## 16. 基础切片用户观察清单（历史）

1. 打开 Mobile V2 页面时，尚未点击前不会偷偷开始模型请求或播放。
2. 点击“进入实时观赛”后，页面先显示法官正在生成内容。
3. 第一条字幕是本次真实模型生成的开场句，不是静态 `game_intro`，随后实时播放同源声音。
4. 第一条声音完整结束后，页面切换到“第一夜”，再出现第二次真实模型生成的入夜字幕与声音。
5. 第二条声音结束后页面显示“等待本步验收”，不出现狼人睁眼、狼人队友或选刀内容。
6. 此时刷新页面，不会重新播放刚才两句话中的任何一句。
7. Admin V2 记录能看到同一个 `run_id` 下两个不同 `action_id`、两组模型/TTS 耗时、两个 `voice_asset_id` 和两次广播结束证据。
8. 在 Admin V2 分别播放两份保存语音，内容必须与直播中听到的开场句和入夜句一致。
9. 任一观察不符合时，只修复这一切片，不进入下一动作。
10. 同一新建对局的普通直播只显示身份已封存，上帝视角显示全部座位的角色和阵营。
11. 普通页和上帝页读取身份时都不会自动连接实时直播，也不会产生新的模型、展示或语音记录。
12. 点击任一页面的实时观赛按钮后，两种视角按相同顺序收到两条法官字幕和语音，上帝页始终保留全部角色卡。
13. 两个页面同时进入也只产生全局两个 action 和两份语音资产；完成后刷新上帝页不重播刚才的字幕或声音。

## 17. 能力驱动行动窗口契约

本节定义首夜及其他游戏阶段共同使用的当前运行时契约。它替代“按角色名称写死流程”的设计，并在不破坏第 1 至 16 节已验收开场、入夜行为的前提下继续推进。

### 17.1 设计边界

- 角色是能力的载体，不是阶段主执行器中的固定分支。
- 规则集由角色组合、能力配置、能力交互规则和窗口转换规则组成。
- 进入一个行动窗口时，V2 根据冻结规则、身份、资源和当前状态动态发现能力激活项。
- 模型负责需要角色作出的实时选择和自然语言内容；合法性、效果、冲突结算、身份、阶段和胜负仍由确定性代码负责。
- 需要选择或发言的每次激活都必须真实请求模型；纯被动效果和规则结算不是伪装成玩家动作的模型请求。
- 模型请求数、TTS 次数和语音资产数由实际激活计划决定，不允许为某套阵容写死固定数量。
- 本节不复用旧游戏编排、旧角色处理器、旧模型/TTS 或旧记录实现。

### 17.2 核心对象

| 对象 | 含义 | 稳定身份 |
| --- | --- | --- |
| `AbilityDefinition` | V2 代码中注册的版本化能力语义 | `ability_id + ability_version` |
| `AbilityInstance` | 某个玩家、阵营或系统在本局实际持有的能力 | `ability_instance_id` |
| `ActionWindow` | 允许一组能力被发现、执行和结算的游戏窗口 | `window_id + window_seq` |
| `AbilityActivation` | 某个能力实例在当前窗口中的一次实际激活 | `activation_id` |
| `ActivationGroup` | 共享睁眼、闭眼、受众或阵营协作语义的一组激活 | `activation_group_id` |
| `Decision` | 模型依据允许知识给出的结构化选择 | `decision_id` |
| `EffectIntent` | 已通过合法性校验、等待确定性结算的效果意图 | `effect_intent_id` |
| `KnowledgeFact` | 只能投影给明确受众的私密事实 | `knowledge_fact_id` |
| `ResolutionEvent` | 结算器对游戏状态作出的确定性变更证据 | `resolution_event_id` |

不得为预言家、守卫、女巫等角色分别创建一套流程表。持久化围绕上述通用对象组织，Admin V2 通过这些证据还原每种角色的实际行为。

### 17.3 冻结能力快照

现有大厅继续负责规则选择和阵容配置，只通过 V2 创建 DTO 交付最终冻结数据。V2 不复制大厅，也不导入旧规则运行时代码。

当前 `roles` 和 `night_actions` 只能作为编译输入。创建对局时，全新的 V2 能力编译器必须产生不可变运行时快照，至少包含：

- `ability_id`、`ability_version` 和快照 schema 版本。
- 能力所属的角色、阵营或系统范围。
- `owner_scope`: `player | team | system`。
- 允许激活的 `window_type` 和受控触发类型。
- 受控的存活、资源、轮次和使用次数条件。
- 前置结果依赖和依赖允许暴露的最小字段。
- `observation_policy_id`、`decision_contract_id` 和 `target_policy_id`。
- `effect_type`、确定性处理器版本和结算依赖。
- `presentation_policy_id`、受众和是否需要真实语音。
- `blocking`、每窗口最大激活次数和全局最大激活次数。
- 当前规则对共识、平票、资源消耗、同夜互斥和跨轮限制的配置。

数据库配置只能引用 V2 注册表中受信任的标识和枚举，禁止保存任意 Python、JavaScript、SQL 或自由表达式作为运行规则。

在对局可以进入实时运行前，编译器必须验证：

1. 每个能力及版本都已注册。
2. 每个能力都能解析到合法的持有者。
3. 依赖图无环且引用完整。
4. 决策、目标、效果、展示和全部受众投影策略均存在。
5. 激活次数有确定上限，响应能力不能形成无限循环。
6. 下一个窗口转换唯一且可确定。

任一条件不满足时，对局失败关闭，不能跳过未知能力后继续直播。

### 17.4 动态激活生命周期

行动窗口使用以下通用生命周期：

```text
window_opened
  -> activation_plan_compiled
  -> activation_group_opened
  -> activation_opened
  -> decision_committed | deterministic_effect_committed | activation_skipped
  -> effect_intent_committed*
  -> activation_closed
  -> activation_group_closed
  -> effects_resolved
  -> reaction_activations_discovered*
  -> window_closed
```

执行规则：

1. 规划器只从冻结能力快照和已经持久化的当前状态推导可运行激活。
2. 同一 `game_id + window_seq + ability_instance_id + occurrence` 只能生成一个有效 `activation_id`。
3. 为保持实时直播时序，一次只激活一个需要展示或模型请求的激活项。
4. 当前激活的发言、TTS、保存和展示未封口前，不得激活下一个展示项。
5. 条件不成立的能力必须记录结构化 `activation_skipped` 及受控原因，不能以“没有记录”代表跳过。
6. 每次激活关闭后，规划器重新读取确定性状态并计算下一项，不保存写死的“下一个角色”。
7. 效果结算产生的新事件可以激活死亡响应、免疫、反击、身份变化等后续能力。
8. 规划器持续执行到没有未完成的阻塞激活、没有新响应能力且结算稳定，才允许关闭窗口。
9. 模型、质量、TTS、录音、广播或协议失败停在当前激活，不生成静态、随机、旧模型或旧语音兜底。

### 17.5 展示顺序与知识依赖分离

直播展示必须串行，但展示顺序不授予游戏知识。

- 某能力排在狼队行动之后展示，不代表其行动者可以看到狼队目标。
- 只有能力快照声明的依赖和 `observation_policy_id` 才能把前序结果加入模型上下文。
- 上帝视角能看到完整秘密，不代表玩家模型上下文也能看到完整秘密。
- 规划器只决定“谁现在可以执行”；知识投影器独立决定“这个行动者现在可以知道什么”。
- 模型调用前必须持久化本次输入使用的 `knowledge_fact_id`、投影策略版本和规范化摘要哈希，用于幂等检查和审计关联；是否越权仍由事实清单与投影策略共同验证，不能只依赖哈希断言。

例如守护可以在展示上晚于狼队袭击，但守护者看不到袭击目标；女巫救人能力如果声明依赖 `provisional_attack_target`，则只能看到规则允许的被袭击者信息，不能看到狼队讨论和选择理由。

### 17.6 模型、决策与语音

每个需要角色选择或发言的激活创建独立 ActionContext：

- `action_id`、`activation_id`、`ability_instance_id`。
- 当前窗口和确定性目标。
- 仅由知识投影器产生的可见事实。
- 能力声明的结构化输出契约和合法候选项。
- 已预留但当前仍为禁用状态的 `influence`。

模型输出分为两部分：

- `decision`：必须符合能力的结构化决策契约。
- `speech`：能力展示策略要求时生成的私密或公开自然语言内容。

确定性验证器只接受合法决策，拒绝不存在、已死亡、不可选、自身禁止、资源不足或违反跨轮限制的目标。模型不得直接输出最终死亡、身份、阶段或胜负状态。

所有被接受并要求播出的法官或玩家语音都使用本协议既有的实时 TTS、同源 PCM 广播和 V2 语音保存生命周期。私密语音资产必须保存受众元数据；普通连接既不能收到其字幕，也不能收到其 PCM 或下载地址。

### 17.7 效果意图与确定性结算

模型决策通过验证后只产生 `EffectIntent`，例如袭击、防护、查验、治疗、额外伤害、阻断、标记或其他已经注册的效果。意图自身不能直接修改玩家状态。

结算器必须：

1. 按冻结规则读取当前窗口的完整效果意图。
2. 使用已注册、带版本的确定性效果处理器计算结果。
3. 对互斥、抵消、叠加、优先级和资源消耗给出唯一结果。
4. 原子写入玩家状态、能力资源、私密知识和结算事件。
5. 把结算事件交回规划器发现响应能力。

增加全新效果语义时，可以新增独立效果处理器及测试；不得修改窗口主循环来增加 `if role == ...` 分支。

### 17.8 阵营协作与多步骤能力

`ActivationGroup` 负责表达一个角色或阵营在同一次睁眼期间的多个步骤：

- 多名狼人共享一个阵营袭击能力组；组内可以由规则选择逐人提案、共识、队长、票决或平票策略。
- 女巫可以拥有依赖袭击候选的救人子任务和独立毒人子任务；是否允许同夜同时使用由规则配置决定。
- 一个角色拥有多个技能时，可以在同一个能力组内按声明的依赖执行，不需要重复写睁眼和闭眼流程。
- 被动能力不创建虚假的睁眼流程，只在对应事件出现时产生确定性效果或响应激活。

组内每个模型决定仍有独立 `action_id` 和 `activation_id`；组的存在不能合并证据、跳过失败状态或复用模型结果。

### 17.9 受众投影

每个激活和效果必须在服务端分别生成投影：

| 内容 | 普通直播 | 上帝视角 | 未来玩家视角 |
| --- | --- | --- | --- |
| 夜间阶段和安全进度 | 可见 | 可见 | 可见 |
| 行动者角色、身份和阵营成员 | 不可见 | 可见 | 仅按规则可见 |
| 候选目标、选择、理由和效果意图 | 不可见 | 可见 | 仅本人或规则授权对象可见 |
| 查验、救人等私密知识 | 不可见 | 可见 | 仅知识持有者可见 |
| 私密字幕和 PCM | 不发送 | 可发送 | 仅授权连接可发送 |
| 天亮后的公开结果 | 按规则可见 | 可见 | 按规则可见 |

普通连接不能先接收完整事件再由前端隐藏。私密激活占用全局单调的 `presentation_seq` 时，普通连接只接收不含行动者、能力、目标和结果的安全进度投影；该投影携带被占用的序列号，使客户端可以安全前移而不打开私密展示。普通连接不得收到私密 `presentation.opened`、字幕或二进制音频帧，后续公开展示可以合法跳到更大的序列号。

所有受众都必须使用明确允许列表，任何连接都不能透传原始 payload。未知能力、未知字段和未知事件默认删除并记录协议错误；上帝视角可以看到全部已经明确授权的游戏秘密，但仍不能看到访问凭证、模型内部提示、供应商原始响应、身份随机种子或未声明字段。

### 17.10 通用持久化证据

每个行动窗口至少要能从 V2 记录中还原：

- 使用的冻结能力快照版本和哈希。
- 发现、跳过、打开和关闭的全部激活及原因。
- 每个激活允许看到的 `knowledge_fact_id`、投影策略版本和规范化摘要哈希。
- 模型请求、结构化决定、合法性结果和失败分类。
- 效果意图、结算处理器版本和确定性结果。
- 新增或消耗的能力资源与私密知识。
- 各受众生成了哪种投影，哪些内容被失败关闭。
- 每段语音的受众、同源 PCM 校验值和保存结果。
- 窗口关闭条件以及唯一的下一窗口转换。

记录只用于审计、Admin V2 和未来独立 Replay，不能成为 Live V2 的追播队列。

### 17.11 不同规则的计划示例

| 冻结规则 | 动态生成的能力激活 |
| --- | --- |
| 只有狼人和村民 | 阵营袭击；没有守护、查验或女巫步骤 |
| 经典八人局 | 阵营袭击、守护、查验，然后统一夜间结算 |
| 移除守卫的规则 | 不生成守护激活，主执行器无需修改 |
| 加入女巫的规则 | 袭击候选产生后，按依赖生成救人和可选毒人激活 |
| 猎人夜间死亡 | 结算事件按规则决定在当前窗口或后续窗口激活死亡响应 |
| 角色拥有两个技能 | 生成一个能力组和两个有条件子激活 |

经典八人局只是一套真实验收配置，不得成为运行时流程模板。

### 17.12 首次实现的自动化门禁

- 阶段主执行器和行动窗口主循环不得按具体角色名分支。
- 同一能力实例和窗口重复规划时保持幂等，不重复请求模型。
- 无守卫、经典八人和带女巫三种冻结规则生成不同计划。
- 未知能力、版本缺失、循环依赖、缺失投影或无上限响应循环全部失败关闭。
- 展示顺序变化不改变行动者的知识投影。
- 私密 payload、字幕和 PCM 永不进入普通连接。
- 上帝连接可以看到全部已经授权的能力、选择、效果和私密语音。
- 每个需要选择的激活恰好对应一次成功模型调用，数量从实际计划统计而非写死。
- 每段需要播出的语音恰好一次 TTS 和一份同源 V2 语音资产。
- 任一激活失败后不执行后续能力、不结算夜间、不宣布天亮。
- 所有 presentation 保持单调，重连只进入当前激活，不补播已经关闭的私密或公开语音。
- V2 继续通过旧游戏、模型、TTS、Live、Replay 和记录业务零导入检查。

能力运行时通过自动化门禁后，必须使用当前大厅实际创建的冻结规则完成真实对局观察；只有用户确认运行结果，才允许继续下一个行动窗口。

## 18. 当前首夜扩大验收包

本验收包从已经通过的 `first_night / nightfall_announced` 基础继续执行，覆盖当前官方规则实际配置的全部首夜能力。对局不会在首夜中间增加人工停点；只有整个首夜、黎明播报和阻塞死亡响应全部封口后，才进入下一次人工验收。

### 18.1 已实现的能力语义

- `werewolf.attack@1`：存活狼人按座位顺序逐人实时提案；全员一致立即形成袭击意图；不一致只允许再提案一轮，第二轮仍不一致则空刀，绝不随机选人。
- `guard.protect@1`：首夜允许自守；目标必须存活；能力状态保存上一夜目标，为后续夜晚禁止连续守同一人。
- `seer.investigate@1`：只能查验其他存活玩家；阵营结果由冻结身份确定性计算，并写入只属于预言家的知识事实。
- `witch.heal@1`：只有存在临时袭击目标且解药可用时激活；首夜允许自救；可以明确放弃。
- `witch.poison@1`：可以明确放弃；目标必须存活，排除女巫本人和当夜临时袭击目标；同夜用了救药后毒药按互斥规则跳过。
- `hunter.death_shot@1`：猎人因非毒药原因死亡时在黎明产生阻塞响应；模型可以选择开枪或放弃；毒死时不得产生开枪激活。

规则中没有对应能力时不生成激活。当前官方 `social_8`、`starter_6`、`classic_8` 和 `classic_12_seer_witch_hunter_idiot` 由同一个冻结快照编译器和行动窗口主循环处理。

### 18.2 结算和停点

夜间效果由独立确定性结算器统一处理袭击、守护、治疗和毒杀。结算完成后：

1. 原子更新玩家存活、死亡原因、能力资源、效果状态和私密知识。
2. 上帝视角立即收到完整死亡原因和能力进度；普通直播只收到不含角色、目标或原因的安全进度。
3. 法官使用新的实时模型请求生成黎明播报，只公开规则允许的死亡名单，并使用同源实时 TTS 保存语音。
4. 处理所有阻塞死亡响应后重新计算胜负。
5. 无警长规则先进入 `day_1 / public_day_ready / ready`，交给首日窗口开启器。
6. 有警长规则先进入 `day_1 / sheriff_election_ready / ready`，交给首日窗口开启器。
7. 已满足胜负条件时停在 `day_1 / game_completed / awaiting_observation`。

首夜验收已经通过。非终局对局不再把上述 `*_ready` 当成人工停点，而是继续进入第 19 节的首日公开窗口开场；首夜能力、黎明结算和死亡响应仍保持原有语义。

### 18.3 当前证据面

- V2 数据库独立保存 `ActionWindow`、`AbilityInstance`、`AbilityActivation`、`EffectIntent`、`KnowledgeFact` 和 `PlayerState`。
- 每次真实玩家决定由一次模型请求同时产生结构化目标与自然发言；发言只要求是非空文本，允许多句话、换行、引号和自由口语表达。目标在打开字幕和 TTS 前通过候选允许列表验证。
- V2 不设置句数、句末标点、最短/最长字符、Markdown 或引号质量闸门；只有响应无法解析、缺少必要决策字段、发言为空或目标违反确定性规则时才拒绝动作。
- 每次法官动作实时读取法官配置中的 `model_provider`、`model_id`、`tts_speaker` 和 `version`；法官动作规格不得覆盖它们，实际值随 ActionContext、模型请求和 TTS 请求证据一起保存。
- 所有被接受的法官和玩家发言都走同一个独立 V2 PCM 广播、官方时钟和语音保存生命周期。
- presentation 和 voice asset 都保存 `activation_id` 与 `audience`；`god_view` 私密帧不会进入普通连接。
- Admin V2 详情分别展示窗口、能力实例、激活与决策、效果、知识、玩家状态、展示和保存语音。
- 弹幕影响入口继续存在于每个 ActionContext 中，当前固定为 `disabled`，不接收或伪造弹幕信号。

## 19. 完整白天与整局主循环

任意一夜完成且未触发胜负后，运行时只能根据冻结能力快照、整局状态和当前轮次选择白天窗口，不允许客户端、模型或页面自行选择分支：

| 夜晚收口状态 | 新的法官实时动作 | 后续动作 |
| --- | --- | --- |
| `public_day_ready` | `judge_public_discussion_opening` | 公开发言、投票、PK、放逐与死亡响应 |
| `sheriff_election_ready` | `judge_sheriff_election_opening` | 参选、竞选发言、退水、投票、PK，然后进入公开发言 |
| `game_completed` | 不请求模型或 TTS | 保持终局状态 |

每个法官和玩家动作都必须执行完整的模型、字幕、同源实时 TTS、官方音频时钟和语音保存生命周期。法官使用法官配置的模型与音色；玩家使用各自冻结配置的模型与音色。动作完成后持久化业务事件和 `game_phase_changed`、`match.state_changed` 或 `player.state_changed`，使普通与上帝客户端看到各自允许的信息。

### 19.1 警长流程

- 仅当冻结规则启用警长且警徽状态为 `pending` 时执行竞选。
- 存活玩家依次决定参选；参选者实时发表竞选发言并可退水。
- 只有最初未参选玩家拥有警上投票资格；唯一候选直接当选，无合法投票者或两轮仍平票则警徽流失。
- 规则允许的警上自爆会立即中止当天；双爆撕警徽由 `sheriff_badge_bomb_policy` 决定。
- 警长死亡后实时决定移交或撕毁警徽，并保存独立审计事件。

### 19.2 发言、放逐与特殊角色

- 发言顺序由冻结 `speech_policy` 决定；警长顺序模式由警长在相邻存活玩家中选择起点，不能由阶段执行器写死座位。
- 每名存活玩家的发言和投票都是新的实时模型请求，输入包含合法公开历史和该玩家自己的私密知识。
- 放逐按票重确定唯一最高票；警长票权使用冻结 `sheriff_vote_weight`。首轮平票进入 PK，PK 玩家不参与第二轮投票，第二轮仍平票则无人出局。
- 白痴首次被放逐时翻牌存活并永久失去投票权；猎人非毒杀死亡时产生阻塞开枪响应，连锁击中另一猎人时继续结算到没有待处理响应。
- 狼人自爆的“不爆”决定只投影上帝视角；实际自爆、公开死亡和当天中止向全部观众播报。

### 19.3 胜负、轮次与终态

每次夜间结算、放逐、自爆和死亡响应后都重新计算冻结胜负规则。未结束时，白天收口原子推进到 `night_{N+1} / nightfall_ready`；下一夜继续使用同一能力计划和持久化资源状态。满足胜负时，法官实时宣布获胜阵营，状态进入 `game_completed / awaiting_observation`，记录 `winner`、`completion_reason` 和 `run.completed_at`。达到 `max_rounds` 仍无胜负时必须明确进入 `failed / max_rounds_exceeded`，不得伪造平局或静默停止。

普通直播只接收公开存活变化，不接收死亡原因、私密目标和能力结果；上帝视角接收完整原因与私密流水。任一普通连接收到私密字段，客户端必须 fail closed 并关闭连接。

## 20. 对局时间线与播放时间线

新创建对局把 Match 与 Presentation 拆成两条时间线：

- **Match**：模型请求在上一动作 `speech_sealed` 后立即开始；不传 `max_output_tokens` / `max_tokens`，也不执行 first_token / stream_idle / attempt_hard / action_wall。`claim_action` 不再被 `broadcasting` 挡住。
- **Presentation**：TTS、官方时钟和 `speech_closed` 只推进 `playback_cursor`。同一线路上仍只有一个 active presentation。
- 观众直播页（含导演投影）跟 `playback_cursor`：`game.phase_changed`、`player.state_changed`、`match.state_changed`、`dawn.result_announced`、`day.progress_changed` 带 `reveal_presentation_seq`，客户端仅当 `seq <= playback_cursor` 时渲染。
- 上帝视角 / Admin 跟 Match 真状态，快照仍带 `playback_cursor` 便于对照「对局已到 D3 / 语音播到 D1」。
- `awaiting_observation` 与 `lease is null` 且无 worker 的终局不被 reaper 收割。TTS 失败只标 `presentation.failed` 并前进 cursor，不回写对局失败。
- 冻结旧局继续走旧合同（白天 pipeline v1–v3、generation policy v4、pre-exile v1–v2）。新局冻结 pipeline v4、generation policy v6、pre-exile v3。
