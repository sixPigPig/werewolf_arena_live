# 固定 speech-v2 路径恢复决策记录

## 1. 结论

2026-07-21 的“删除分句、回到整段语音”阶段 A/B/C 路线已经终止。阶段 C 对第一至四期的删除被恢复，不再作为后续开发基线。

当前决策：

- 保留角色心智、ScenePacket、社交意图、硬门禁和情绪 delivery；
- 恢复 speech-v2 第一至四期；
- 新对局直接使用唯一的 `committed_segments_v2` 路径；
- 不做灰度、不做百分比分流、不保留运行时回退开关；
- 不兼容旧数据库、旧 Replay、旧客户端或旧 `segments_v1`；
- 删除会根据未来终局事件快进导演和语音队列的错误实现。

详细合同、分期范围、第五期和验收矩阵见[逻辑发言流 speech-v2：固定路径开发基线](./2026-07-20-logical-speech-streaming-v2-design.md)。

## 2. 从阶段 A/B/C 保留的有效修复

- 干净数据库初始化 12 个差异化虚拟玩家，避免新环境依赖历史数据才能开局；
- Planner 超时或异常使用已有确定性 turn plan，不直接吞掉公开发言；
- 终局事件不得裁剪尚未播放的历史 cue；
- API、模型、TTS 和播放 ACK 分阶段记账，不用统一 60 秒原因掩盖根因。

## 3. 被撤销的内容

- 删除 speech receipt、segment TTS、SpeechPlaybackSession、PCM 调度、preempt 和 Replay 恢复；
- `sentence_stream=off`、`tts_prefetch_depth=0`、`voice_preempt=off` 的固定整段语音合同；
- “阶段 C 已完成、第一至四期不再需要”的结论。

## 4. 终局跳转事故结论

“第一夜直接跳第三夜”不是自然完赛，也不是 speech-v2 必然行为。直接原因是客户端提前读取未来 `game_completed.terminal_keep_from_event_id`，随后过滤导演 cue、跳转当前游标并中断窗口外语音。

修复原则：

- 导演始终按时间线顺序消费 cue；
- 终局信息不能使当前游标前进；
- `voice_preempt` 只能处理相同 `speech_id`，不能裁剪其他 speech 或历史事件；
- Replay 默认从第一条事件开始，除非用户显式 seek。

## 5. 当前状态

前四期代码已经恢复并改成单一路径，正在执行跨层回归。真实连续对局和重启恢复属于新的第五期验收，尚未完成，因此不宣称项目已经稳定上线。
