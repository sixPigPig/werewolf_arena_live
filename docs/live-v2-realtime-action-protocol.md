# Live V2 单次实时动作与直播协议草案

> 状态：已确认（2026-07-22）。只授权实现本文定义的第一句话垂直切片，不授权开发第二动作。

## 1. 本步唯一目标

打通一个可以由用户亲自观察的最小垂直切片：

> Mobile 用户点击进入实时直播后，服务端通过全新的 V2 模型客户端实时生成法官开场的第一句话，通过全新的 V2 TTS 客户端实时产生音频块；同一份 PCM 一路交给全新的 V2 WebSocket 实时广播，另一路由全新的 V2 Voice Recorder 保存为不可变语音资产。第一句话的官方音频时钟结束且语音资产保存完成后，流程停在 `awaiting_observation`，不开始第二个动作。

这句话不读取静态 `game_intro`，也不从旧对局、旧直播或 Replay 中获取。

## 2. 本步明确不做

- 不开始第二句话或第二个动作。
- 不创建玩家阵容，不分配身份，不进入首夜。
- 不实现投票、技能或胜负结算。
- 不接收、存储、聚合真实弹幕，只固定弹幕影响输入接口。
- 不实现 Replay、追播、暂停、倍速、Seek 或历史音频补发。
- 不实现模型重试、备用模型或 TTS 备用供应商；失败后明确停止。
- 不实现上帝视角，只保留服务端投影边界。
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
| V2 Action Engine | 驱动一次动作并决定唯一状态转换 | 播放历史、等待客户端 ACK |
| V2 Model Client | 发起一次真实模型流并返回增量 | 决定游戏规则、公开原始 token |
| V2 Sentence Gate | 从增量中确认一个完整且可公开的句子 | 改写成另一个意思、生成兜底台词 |
| V2 TTS Client | 把已确认句子转换为流式 PCM | 决定展示顺序 |
| V2 Live Broadcaster | 建立官方音频时钟并广播当前内容 | 读取数据库历史追播 |
| V2 Voice Recorder | 顺序保存广播所用的同一份 PCM，并原子完成语音资产 | 调整广播顺序、触发补播、向公开直播暴露历史音频 |
| V2 Repository | 保存动作证据和当前投影 | 充当直播播放队列 |
| Mobile V2 Client | 消费当前快照和未来帧并播放 PCM | 推动全局游戏、请求缺失历史块 |

规则推进仍然是确定性代码。大模型负责动作中的内容或选择；规则合法性、阶段转换、胜负判断不能由模型自由决定。

## 5. 身份与序列

第一切片创建以下稳定标识：

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

第一切片只有一个 action、一个 speech、一个 presentation 和一个 segment。

## 6. ActionContext 与弹幕影响预留

每一次模型请求都必须由 Action Engine 生成独立的 `ActionContext`。第一切片的逻辑结构为：

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
  "objective": "生成本场直播的法官开场第一句话",
  "output_contract": {
    "kind": "public_speech",
    "language": "zh-CN",
    "sentence_count": 1
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

本步的 `influence` 只能是上述禁用值。未来弹幕系统只能生产这个字段，不能绕过 Action Engine 直接修改规则、提示词、展示状态或音频队列。

## 7. 服务端状态机

### 7.1 动作状态

| 当前状态 | 唯一输入 | 动作 | 下一状态 | 对外表现 |
| --- | --- | --- | --- | --- |
| `ready` | 首个已完成音频解锁的 V2 客户端发送 `client.ready` | 创建 `action_id` 和 ActionContext | `model_streaming` | `live.state_changed: generating` |
| `model_streaming` | 新 V2 模型客户端返回增量 | 仅在服务端累积和检查，不公开原始 token | `model_streaming` | 无公开字幕 |
| `model_streaming` | Sentence Gate 接受第一句完整文本 | 持久化句子，关闭本次模型流，封口 speech | `sentence_committed` | 依次发送 `presentation.opened`、`speech.segment_committed` |
| `sentence_committed` | 新 V2 TTS 客户端返回首个有效 PCM 块 | 创建状态为 `writing` 的 `voice_asset_id`，同一 PCM 块同时送入 recorder 和 broadcaster | `audio_streaming` | 发送带相同展示标识的音频帧 |
| `audio_streaming` | TTS 正常结束 | 冻结最终 sample 数，停止接收新块，等待广播时钟和 recorder 收尾 | `finalizing` | `live.state_changed: finalizing`，保持当前 presentation |
| `finalizing` | 官方时钟走完最后一个 sample，且语音资产已原子保存为 `ready` | 关闭 presentation、speech 和 action | `succeeded` | `presentation.closed`，随后 `live.state_changed: awaiting_observation` |
| 任意非终态 | 明确的模型、质量、TTS、录音、广播或协议错误 | 记录唯一失败分类，停止当前资源 | `failed` | `presentation.failed` 或 `live.state_changed: failed` |

`succeeded` 和 `failed` 都是终态。第一切片不得从终态自动创建下一个动作。

`client.ready` 只是第一切片的一次性启动门禁，用来确保浏览器已通过用户手势解锁音频；它不是播放 ACK，不能在动作之间控制推进。

### 7.2 发言生命周期

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

### 7.3 展示状态

```text
none -> active -> closed
               -> failed
```

- 任意时刻最多一个 `active` presentation。
- `closed` 或 `failed` 后，当前快照中的 `current_presentation` 必须变为 `null`。
- 新连接只能加入仍在 `active` 的 presentation，并从加入后的音频位置开始。
- 已结束的 presentation 永不重新激活。

## 8. WebSocket 连接

第一切片只提供普通直播入口：

```text
GET /api/v2/live/games/{game_id}/ws
```

连接规则：

1. 服务端建立连接后立即发送 `live.snapshot`。
2. Mobile 必须先通过用户点击解锁 `AudioContext`，再发送一次 `client.ready`。
3. 服务端之后只发送连接建立后的当前和未来内容。
4. WebSocket 断开不会暂停或终止全局动作。
5. 重连重新从第 1 步开始，不提交历史 cursor，也不补发断线期间的音频。
6. 普通入口永远只返回普通直播投影；未来上帝视角必须使用独立鉴权入口，不能由客户端参数提权。

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
  "live_state": "ready",
  "latest_presentation_seq": 0,
  "current_presentation": null
}
```

若重连时正在播报，`current_presentation` 只包含当前展示、当前字幕和加入时的 `join_sample_cursor`，不包含已经发送的音频块。若播报已经结束，则必须为 `null`。

### 9.2 `client.ready`：客户端到服务端

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

每条连接最多接受一次。首个满足条件的 `client.ready` 可以原子地启动本切片；后来连接的 `client.ready` 只标记该连接具备播放能力。重复消息幂等，任何并发连接都不得创建第二个 action。

### 9.3 `live.state_changed`：服务端到客户端

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

第一切片允许的状态为：`ready`、`generating`、`broadcasting`、`finalizing`、`awaiting_observation`、`failed`。

### 9.4 `presentation.opened`：服务端到客户端

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

### 9.5 `speech.segment_committed`：服务端到客户端

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
  "text": "模型实时生成的一句完整法官开场白。"
}
```

字幕必须在第一个音频块之前送达，并与音频使用完全相同的 `presentation_id`、`speech_id` 和 `segment_index`。

### 9.6 `presentation.closed`：服务端到客户端

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
  "result": "audio_drained_and_voice_saved"
}
```

该消息只能在官方音频时钟走完最后一个 sample 后发送，不能在 TTS 返回结束或最后一帧刚写入 socket 时提前发送。

### 9.7 失败消息：服务端到客户端

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
| `awaiting_observation` | `current_presentation=null` | 不播放刚结束的第一句话 |
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

第一切片至少记录：

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
12. `audio_broadcast_completed` 或明确广播失败事件
13. `action_succeeded` 或 `action_failed`

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

## 13. 现有基础脚手架的影响

以下现状不能进入正式实时链路，下一步实现时需要在 V2 内替换：

- `create_opening_game()` 当前直接提交静态 `game_intro`。
- `app/v2/service.py` 和 `app/v2/router.py` 当前仍导入旧 `app.werewolf.judge_voice_assets`，已经违反新的零复用准则；下一步必须删除这两个依赖，不能包装后继续使用。
- 当前 snapshot 返回完整音频 URL，会让后来连接的观众播放历史整段音频。
- `V2LivePresentation` 当前假设创建展示时已经存在完整静态音频；新流程需要关联处于 `writing` 状态的 V2 语音资产，并在流结束后更新为 `ready`。
- Mobile 当前使用 `HTMLAudioElement` 播放整段 MP3。
- 重构准则已经同步收紧：只允许共享框架、第三方 SDK、配置值和运行基础设施，禁止导入、包装、复制或改名迁移旧业务实现。

保留的基础是 V2 路由边界、V2 对局/运行/事件命名空间、Admin V2 记录入口和 Mobile V2 独立页面；它们不构成复用旧直播业务逻辑的理由。

## 14. 下一步预计修改的模块

只有本文获得确认后，才允许设计具体文件差异。预计边界为：

- API：V2 Action Engine、V2 模型客户端、V2 TTS 客户端、V2 WebSocket broadcaster、V2 Voice Recorder、V2 repository 和协议类型。
- 数据库：补足 `action_id`、流式 presentation 状态、动作证据和全新 V2 语音资产元数据；保存完整 WAV 文件，但不创建音频块表。
- Mobile：V2 WebSocket 客户端、严格消息 reducer、独立 PCM 播放器和观察状态 UI。
- Admin：展示本次 action 的模型/TTS/录音/广播证据，并通过受权 V2 接口播放已保存语音；不扩展对局操作能力。
- 测试：导入边界、状态机、协议、语音资产一致性、重连不追播、失败关闭和跨层真实运行验证。

## 15. 自动化验收标准

- V2 对被禁止的旧业务模块保持零导入。
- 一次 `client.ready` 只创建一个 action；重复消息不创建第二个。
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
- 刷新或重连后不播放已经结束的第一句话。
- 模型、质量、TTS、录音、广播或协议失败均明确终止，且不开始第二动作。
- 普通直播帧不包含模型内部提示、原始响应或秘密上下文。

## 16. 用户观察清单

1. 打开 Mobile V2 页面时，尚未点击前不会偷偷开始模型请求或播放。
2. 点击“进入实时直播”后，页面先显示法官正在生成内容。
3. 字幕是本次真实模型生成的一句完整文本，不是静态 `game_intro`。
4. 字幕出现后开始实时声音，画面、字幕和声音都属于法官。
5. 声音结束后页面显示“等待本步验收”，不出现第二句话。
6. 此时刷新页面，不会重新播放刚才那句话。
7. Admin V2 记录能看到同一个 `run_id`、`action_id`、模型耗时、TTS 耗时、`voice_asset_id` 和广播结束证据。
8. 在 Admin V2 播放保存语音，内容必须与刚才直播听到的第一句话一致。
9. 任一观察不符合时，只修复这一切片，不进入下一动作。
