# 逻辑发言流 speech-v2：固定路径开发基线

## 1. 文档状态

- 状态：前四期已恢复，进入回归验证；第五期尚未实施。
- 生效日期：2026-07-21。
- 适用对象：新建对局、Live、Replay、God View、API、语音 worker、Mobile 和 game-client。
- 数据边界：项目尚未上线，不兼容旧数据库、旧 Replay、旧客户端或进行中的旧对局。
- 发布边界：不做灰度、不做百分比分流、不保留运行时回退开关。

本文是后续开发和验收的唯一 speech-v2 基线。2026-07-20 版本中关于
`segments_v1` 兼容、control/treatment、Admin 灰度页、自动回退和双协议协商的设计全部作废。

## 2. 目标与非目标

目标：在不删除角色心智、社交意图和情绪表达的前提下，把一次公开发言拆成多个已经通过硬门禁的稳定句段，使第一段可以尽早进入 TTS，同时保持整次发言的唯一身份、顺序、封口、恢复和打断语义。

非目标：

- 不直接播放模型 raw token 或未通过门禁的草稿；
- 不用未来的终局事件裁剪尚未播放的历史时间线；
- 不让 TTS、WebSocket 或客户端 ACK 改变游戏规则状态机结果；
- 不用增加总超时时间掩盖重复重试、队列阻塞或 worker 版本漂移；
- 不保留旧模式作为线上第二条执行路径。

## 3. 唯一运行合同

所有新对局固定冻结同一个快照：

```json
{
  "experience_revision": "liveness-v1",
  "speech_stream_version": "speech-v2",
  "feature_modes": {
    "style_gate": "async_observe",
    "actor_mind": "read",
    "sentence_stream": "committed_segments_v2",
    "affect_delivery": "on",
    "tts_prefetch_depth": 1,
    "voice_preempt": "deterministic"
  }
}
```

这些字段是持久化合同和诊断信息，不是运行时开关。解析器只接受上面的完整组合；缺失、旧值和未知值全部 fail-closed。数据库中的 `speech_stream_mode` 只允许 `segments_v2`。

代码回退只使用 Git，不在产品中维护第二套模式。

## 4. 权威数据流

```text
ActorMind + ScenePacket + 确定性 fallback plan
                    ↓
            Renderer 流式生成
                    ↓
     完整句边界 + 增量硬门禁 + 总长度预算
                    ↓
       durable accepted_segment（顺序不可逆）
                    ↓
       segment TTS 物化 / audience 隔离
                    ↓
       SpeechPlaybackSession 连续 PCM 播放
                    ↓
       action_parsed seal（整次发言唯一封口）
                    ↓
        speech ACK / checkpoint / Replay
```

四个事实边界：

1. raw model delta 不是公开事实；
2. `accepted_segment` 是已经通过门禁、不可撤回的公开句段；
3. `action_parsed` 是整个 speech 的唯一权威封口；
4. playback ACK 只记录交付结果，不回写规则状态。

## 5. 核心身份和顺序

一次公开行动固定一个 `action_id` 和一个 `speech_id`。每个句段包含：

```json
{
  "schema_version": 2,
  "commit_state": "accepted_segment",
  "speech_stream_mode": "segments_v2",
  "speech_id": "sp_...",
  "segment_id": "seg_...",
  "segment_index": 0,
  "segment_final": false,
  "presentation_id": "pres_...",
  "visible_text": "已经通过门禁的完整句。"
}
```

约束：

- `segment_index` 从 0 连续递增，不允许缺口、重复身份或换 `speech_id`；
- v2 句段不能自行声明 `segment_final=true`；
- `action_parsed.final_segment_index == segment_count - 1` 才完成封口；
- seal 后禁止追加句段；
- Live、checkpoint 和 Replay 对相同 `presentation_id` 必须幂等。

## 6. 门禁与重试

首段低延迟不能绕过完整发言规则：

- 只有完整句边界才允许 commit；
- system artifact、隐私泄漏和确定性规则错误在 commit 前拒绝；
- 总长度超限时只保留预算内最后一个完整句，未完成尾巴不得分块泄漏；
- Planner 超时或异常使用请求中已有的确定性 plan，不吞掉公开发言；
- Renderer 最多两次尝试。增量门禁和外层质量重写共用这个预算，不叠加成四次请求；
- TTS 失败、ACK 超时和模型生成失败分别记账，不共享一个笼统的 60 秒原因。

## 7. 第一期：durable segments-v2 与 seal

实现范围：

- `speech_turn_receipts`、`speech_turn_segments` 和唯一 v2 数据库约束；
- accepted segment 的稳定 ID、序号、文本哈希和 presentation ID；
- `action_parsed` seal、`final_segment_index` 和持久化坐标；
- checkpoint 子集校验、崩溃窗口 reconciliation 和 seal 后禁止追加；
- Replay 按 receipt 重建相同 accepted segments 与 seal；
- 隐私投影只公开允许的 committed 字段。

退出标准：重复事件幂等、缺号拒绝、篡改拒绝、seal 坐标一致、Replay 文本与 receipt 完全一致。

## 8. 第二期：SpeechPlaybackSession 状态机

实现范围：

- 发言级状态：opened、buffering、playing、sealed、completed、interrupted；
- 句段按 `(speech_id, segment_index)` 接收，重复消息幂等；
- 当前 speech 与导演 cue 通过 `speech_id` 对齐；
- 开发环境 shadow reducer 观察真实消息，但不创建第二套产品模式；
- Mobile bridge 将发言级完成坐标映射回折叠时间线。

退出标准：乱序、重复、seal 先到、断线重放和多 audience 消息不会重复播放或提前完成 cue。

## 9. 第三期：连续 PCM 与发言级流控

实现范围：

- 同一 speech 的多个 PCM 句段进入连续 scheduler；
- 字幕使用音频时钟，不使用估算文本时长冒充播放进度；
- 每个 utterance 独立发送 completed/interrupted/skipped/failed ACK；
- TTS materialization 保留 speech、segment 和 audience 身份；
- `tts_prefetch_depth=1` 是固定常量，只允许当前段后预取一段；
- 音频播放阻塞只约束匹配当前 cue 的 speech。

退出标准：句间不重复建播放器、无重叠播放、ACK 不死锁导演、Player Public 与 God View 不串音。

## 10. 第四期：恢复、确定性打断、Replay 与多 audience

实现范围：

- 重连从 durable utterance、segment receipt 和播放观测恢复；
- `voice_preempt` 只按相同 `speech_id` 中断当前或已排队句段；
- 打断使用确定的 `cut_after_segment_index`，并逐 utterance 回 ACK；
- 恢复重发 `action_parsed` 时保留原 speech-v2 seal 和 delivery snapshot；
- Replay 使用与 Live 相同的 speech/segment/presentation 身份；
- 多 audience 独立物化、排队、ACK 和恢复。

明确禁止的旧实现：客户端不能因为事件列表中已经出现未来 `game_completed`，就过滤导演 cue、跳到 `terminal_keep_from_event_id` 或清空历史语音队列。终局只能在导演自然到达对应事件时展示；语音打断不能快进时间线。

退出标准：API 或语音连接中断后不丢段、不重播已完成 presentation；打断不影响其他 speech；从第一条事件顺序播放到终局，不跨夜跳转。

## 11. 第五期：固定路径稳定化与延迟优化

旧第五期“灰度与自适应回退”已取消。新的第五期只优化唯一 speech-v2 路径：

1. 干净数据库执行到唯一 migration head，并验证 6/8/12 人新对局可创建；
2. 连续真实运行至少 10 局，逐局核验事件、receipt、TTS、ACK、完赛和 Replay；
3. 各执行一次 API 重启、语音 worker 重启和浏览器重连；
4. 建立分阶段延迟指标：Planner、Renderer 首 token、首段 commit、TTS 首音频、首播放、speech 完成；
5. 删除重复等待和重复模型重试，限制队列水位，验证 worker/API 协议一致；
6. 只有证据表明不增加乱序、重复、缺音和失败率时，才调整固定预取深度或句段策略；
7. 不新增 percentage、variant、Admin 灰度页、运行时回退开关或旧协议兼容。

第五期验收结果必须给出具体 run_id、失败分类和 Replay 证据，不能用单元测试代替真实对局。

## 12. 跨层验收矩阵

| 层 | 必须证明 |
|---|---|
| Migration/Model | 只有 `segments_v2`；receipt、segment、utterance 和 playback 外键/约束一致 |
| Engine | Planner 降级可用；句段门禁、长度预算、两次 Renderer 上限、seal 正确 |
| Live Store | 事务内写 event 与 receipt；重复幂等；crash reconciliation fail-closed |
| Voice Worker | segment 只物化一次；speech/segment/audience 身份完整；preempt 可重放 |
| WebSocket | opened/start/chunk/end/sealed/preempt 顺序和重连合同正确 |
| game-client | speech session、连续 PCM、逐 utterance ACK、无终局快进 |
| Mobile | speech 字幕聚合、director bridge、Live/Replay 顺序一致 |
| Admin | 只展示固定 liveness 合同和诊断，不提供灰度控制 |
| Replay | 句段、seal、presentation、delivery 与 Live 一致 |

## 13. 当前实施记录

- 2026-07-20：第一期 durable segments-v2、第二期 shadow speech session、第三期 PCM/ACK、第四期恢复/打断/Replay/多 audience 完成初版。
- 2026-07-21：曾为稳定性排查撤销 speech-v2；该路线随后被否决。
- 2026-07-21：恢复前四期，删除灰度、experiment/variant、旧 v1 合同和运行时开关；所有新对局固定使用 speech-v2。
- 2026-07-21：删除终局事件提前裁剪导演与语音 backlog 的实现，增加“不跳过历史 cue”回归。
- 2026-07-21：修复超长尾巴绕过完整句长度门禁、双层重试放大为四次 Renderer 调用、恢复重发遗漏 speech seal 等边界。
- 第五期尚未执行；当前不能宣称已经通过真实连续对局稳定性验收。
