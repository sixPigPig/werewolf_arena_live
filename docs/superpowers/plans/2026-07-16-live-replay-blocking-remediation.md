# 直播与复播阻塞收敛开发计划

**状态：** 已实施，待按任务拆分提交

**日期：** 2026-07-16

**目标：** 在不修改狼人杀规则、Prompt、角色行动语义和现有受众隐私边界的前提下，收敛直播/复播的异常阻塞、复播首屏大包、跳转后旧语音补播、双时钟尾部空白，以及回合结束后的隐藏等待。

## 0. 实施结果

- TASK-BLOCK-00 至 TASK-BLOCK-08 已按本文边界完成，并补齐对应回归测试；TASK-BLOCK-09 仅剩提交前的分任务暂存与差异复核。
- 直播终态连接失败、语音不可用、HTML Audio 停滞和服务端 ACK 超时均已 fail-open；用户主动暂停不计入 watchdog。
- 复播主响应仅保留数据库语音元数据，音频按 utterance 懒加载；播放完成、失败或显式跳转后立即释放已加载块，向后跳转时重新按需加载。
- 有语音 cue 由真实音频完成信号解除导演 hold；中文4字/秒、英文150词/分钟以及固定展示时间只保留为无语音、语音关闭或失败时的视觉 fallback。
- 私有回合记忆改为并发等待、顺序提交，保留原有失败、checkpoint、隐私和游戏语义边界。
- 真实完成对局 `game_079a55eb` 的 playback 主响应约 2.4 MB，92 条数据库语音均不再内嵌 chunks；单条语音可通过懒加载接口取得。
- 最终回归：API 334 passed、2 skipped；game-client 299 passed 并通过 typecheck；mobile-web 198 passed，并通过 lint、build 和 bundle budget。
- 未新增数据库迁移，未修改规则、Prompt、字幕样式、TTS 时间戳、受众投影或模型配置。

## 1. 背景与已确认问题

当前“阻塞”来自不同层次，不能用一个全局超时统一处理：

1. 直播导演在有语音条目时通过 `holdAdvance` 等待语音结束；连接异常若留下 `receiving` 条目，可能永久阻塞。
2. 复播接口把完整语音块以 base64 放进 playback JSON；当前样本仅音频字段约为 62.4 MiB 和 116.3 MiB，首屏必须等待整个响应下载和解析。
3. 复播显式跳转后，导演游标已经改变，但语音消费游标没有同步，可能从最早未消费语音开始补播。
4. 字幕已经由 TTS 时间戳驱动，但导演仍使用固定 2–8 秒和中文 4 字/秒、英文 150 词/分钟的估算时间；有语音时会形成第二套时钟和尾部无声等待。
5. 公开回合简报之后，后端按存活玩家串行生成私有回合记忆。最近样本出现 77–104 秒无公开事件空窗，直播端只能停在最后一条公开事件。

这些问题必须按依赖关系逐步修复。不得把“减少等待”扩大为直播 UI 重做、语音供应商替换、游戏规则调整或模型 Prompt 优化。

## 2. 范围

### 2.1 本计划包含

- 直播语音异常时可靠解除导演 hold；
- 服务端语音播放 ACK 有界等待；
- 复播 PCM 暂停/恢复时使用音频时钟判断真实完成；
- playback 主响应不再内嵌大体积的已保存 PCM 音频；
- 已保存语音按 utterance 懒加载，并继续兼容小体积内联静态法官语音；
- 复播显式跳转时同步语音游标；
- 有语音时以音频生命周期和 TTS 时间戳作为唯一主时钟；
- 无语音、语音关闭或语音失败时保留文字展示时间作为 fallback；
- 在不改变总结内容和落库顺序的前提下，缩短私有回合记忆的串行等待；
- 为每个阶段补充针对真实失败模式的回归测试。

### 2.2 明确非目标

- 不修改 `prompts_zh.py`、角色人设、策略、规则集、胜负条件或行动顺序；
- 不修改 live/replay 的 Player Public、God View 投影和鉴权语义；
- 不重新生成历史缺失语音，不调用 TTS 修补旧对局；
- 不引入对象存储、CDN、HTTP Range、媒体转码或新的音频格式；
- 不重做 `MobileLiveTheater` 布局、动画、字幕样式或座位表现；
- 不调整模型名单、模型路由、重试策略或供应商配置；
- 不把本计划扩展为通用媒体服务或通用时间轴框架；
- 不顺带清理无关技术债、重命名公共类型或格式化无关文件；
- 不修改现有数据库表结构；如果实现发现必须迁移数据库，立即停止并重新评审范围。

## 3. 实施约束

1. 每个实施任务单独提交，不允许把后端引擎、播放 API 和前端时钟改动混在一个提交中；TASK-BLOCK-00 是实施前置检查，不单独提交红灯测试。
2. 每个实施任务先在本地证明对应回归会失败，再修改实现；测试与修复在同一任务提交中保持绿灯，本任务测试通过后才能进入下一任务。
3. 任何行为改变必须由下文验收标准直接要求；未列出的行为保持不变。
4. 触及任务“允许文件”之外的业务文件前必须停止，先更新本计划并重新评审。
5. 不以增加更长超时掩盖游标、状态机或音频时钟错误。
6. 语音异常必须 fail-open：可以退回文字播放，但不能永久冻结导演。
7. 用户主动暂停除外；暂停状态允许无限期停止，且不得被 watchdog 自动推进。
8. 所有跳转都必须取消旧异步加载结果的播放资格，避免旧 Promise 回写当前状态。
9. 当前工作区已有其他未提交改动。实施时必须显式分文件/分 hunk 暂存，禁止把无关改动带入提交。

## 4. 目标播放模型

### 4.1 直播

```text
导演到达语音 source event
  -> 语音条目开始接收/播放
  -> holdAdvance=true
  -> 音频时钟和 TTS 时间戳推进字幕
  -> played: 记录该 source range 已由语音完成，立即解除 hold 并推进
  -> error/closed/stall: 解除 hold，继续使用当前文字 fallback
```

### 4.2 复播

```text
先加载事件和语音元数据
  -> 导演进入当前 cue
  -> 只懒加载当前或下一条语音
  -> 音频完成后解除 hold
  -> 显式跳转时取消当前音频、递增 cursor version、重建消费边界
  -> 目标之前语音直接跳过，目标及之后语音按新游标播放
```

### 4.3 单主时钟规则

- 已成功播放语音的 cue：音频生命周期是唯一推进依据；不得再等待固定 5 秒、6 秒、8 秒或 `longTextDuration()` 的剩余时间。
- 语音尚未开始：现有导演时间继续作为安全 fallback，防止 TTS 未到达时画面立即越过。
- 语音失败、关闭或缺失：继续使用现有文字展示时间；本计划不重新设计文字阅读速度。
- 纯视觉事件：继续使用导演展示时间。
- 本轮不新增 `postVoiceHoldMs`。投票、出局、终局等若已有语音，语音结束即推进；若无语音，继续使用现有结果卡片时间。
- 中文 4 字/秒、英文 150 词/分钟只保留为无语音 fallback，不再作为已播放语音 cue 的第二时钟。

## 5. API 兼容策略

为避免一次性破坏旧客户端，复播音频拆分采用兼容式切换：

1. 先增加单 utterance 音频接口，playback 主响应暂时仍保留现有 `chunks`。
2. 客户端先支持两种来源：优先使用已有内联 `chunks`，缺失时按 utterance 懒加载。
3. 客户端回归通过后，主响应才停止内联数据库保存的 PCM chunks。
4. 小体积静态法官语音继续内联，避免新增静态资产公开路由和鉴权分支。
5. 单 utterance 接口仍返回现有 JSON chunk 结构，不引入二进制媒体协议、Range 或转码。

建议接口：

```text
GET /api/v1/games/{session_id}/playback/voices/{utterance_id}
GET /api/v1/games/{session_id}/god-view/playback/voices/{utterance_id}
```

响应只包含 playback 主响应已经公开过的语音字段与该 utterance 的 chunks。接口必须验证 `session_id + utterance_id` 归属，并复用对应 playback 路由的受众与鉴权边界。

## 6. 有序任务列表

### TASK-BLOCK-00：冻结基线与补充失败回归

**目的：** 在任何行为修改前锁定现有正常路径和已确认异常路径。

**允许文件：**

- `packages/game-client/src/live/liveVoiceStream.test.tsx`
- `packages/game-client/src/live/livePlaybackVoice.test.tsx`
- `packages/game-client/src/live/liveDirectorHook.test.tsx`
- `apps/mobile-web/src/pages/LivePage.test.tsx`
- `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`
- `apps/api/tests/test_voice_stream_api.py`

**任务：**

- [x] 直播在已有 `receiving` 条目时 WebSocket 最终失败，测试证明当前条目仍会阻塞。
- [x] 复播 PCM 播放中暂停超过原计划结束时间，测试证明当前完成定时器会提前消费语音。
- [x] 复播从开头显式跳到后续事件，测试证明当前会选择目标之前最早未消费语音。
- [x] 短 TTS 语音播放完成后，测试证明当前导演仍可能等待固定/估算时间。
- [x] 保留现有正常路径：直播 PCM、非 PCM、暂停/恢复、重连、去重、复播字幕均保持通过。

**验收：** 实施前在本地证明新增异常用例能够击中当前问题，既有正常路径保持通过；红灯用例分别随对应修复任务提交，不产生独立的失败测试提交。

### TASK-BLOCK-01：保证语音阻塞一定可解除

**依赖：** TASK-BLOCK-00。

**允许文件：**

- `packages/game-client/src/live/liveVoiceStream.ts`
- `packages/game-client/src/live/liveVoiceStream.test.tsx`
- `packages/game-client/src/live/livePlaybackVoice.ts`
- `packages/game-client/src/live/livePlaybackVoice.test.tsx`
- `apps/api/app/werewolf/voice_stream.py`
- `apps/api/tests/test_voice_stream_api.py`
- `apps/mobile-web/src/pages/LivePage.tsx`
- `apps/mobile-web/src/pages/LivePage.test.tsx`
- `apps/mobile-web/src/pages/LiveReplayPage.tsx`
- `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`

**任务：**

- [x] WebSocket `error/closed/unavailable` 时，将当前未完成语音转成终态并解除 hold。
- [x] 个别 utterance `voice_error` 继续只终止对应条目，不影响后续条目。
- [x] HTML Audio 在非暂停状态下长时间无进度时 fail-open；暂停期间不计入 stall。
- [x] 直播 PCM 继续使用 `AudioContext.currentTime` 轮询完成，不改回墙钟总时长。
- [x] 复播 PCM 完成判断改为与直播一致的音频时钟轮询；暂停时取消轮询，恢复后重新 armed。
- [x] 服务端 `_wait_for_playback_ack()` 增加有界等待；超时仅放行下一语音，不把对局标记失败。
- [x] 用户关闭语音立即解除 hold，并清理当前音频、轮询和对象 URL。
- [x] 保证同一 utterance 只 ACK 一次，错误和超时不会产生重复播放。

**验收：**

- [x] 连接失败、播放拒绝、音频 stall、PCM 暂停/恢复都不会永久 hold。
- [x] 用户主动暂停仍不会自动推进。
- [x] 语音异常不会导致游戏 run 失败。
- [x] 直播/复播现有语音顺序和去重测试保持通过。

### TASK-BLOCK-02：增加单 utterance 懒加载接口

**依赖：** TASK-BLOCK-01。

**允许文件：**

- `apps/api/app/werewolf/voice_store.py`
- `apps/api/app/api/routes/games.py`
- `apps/api/tests/test_voice_store.py`
- `apps/api/tests/test_games_api.py`

**任务：**

- [x] 增加按 `session_id + utterance_id` 查询一条已完成公开语音及 chunks 的 store 方法。
- [x] 查询拒绝 failed、synthesizing、无 chunk、非 public speaker kind 和不属于该 session 的记录。
- [x] 增加 player-public 与 god-view 对应的单 utterance 路由，并复用现有鉴权边界。
- [x] 不返回文件路径、供应商凭证、内部 Prompt、私有事件或私有回合总结语音。
- [x] 第一阶段保持 playback 主响应兼容，不在此任务删除现有 chunks。

**验收：**

- [x] 合法 utterance 返回有序 chunks 和现有音频元数据。
- [x] 跨 session、私有或不存在 utterance 返回 404，不泄露记录是否存在。
- [x] 现有 playback API 合同暂不变化。
- [x] 不新增数据库迁移。

### TASK-BLOCK-03：客户端支持按当前语音懒加载

**依赖：** TASK-BLOCK-02。

**允许文件：**

- `packages/game-client/src/types.ts`
- `packages/game-client/src/api/getGamePlayback.ts`
- `packages/game-client/src/api/endpoints.test.ts`
- `packages/game-client/src/live/livePlaybackVoice.ts`
- `packages/game-client/src/live/livePlaybackVoice.test.tsx`
- `apps/mobile-web/src/pages/LiveReplayPage.tsx`
- `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`

**任务：**

- [x] `PlaybackVoiceUtterance.chunks` 改为兼容可选/空列表，不影响旧内联响应。
- [x] 增加按 session 和 utterance 获取 chunks 的 API client。
- [x] `usePlaybackVoice` 只在语音即将播放时请求该 utterance 的 chunks。
- [x] 同一 utterance 请求去重；当前语音结束前最多预取下一条，不预取整局。
- [x] 禁用语音、组件卸载或显式跳转时，取消旧请求结果的播放资格。
- [x] 懒加载失败只跳过该条语音并退回文字，不阻塞后续播放。
- [x] 继续兼容内联静态法官语音，不为其发起额外请求。

**验收：**

- [x] 页面拿到事件和元数据后即可渲染，不等待全部音频。
- [x] 任一时刻只保留当前/下一条必要音频数据，不把整局 base64 常驻前端状态。
- [x] 旧 playback 响应仍能播放；新元数据响应也能播放。
- [x] 加载失败、取消和竞态不会重新激活旧语音。

### TASK-BLOCK-04：从 playback 主响应移除已保存 PCM chunks

**依赖：** TASK-BLOCK-03。

**允许文件：**

- `apps/api/app/werewolf/voice_store.py`
- `apps/api/app/api/routes/games.py`
- `apps/api/tests/test_voice_store.py`
- `apps/api/tests/test_games_api.py`
- `packages/game-client/src/api/endpoints.test.ts`

**任务：**

- [x] playback 主响应中的数据库语音只返回元数据，不返回 chunks base64。
- [x] 静态法官 fallback 保持现有小体积内联 chunks。
- [x] `voice_coverage` 继续基于元数据计算，不依赖主响应内联音频。
- [x] 保持 event timeline、source/last source 映射和排序不变。

**验收：**

- [x] 大体积 PCM sentinel 不出现在 playback 主响应。
- [x] 当前两类 playback 路由均返回完整语音元数据。
- [x] 复播首屏响应体不再随 PCM 总时长线性增长。
- [x] 静态法官语音仍可播放。

### TASK-BLOCK-05：同步复播导演游标与语音游标

**依赖：** TASK-BLOCK-04。

**允许文件：**

- `packages/game-client/src/live/liveDirector.ts`
- `packages/game-client/src/live/liveDirectorHook.test.tsx`
- `packages/game-client/src/live/livePlaybackVoice.ts`
- `packages/game-client/src/live/livePlaybackVoice.test.tsx`
- `apps/mobile-web/src/pages/LiveReplayPage.tsx`
- `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`
- `apps/mobile-web/src/components/MobileLiveTheater.tsx`（仅在需要传递显式跳转版本时）
- `apps/mobile-web/src/components/MobileLiveTheater.test.tsx`（仅对应上述最小改动）

**设计约束：**

- `useLiveDirector` 增加只在显式 `seekToEventId`、`catchUpToLatest` 和 reset 时递增的 `cursorVersion`；普通自动前进不得递增。
- `usePlaybackVoice` 接收 `cursorVersion`。版本变化时取消当前音频和旧异步结果，并按目标事件重建消费边界。
- 对目标事件 `T`：`last_source_event_id < T` 的语音视为已跳过；覆盖或等于 `T` 的语音允许播放；未来语音保持未消费。
- 向后跳转使用同一规则重建集合，不维护易漂移的增量回滚逻辑。

**任务：**

- [x] 增加 `cursorVersion`，保持现有 director API 其余语义不变。
- [x] 点击事件、阶段和“最新”都触发显式版本变化。
- [x] 跳转时停止当前音频、清除 hold、取消旧懒加载结果。
- [x] 目标之前语音不补播，目标语音正常播放。
- [x] 向后跳转后目标及后续语音可再次播放。

**验收：**

- [x] 从开头跳“最新”不会串行播放旧语音。
- [x] 跳到某阶段不会播放该阶段之前的语音。
- [x] 自动前进不误判为 seek，不会重复清空队列。
- [x] 快速连续跳转只允许最后一次目标播放。

### TASK-BLOCK-06：有语音时切换为 TTS 单主时钟

**依赖：** TASK-BLOCK-01、TASK-BLOCK-05。

**允许文件：**

- `packages/game-client/src/live/liveDirector.ts`
- `packages/game-client/src/live/liveDirectorHook.test.tsx`
- `packages/game-client/src/live/liveVoiceStream.ts`
- `packages/game-client/src/live/liveVoiceStream.test.tsx`
- `packages/game-client/src/live/livePlaybackVoice.ts`
- `packages/game-client/src/live/livePlaybackVoice.test.tsx`
- `apps/mobile-web/src/pages/LivePage.tsx`
- `apps/mobile-web/src/pages/LivePage.test.tsx`
- `apps/mobile-web/src/pages/LiveReplayPage.tsx`
- `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`

**设计约束：**

- 语音 hook 暴露最近一次成功播放完成的 source range；不得由页面直接无条件调用 `director.advance()`。
- director 只在当前 cue 被该成功 range 覆盖时把剩余展示时间视为 0，防止旧语音完成推进错误 cue。
- `error`、`closed`、`unavailable` 不标记“语音已成功完成”，而是解除 hold 并继续沿用已经开始计算的文字 fallback。
- `longTextDuration()` 和固定 cue 时间暂时保留，作为无语音 fallback；不在本任务大范围删除映射。

**任务：**

- [x] 直播和复播语音 hook 返回可去重的成功完成 range/token。
- [x] director 接收外部完成信息，仅对匹配 cue 清零剩余时间。
- [x] 短语音结束后立即推进，不再补足 5/6/8 秒或长文本最低6秒。
- [x] 长语音不受20秒上限提前推进，始终播放到音频时钟结束。
- [x] 语音关闭、缺失或失败时仍按现有导演时间播放文字。
- [x] TTS 字幕继续完全使用已有时间戳，不改字幕分页、颜色和样式。

**验收：**

- [x] 开局、阶段、法官提示、玩家发言和终局的有语音路径不存在尾部无声等待。
- [x] 无语音路径仍有可读的视觉展示时间。
- [x] 语音完成 token 不会跨 cue、跨 seek 或跨 run 生效。
- [x] 1x/2x 只影响无语音导演时间，不改变真实音频速度。

### TASK-BLOCK-07：收敛导演时间语义

**依赖：** TASK-BLOCK-06。

**允许文件：**

- `packages/game-client/src/live/liveDirector.ts`
- `packages/game-client/src/live/liveDirector.test.ts`
- `packages/game-client/src/live/liveDirectorHook.test.tsx`

**任务：**

- [x] 在类型和注释中明确 `durationMs` 是视觉/fallback时间，不是字幕时间。
- [x] 中文4字/秒、英文150词/分钟仅用于无语音 fallback。
- [x] 保留纯视觉模型状态、阶段和结果卡片的当前展示时间，不重新调参。
- [x] 删除仅在确认完全不可达后才允许删除的重复计时分支；不做顺手重构。
- [x] 保留 backlog≥8 时普通可压缩 cue 的500ms追播规则。

**验收：**

- [x] 代码中不再把 TTS 字幕时间和视觉阅读估算描述为同一个时钟。
- [x] 不改变 cue 分类、标题、正文、importance 和 compressible 语义。
- [x] 不新增动画时间或结果停留时间。

### TASK-BLOCK-08：缩短私有回合记忆空窗

**依赖：** TASK-BLOCK-00；与前端任务分开提交，建议最后实施。

**允许文件：**

- `apps/api/app/werewolf/engine.py`
- `apps/api/tests/test_werewolf_runner.py`

**设计约束：**

- 只调整 `_run_private_round_memories()` 的执行方式。
- 每位玩家的 request 必须基于与当前串行实现等价的输入快照。
- 模型调用可以受控并行，但结果必须按 `active_players` 原顺序写入 `private_summaries`、observations 和 `round_log.summaries`。
- 不发布 summary 文本、玩家身份或模型进度到公开事件。
- 不修改 Prompt、summary 内容解析、checkpoint 结构或全局 action budget 默认值。

**任务：**

- [x] 先补充串行基线测试，锁定 summary 顺序和每位玩家观察写入结果。
- [x] 预构建独立 request 快照，使用现有受控批处理能力并发模型等待。
- [x] 保持提交结果顺序、异常处理和 checkpoint 语义不变。
- [x] 增加慢 Provider 测试，证明总等待接近最慢单次调用而不是所有调用之和。
- [x] 增加单个 summary 失败测试，保持当前失败边界，不静默吞错。

**停止条件：** 如果并行化会改变 Provider 调用顺序、Prompt 输入、checkpoint 恢复结果或确定性测试结果，则本任务停止，不通过扩大引擎重构解决。

**验收：**

- [x] 私有 summary 内容、顺序和落库结构与现状一致。
- [x] 不新增公开隐私信息。
- [x] 不修改游戏行动、胜负和回合推进语义。
- [x] 慢 Provider 场景不再按存活玩家数量线性累计等待。

### TASK-BLOCK-09：全链路回归与发布门禁

**依赖：** 所有实际实施的前置任务。

**任务：**

- [x] API：运行 voice store、games API、voice stream、werewolf runner 定向测试。
- [x] Game client：运行 live director、live voice、playback voice 全量测试与 typecheck。
- [x] Mobile web：运行 LivePage、LiveReplayPage、MobileLiveTheater 定向测试、lint 和 build。
- [x] 使用一局短语音夹具验证直播正常、关闭语音、TTS失败和重连。
- [x] 使用一局多语音复播夹具验证首屏不携带整局 PCM、懒加载、暂停和连续 seek。
- [x] 对真实完成 session 复核 playback 主响应大小，不包含数据库 PCM base64。
- [x] 复核 Player Public 与 God View 两条 playback 路由的事件和语音投影未发生漂移。
- [ ] 提交前运行 `git diff --check`，逐任务检查 staged diff，确认无关工作区改动未进入提交。

**发布门禁：** 任一以下情况出现时不得继续合并：

- 直播或复播能在非用户暂停状态永久 hold；
- seek 后播放目标之前的旧语音；
- TTS失败导致页面或游戏 run 失败；
- playback 主响应仍包含数据库 PCM chunks；
- Player Public 获得新增私密事件、语音或角色信息；
- 私有总结并行化改变 Prompt、总结顺序、checkpoint 或游戏结果；
- 为通过测试而扩大超时、跳过断言或删除既有回归。

## 7. 推荐提交顺序

TASK-BLOCK-00 只作为本地前置验证，不创建红灯提交。其余任务的回归测试与对应实现一起提交：

1. `fix(voice): release playback holds on terminal failures`
2. `feat(replay): add lazy playback voice endpoint`
3. `feat(replay): load saved voice on demand`
4. `perf(replay): remove saved PCM from playback payload`
5. `fix(replay): synchronize voice cursor with explicit seeks`
6. `fix(live): use completed TTS audio as the primary cue clock`
7. `refactor(live): clarify director fallback timing semantics`
8. `perf(engine): batch private round memories`（仅在 TASK-BLOCK-08 门禁全部满足时）

## 8. 完成定义

只有同时满足以下条件，本计划才算完成：

- 非用户暂停情况下不存在永久导演 hold；
- 复播首屏不再传输整局数据库 PCM；
- 复播显式跳转不补播目标之前语音；
- 有语音 cue 只由音频完成驱动，不再叠加固定/估算阅读时间；
- 无语音 cue 仍保持现有可读 fallback；
- 私有总结优化不改变任何游戏语义或隐私边界；
- 所有定向测试、typecheck、lint、build 和 staged diff 检查通过；
- 每个提交只包含对应任务的文件和行为。
