# 前端导播播放速度统一设计

**日期**: 2026-05-18
**状态**: 新基准设计。替代 `2026-04-26-live-director-pacing-design.md` 和 `2026-04-26-live-director-pacing.md` 中关于后端演示慢速、`event_pacing` 三档延迟、创建对局页“演示慢速”控件的设计。

## 背景

实时观战页已经引入前端导播队列，用 `DirectorCue` 把 SSE 原始事件转换成适合观看的播放片段。旧设计同时引入了后端 `event_pacing`，让后端按 `off | standard | slow` 在事件发布前 sleep。

新的产品方向是：后端不再承担演示节奏控制。对局执行、模型请求、规则推进和事件发布都按正常速度完成；观众看到的节奏完全由前端导播层控制。这样可以让后端保持可预测、可测试、可复盘，避免为了演示而拖慢真实对局。

## 目标

- 后端一律正常速度执行，不区分标准演示、慢速讲解或其他执行速度。
- 创建对局页不再提供“演示慢速”选择，也不向后端提交节奏配置。
- 直播页保留导播队列，由前端决定每条 cue 展示多久。
- 默认 `1x` 以常人发言正常语速为基准，重点解决发言、模型公开文本、投票和胜负结果可读性。
- 播放速度只提供 `1x` 和 `2x` 两档。
- 调试用原始事件列表继续实时展示真实 SSE 到达顺序，不被导播播放速度影响。

## 非目标

- 不改变狼人杀规则、模型 prompt、行动解析或胜负判定。
- 不让后端根据 UI 播放速度暂停、等待或跳过事件。
- 不做复杂速度滑杆、自动语音朗读或 AI 解说。
- 不把前端导播队列作为权威状态；权威状态仍来自完整事件流。

## 推荐方案

采用“后端去节奏化 + 前端语速基准化”的方案。

后端移除实际等待逻辑：`EventPacer`、`SUPPORTED_EVENT_PACING`、`standard/slow` 延迟表和后台运行路径中的 `pacer.wait()` 都不再参与对局执行。创建 run 时不需要 `event_pacing`。如果需要兼容旧客户端，可以在一个过渡版本中接受但忽略旧字段，并明确不再把它作为执行策略；本项目内置前端应直接停止发送该字段。

前端保留导播队列，所有观看节奏在 `liveDirector.ts` 和 `useLiveDirector.ts` 内完成。每个 `DirectorCue.durationMs` 表示 `1x` 下的展示时长；播放速度为 `2x` 时，hook 将展示时长除以 2，并保留最短展示时长，避免 UI 闪烁。

## 数据流

```text
后端正常执行 -> SSE 原始事件 -> useGameRunEvents(events[])
events[] -> buildDirectorCues() -> DirectorCue(durationMs = 1x)
useLiveDirector(speed: 1 | 2) -> currentCue + effectiveDurationMs
LiveDirectorStage 展示 currentCue
LiveEventTimeline 展示真实原始事件列表
```

关键边界：

- 后端只负责产生事实事件。
- 前端导播只负责观看节奏。
- 播放速度只影响 `effectiveDurationMs`，不影响 SSE 连接、事件去重、复盘数据或后端状态。

## 1x 语速基准

`1x` 应接近真人正常发言，而不是简单固定秒数。建议把 cue 时长拆成两部分：

1. 事件基础停留：用于标题、阶段变化、行动请求等短信息。
2. 文本阅读/发言时长：用于公开发言、模型可见文本、总结、投票说明等长文本。

建议基准：

- 中文公开文本按约 `3.5-4` 个汉字/秒估算。
- 英文或混合文本按约 `140-170` words/min 估算。
- 每条长文本增加 `800-1200ms` 起始停顿，给观众完成视线定位。
- 单条 cue 仍设置上下限，避免短文本一闪而过或超长 raw response 卡住播放。

建议初始参数：

```text
NORMAL_CHARS_PER_SECOND = 4
NORMAL_WORDS_PER_MINUTE = 150
LONG_TEXT_LEAD_IN_MS = 1000
MIN_CUE_DURATION_MS = 800
MAX_TEXT_CUE_DURATION_MS = 20000
```

示例：

- 20 个中文字符：约 `1000 + 20 / 4 * 1000 = 6000ms`。
- 60 个中文字符：约 `16000ms`。
- 120 个中文字符：超过上限时压到 `20000ms`。
- `2x` 下同一条 cue 的有效时长约减半，但不低于最短展示时长。

## 事件时长建议

`durationMs` 存储 `1x` 时长：

- `run_created`、`run_started`：`1500-2000ms`。
- `game_started`：`4000-6000ms`，足够看清玩家阵容。
- `round_started`、`phase_started`：`2000-3000ms`。
- `action_requested`、`model_request_started`：`2000-3000ms`，可压缩。
- `model_response_delta` 合并后的公开发言：按 1x 语速估算，不可压缩。
- `model_response_received` 若只有“已接收/正在解析”提示：`2000-2500ms`，可压缩。
- `action_parsed`：`3000-4000ms`，可压缩；如果包含公开发言文本，则按语速估算。
- `state_updated` 中的发言、投票、出局、平安夜、回合总结：按内容长度或 `6000ms` 起步，不可压缩。
- `game_completed`、`game_failed`：`8000ms` 起步，不可压缩。

积压时仍可以压缩可压缩 cue；不可压缩 cue 使用语速基准，保证关键内容可读。

## UI 调整

大厅创建页：

- 移除“演示慢速”字段。
- 提交 payload 不再包含 `event_pacing`。
- 横向控制台只保留规则、随机种子、最大轮数、玩家配置和发起对局相关控制。

直播页：

- 控制条的“播放速度”保留，但选项改为 `1x` 和 `2x`。
- 默认速度为 `1x`。
- 重置 run 或切换 run 后速度回到 `1x`。
- 状态条不再展示“快速执行/标准演示/慢速讲解”，可以改为展示连接状态、运行状态、队列积压和当前播放速度。

文案建议：

- `1x`：正常语速。
- `2x`：快速浏览。

## API 与兼容性

目标 API 不再需要 `event_pacing`：

- `POST /api/v1/games/runs` 不再要求或使用 `event_pacing`。
- `GameRun` summary 不再需要展示 `event_pacing`。
- `run_created` payload 不再把 `event_pacing` 作为对局属性。

如果担心历史前端或外部调用仍发送该字段，第一步可以做兼容处理：

- 后端请求 schema 临时允许未知/旧字段，但忽略 `event_pacing`。
- 不再验证 `off | standard | slow`。
- 不再基于该字段 sleep。
- 前端和文档立即停止发送、展示该字段。

完成迁移后，再删除兼容入口和旧类型。

## 测试策略

后端：

- 覆盖创建 run 时不需要 `event_pacing`。
- 覆盖即使旧请求带 `event_pacing`，也不会触发 sleep 或改变执行路径。
- 删除或改写 `test_werewolf_pacing.py` 中标准/慢速延迟相关断言。
- 覆盖 run summary 和 `run_created` payload 不再依赖节奏模式。

前端：

- `CreateGameRunForm` 测试确认没有“演示慢速”控件，提交 payload 不含 `event_pacing`。
- 类型测试或 API 测试确认 `CreateGameRunRequest` 不再暴露 `event_pacing`。
- `LiveDirectorControls` 测试确认只有 `1x` 和 `2x` 两档。
- `useLiveDirector` 测试确认默认 `1x`，`2x` 将 cue 有效时长减半，并保留最短时长。
- `liveDirector` 测试覆盖长文本按正常语速生成 `1x` duration。
- `LiveStatusStrip` 测试确认不再显示“快速执行/标准演示/慢速讲解”。

验证命令建议：

```bash
pytest apps/api/tests/test_live.py apps/api/tests/test_games_api.py
pnpm --dir apps/web test -- --run src/features/games/liveDirector.test.ts src/features/games/hooks/useLiveDirector.test.tsx src/features/games/components/LiveDirectorControls.test.tsx src/pages/GamesPage.test.tsx src/pages/LiveGamePage.test.tsx
pnpm --dir apps/web build
```

## 分阶段开发思路

第一阶段：前端体验先对齐。

- 把播放速度类型从 `1 | 1.5` 调整为 `1 | 2`。
- 把长文本 cue 的 `durationMs` 调整为 1x 正常语速基准。
- 移除大厅页“演示慢速”控件和提交字段。
- 移除直播状态条里的后端节奏标签。

第二阶段：后端去节奏化。

- 删除或废弃 `EventPacer` 和延迟表。
- 移除后台执行路径中的 `pacer.wait()`。
- 从 run 创建、summary、事件 payload 中清理 `event_pacing`，或先兼容忽略再删除。
- 更新 API 测试，保证没有 sleep 路径。

第三阶段：文档和回归验证。

- 清理旧文档中把 `event_pacing` 当作目标能力的描述。
- 跑前后端测试和 web build。
- 本地打开直播页，验证真实事件快速到达时前端仍按 `1x/2x` 导播节奏播放。

## 验收标准

- 后端执行速度不受任何 UI 或请求字段影响。
- 用户无法在创建对局时选择后端演示慢速。
- 直播页播放速度只有 `1x` 和 `2x`。
- `1x` 下长文本播放时长接近正常发言语速，观众能读完整段公开发言。
- `2x` 下导播播放明显加快，但关键 cue 不会低于最短展示时长。
- 原始事件列表仍按真实事件到达顺序实时增长。

## 自查

- 没有保留“后端标准演示/慢速讲解”的执行策略。
- 明确了 `1x` 的语速算法，而不是只改 UI 文案。
- 明确区分后端真实执行速度、SSE 到达速度和前端导播播放速度。
- 覆盖了移除旧字段、前端两档速度、测试和兼容策略。
