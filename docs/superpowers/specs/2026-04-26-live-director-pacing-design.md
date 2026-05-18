# 狼人杀实时直播导播节奏优化设计方案

**日期**: 2026-04-26
**范围**: 优化实时观战页的观看节奏，解决当前对局信息一闪而过的问题。第一期同时提供前端导播队列和后端演示慢速模式。

> **2026-05-18 修订**: 本文中“后端演示慢速模式”、`event_pacing` 三档延迟和创建对局页“演示慢速”控件已被废弃。新的基准设计是后端一律正常速度执行，仅由前端导播控制播放速度；详见 `docs/superpowers/specs/2026-05-18-frontend-only-live-playback-pacing-design.md`。

## 1. 背景

当前实时观战页直接由 SSE 事件驱动页面焦点。后端在一次玩家行动中会连续发布 `action_requested`、`model_request_started`、`model_response_received`、`action_parsed`、`state_updated` 等事件。当前前端每收到新事件就重算观战状态，导致中间主画面和玩家焦点很快被下一条事件覆盖。

这种实现适合调试事件流，但不适合观看。用户常常还没有读完模型回复、发言或投票结果，画面就已经跳到下一条事件，形成“信息闪过”的体验。

## 2. 用户确认的方向

本轮讨论确认采用 **前端导播为主 + 后端演示慢速**：

- 默认对局不拖慢后端执行，模型调用和引擎仍按原速度完成。
- 前端新增导播队列，把原始事件按观赛节奏播放。
- 主画面播放所有事件，但不同事件有不同停留时长。
- 队列积压时自动追进度：普通事件缩短停留，关键事件保持可阅读。
- 一期增加创建对局时的“演示慢速”选项，让后端按配置延迟推进，适合现场演示。

## 3. 目标

- 直播主画面不再直接跟随最新事件，而是按导播队列播放。
- 所有实时事件都能在主画面出现，避免隐藏模型过程。
- 长文本、发言、投票、出局、胜负等关键内容有足够停留时间。
- 后端跑得快时，前端能自动压缩普通事件，避免永远追不上。
- 用户可以暂停、继续、追到最新，并看到当前队列积压状态。
- 创建对局时可以选择演示慢速，让后端事件发布也变慢。
- 保留原始事件列表，继续服务调试和完整追踪。

## 4. 非目标

- 不重做多人房间或观众同步。
- 不在第一期生成 AI 解说或阶段摘要。
- 不改变狼人杀规则、胜利条件或模型 prompt 语义。
- 不把前端导播队列作为权威状态；权威状态仍来自原始 SSE 事件。
- 不移除当前原始事件列表和 DebugPanel 能力。

## 5. 总体体验

直播页变成一个“导播播放台”：

- 左侧保持玩家列表、角色、存活状态、自动跟随。
- 中间主画面展示当前导播事件，包含标题、事件类型、回合阶段、玩家、正文和播放状态。
- 中间底部增加播放控制：暂停/继续、追到最新、倍速、自动追进度提示。
- 右侧保留原始事件列表，真实事件仍实时追加，并高亮当前正在播放的事件。
- 顶部状态条展示运行状态、连接状态、当前规则、演示慢速模式、队列积压数量。

用户看到的是有节奏的观赛画面；调试者仍能在右侧看到真实事件是否已经抵达。

## 6. 前端数据流

现有 `useGameRunEvents(runId)` 继续负责连接 SSE、去重和维护完整事件数组。新增一个导播模块，建议命名为：

```text
apps/web/src/features/games/liveDirector.ts
apps/web/src/features/games/hooks/useLiveDirector.ts
apps/web/src/features/games/components/LiveDirectorStage.tsx
apps/web/src/features/games/components/LiveDirectorControls.tsx
```

数据流：

```text
SSE -> useGameRunEvents -> events[]
events[] -> useLiveDirector -> DirectorCue 队列 -> 当前播放 cue
events[] -> deriveLiveSpectatorState -> 玩家状态和存活状态
events[] -> LiveEventTimeline -> 原始事件列表
```

`deriveLiveSpectatorState()` 仍使用完整事件数组计算当前局势；导播队列只控制中间主画面“展示哪一条、展示多久”。

## 7. DirectorCue 模型

`DirectorCue` 是面向观看的事件卡片：

```ts
type DirectorCue = {
  eventId: number;
  type: string;
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  title: string;
  body: string;
  importance: "normal" | "action" | "key" | "terminal";
  durationMs: number;
  compressible: boolean;
};
```

转换规则集中放在纯函数中，便于测试：

```ts
function toDirectorCue(event: LiveGameEvent): DirectorCue
```

主画面播放所有事件，因此每个已知或未知事件都必须能转换成 cue。未知事件使用事件类型作为标题，payload 中可读字段作为正文；不能解析正文时也展示标题和基础元信息。

## 8. 播放节奏

默认采用“观赛节奏”：

- `run_created`、`run_started`、`phase_started`: 约 2 秒。
- `action_requested`、`model_request_started`: 约 2-3 秒。
- `action_parsed`: 约 3-4 秒。
- `model_response_received`: 约 6-10 秒，按正文长度适当延长。
- 发言、总结、投票、死亡、放逐等 `state_updated`: 约 5-8 秒。
- `game_completed`、`game_failed`: 至少 8 秒。

停留时长由基础时长和文本长度共同决定，并设置上下限，避免特别长的 raw response 卡住太久。

## 9. 积压与追进度策略

导播模块维护两个进度：

- `receivedEventId`: 最新收到的真实事件 id。
- `displayedEventId`: 当前或最近播放过的导播事件 id。

当 `receivedEventId - displayedEventId` 超过阈值时进入自动追进度状态：

- 普通事件停留时间压缩到最短，例如 500-800ms。
- `model_request_started` 等过程事件可以快速闪过，但仍会出现。
- `model_response_received`、发言、投票、出局、胜负等关键事件保持完整停留。
- 如果积压持续扩大，允许跳过可压缩事件的正文展示，只显示标题和元信息。
- 用户点击“追到最新”时，跳过可压缩事件，停在最近关键事件或最新事件。

这保证所有事件都有展示痕迹，同时避免对局已经结束但前端还在缓慢播放大量普通事件。

## 10. 用户控制

第一期控制项：

- 暂停/继续：暂停只影响导播播放，不停止 SSE 接收。
- 追到最新：快速推进到最近关键事件或最新事件。
- 倍速：`1x` 和 `1.5x` 即可，第一期不做复杂速度条。
- 自动追进度：默认开启，可在队列积压时自动压缩普通事件。

当用户暂停时，右侧原始事件列表仍继续增长，顶部提示“已暂停，队列新增 N 条”。恢复播放后按队列策略继续推进。

## 11. 后端演示慢速模式

创建对局表单增加“演示慢速”选择，默认关闭。一期提供三档：

- `off`: 关闭，默认快速执行。
- `standard`: 标准演示，关键事件之间约 1-2 秒。
- `slow`: 慢速讲解，关键事件之间约 3-5 秒。

后端 API 增加字段：

```json
{
  "event_pacing": "standard"
}
```

运行状态和直播页状态条返回并展示当前模式。后端只在事件发布或阶段推进处加入可配置 delay，不改变规则逻辑、模型参数或日志结构。演示慢速失败时不应影响默认模式。

## 12. API 与兼容性

`POST /api/v1/games/runs` 新增可选字段 `event_pacing`。未传时等同 `off`，保持现有调用兼容。

`GET /api/v1/games/runs/{run_id}` 和 run 创建响应增加：

```json
{
  "event_pacing": "off"
}
```

实时事件结构不需要为导播队列新增字段。前端从现有 `type`、`round`、`phase`、`actor`、`action`、`payload` 中派生展示 cue。这样可以先解决观看节奏，不把后端和 UI 绑得太紧。

## 13. 错误处理

- SSE 断开时，导播继续播放已收到队列，状态条显示连接异常。
- 重新连接后按事件 id 去重，并把补发事件加入队列。
- 事件 payload 异常时，cue 降级为标题和元信息，不让主画面崩溃。
- 后端 `event_pacing` 非法时返回 422 或 400。
- 演示慢速 delay 被中断时，对局应进入失败处理或继续使用默认事件发布，不产生半写日志。

## 14. 测试策略

后端：

- API 接收 `event_pacing`，默认值为 `off`。
- 非法 `event_pacing` 被拒绝。
- 标准演示和慢速讲解会调用 delay 策略；测试中使用可注入 sleeper，避免真实等待。
- 默认模式不引入额外等待。

前端：

- `toDirectorCue()` 覆盖所有现有事件类型和未知事件。
- `useLiveDirector()` 覆盖顺序播放、暂停、继续、追到最新、积压压缩、去重。
- `LiveGamePage` 展示导播主画面、控制条、队列数量和当前播放事件高亮。
- 回归测试确保原始事件列表仍能显示完整事件。

## 15. 分阶段实施建议

第一批：

- 前端实现 `DirectorCue` 转换、导播 hook、主画面组件和控制条。
- `LiveGamePage` 接入导播层，右侧原始事件列表保留。
- 覆盖前端单元测试。

第二批：

- 后端增加 `event_pacing` 请求字段、运行记录字段和可注入 delay 策略。
- 创建对局表单增加演示慢速选择。
- 状态条展示当前慢速模式。

第三批：

- 完成端到端验证：默认快跑、演示慢速、暂停恢复、追到最新、断线重连。
- 根据实际观感微调事件时长和积压阈值。
