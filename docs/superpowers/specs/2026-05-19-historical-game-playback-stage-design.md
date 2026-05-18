# 历史对局播放台回放设计

**日期**: 2026-05-19
**状态**: 已确认设计，待实现计划
**范围**: 为历史对局新增“放到播放台播放”能力。完整局、partial 局和失败局都可以播放已有历史片段；partial/失败局的“继续对局”逻辑保持不变，仍复用现有 resume 流程。

## 背景

当前系统已有三类相关能力：

- 历史列表：`/games/history` 展示历史 session，支持刷新、打开复盘详情，以及对 resumable 对局执行“继续对局”。
- 静态复盘：`/games/:sessionId` 读取 `GET /api/v1/games/{session_id}`，以工作台形式展示 `state + logs`，适合调试 prompt、raw response 和解析结果。
- 实时播放台：`/games/live/:runId` 通过 SSE 获取 `LiveGameEvent[]`，再交给 `useLiveDirector`、`LiveDirectorStage`、上帝视角面板和事件时间线做导播播放。

新增需求不是重新跑历史对局，也不是替代静态复盘，而是把已有历史对局转换成播放台可以消费的事件序列，让用户能像看直播一样回看一局历史对局。

## 目标

- 在历史列表和复盘详情中提供“播放”入口。
- 新增历史播放台路由，让历史对局按直播播放台体验从头播放。
- 复用现有播放台核心组件和导播节奏，不另建一套视觉播放器。
- 完整局播放到胜负结算。
- partial/失败局播放到已有日志末尾，并明确显示“对局未完成/已中断”。
- partial/失败局继续保留现有“继续对局”入口和 resume 行为，逻辑不变。
- 播放历史时不触发模型请求，不修改历史日志，不创建真实 live run。

## 非目标

- 不改变狼人杀规则、模型调用、行动解析或胜负判定。
- 不把播放台回放作为恢复对局的替代路径。
- 不在第一版实现任意时间轴拖拽、倍速滑杆、剪辑导出或 AI 解说。
- 不要求旧历史局与真实直播逐 token 完全一致。旧历史局可以由 `state + logs` 合成播放事件。
- 不删除现有 `/games/:sessionId` 调试复盘工作台。

## 推荐方案

采用“后端标准化回放事件 + 前端复用播放台”的方案。

后端新增只读 playback API，把 `ReplayStore` 读出的历史 `state + logs` 转换成稳定的 `LiveGameEvent` 形状。前端新增 `/games/playback/:sessionId` 页面，从该 API 获取事件数组，然后复用直播页已经存在的导播、上帝视角和时间线组件。

数据流：

```text
game_complete/game_partial + game_logs
-> ReplayStore.load_session(session_id)
-> ReplayPlaybackEventBuilder
-> GET /api/v1/games/{session_id}/playback
-> GamePlaybackPage
-> LiveStageExperience
-> useLiveDirector(events)
-> LiveDirectorStage + GodView panels + LiveEventTimeline
```

这个方案的核心收益是把“播放台需要什么事件”作为稳定契约，避免在前端页面里散落历史日志解析逻辑。后续如果真实直播事件持久化为 `live_events.json`，同一个 playback API 也可以优先返回原始事件，实现更精确回放。

## 后端设计

新增模块：

```text
apps/api/app/werewolf/replay_playback.py
```

建议职责：

- 接收 `session_id` 和 `ReplayStore.load_session()` 的结果。
- 生成 `LiveEvent` 等价字典，不注册到 `LiveRunRegistry`。
- 为每条事件分配稳定递增 `id`。
- 为所有合成事件设置 `run_id`，例如 `playback_{session_id}`。
- 复用历史 session 的 `session_id`。
- `created_at` 使用确定性的合成时间：以历史 session 的 `created_at` 为基准，每条事件按 `id - 1` 秒递增；如果历史创建时间缺失，则使用 `1970-01-01T00:00:00Z` 作为基准。前端播放顺序仍以 `id` 为准。

新增 API：

```text
GET /api/v1/games/{session_id}/playback
```

返回：

```json
{
  "session_id": "game_1234abcd",
  "status": "complete",
  "rule_set": {},
  "resumable": false,
  "events": []
}
```

`events` 内元素保持现有 `LiveGameEvent` 类型字段：

```json
{
  "id": 1,
  "type": "game_started",
  "run_id": "playback_game_1234abcd",
  "session_id": "game_1234abcd",
  "created_at": "2026-05-19T00:00:00Z",
  "round": null,
  "phase": null,
  "actor": null,
  "action": null,
  "payload": {}
}
```

### 事件生成顺序

第一版按“可观看、可解释、与现有播放台兼容”优先，不追求模拟每个真实 SSE 细节。

基础事件：

1. `run_created`: 标记这是历史播放台回放，payload 带 `playback: true`、`session_id`、`rule_set`、`resumable`。
2. `run_started`: 标记回放开始。
3. `game_started`: payload 带完整玩家列表、规则集和基础对局信息。

每轮事件：

1. `round_started`
2. `phase_started`，夜晚阶段
3. 夜晚行动类事件，来自 `RawRoundLog`：狼人击杀、守卫保护、预言家查验、女巫、猎人等
4. 夜晚 `state_updated`，来自 `RawRoundState` 的夜晚结果、存活玩家、死亡信息
5. `phase_started`，警长/白天/发言/投票等阶段
6. 白天行动类事件，来自 `RawRoundLog`：上警、警上发言、退水、警徽投票、发言顺序、白天发言、自爆、放逐投票、警徽移交等
7. 白天 `state_updated`，来自 `RawRoundState` 的发言、投票、出局、警长状态和存活玩家
8. summary 行动和 `state_updated`

终局事件：

- complete 局生成 `game_completed`，payload 带 `winner`。
- partial/失败局生成 `game_failed`，payload 带简短 `error` 和 `playback_partial: true`。

### 行动事件映射

历史日志中的 `RawActionLog` 可以映射为一组压缩事件：

```text
action_requested
model_response_received
action_parsed
```

第一版不必从历史日志伪造 `model_response_delta` 流式 token。对公开发言、总结、可展示文本，优先把文本放进 `model_response_received.payload.visible_text` 或 `action_parsed.payload.visible_result`，让现有 `liveDirector` 生成可读 cue。

行动字段映射：

- `actor`: `RawActionLog.actor`
- `action`: `RawActionLog.action`
- `payload.options`: `RawActionLog.options`
- `payload.choice`: `RawActionLog.choice`
- `payload.result`: `RawActionLog.lm_log.result`
- `payload.visible_result`: 从 result 中提取 `say`、`summary`、目标选择等公开信息
- `payload.prompt` 和 `payload.raw_response`: 默认不进入播放台主 cue；调试仍由静态复盘工作台承载

## 前端设计

新增 API 文件：

```text
apps/web/src/features/games/api/getGamePlayback.ts
```

新增类型：

```ts
export type GamePlayback = {
  session_id: string;
  status: GameStatus;
  rule_set?: RuleSetSummary | null;
  resumable?: boolean;
  events: LiveGameEvent[];
};
```

新增页面：

```text
apps/web/src/pages/GamePlaybackPage.tsx
```

新增路由：

```text
/games/playback/:sessionId
```

### 播放台复用

把 `LiveGamePage` 中与播放来源无关的 UI 抽成共享组件，例如：

```text
apps/web/src/features/games/components/LiveStageExperience.tsx
```

它接收：

```ts
type LiveStageExperienceProps = {
  events: LiveGameEvent[];
  connectionState: ConnectionState;
  run: {
    run_id: string;
    session_id: string;
    status: "queued" | "running" | "completed" | "failed";
    rule_set?: RuleSetSummary | null;
    winner?: string | null;
    error?: string | null;
  };
  mode: "live" | "playback";
  canResume?: boolean;
  onResume?: () => void;
};
```

`LiveGamePage` 继续负责：

- 读取 `runId`
- `getGameRun(runId)`
- `useGameRunEvents(runId)`
- resume 失败局

`GamePlaybackPage` 负责：

- 读取 `sessionId`
- `getGamePlayback(sessionId)`
- 将 `connectionState` 固定为 `closed`
- 将 `mode` 设为 `playback`
- 对 resumable partial/失败局展示“继续对局”入口，点击后仍调用现有 `resumeGameRun(sessionId)` 并跳转到 `/games/live/:runId`

### 页面入口

历史列表 `SessionList` 增加“播放”入口：

```text
查看复盘 | 播放 | 继续对局
```

复盘详情页顶部增加“放到播放台”入口：

```text
放到播放台
```

建议保持语义清晰：

- “查看复盘”：进入 `/games/:sessionId`
- “播放”：进入 `/games/playback/:sessionId`
- “继续对局”：只对 resumable 对局显示，继续进入现有 live run

## partial/失败局规则

partial/失败局的恢复逻辑保持不变：

- 历史页的“继续对局”仍调用 `POST /api/v1/games/{session_id}/resume`。
- 播放台回放不会自动恢复对局。
- 播放台回放不会创建真实 run，也不会调用模型。
- 播放台回放到已有事件末尾后显示中断状态。
- 如果该 session `resumable: true`，播放台设置菜单或顶部操作区可以展示“继续对局”按钮。
- 继续成功后跳转到 `/games/live/:runId`，进入真实实时播放台。

这保证三条用户路径不会混淆：

```text
查看复盘 = 调试和分析历史日志
放到播放台 = 像直播一样播放已有历史
继续对局 = 从 checkpoint 恢复真实对局
```

## 状态与错误处理

后端：

- session id 继续使用 `SESSION_ID_RE` 校验。
- 找不到历史对局时返回 404。
- 历史日志损坏时返回 404 或 422，避免泄露本地路径和完整异常。
- playback 生成器对缺失字段采用空数组、空字符串或 null 回退。

前端：

- loading：显示“正在准备历史播放台...”
- error：显示“无法读取历史回放”
- empty events：显示“该对局没有可播放事件”
- complete：播放到胜负结算
- partial/failed：播放到中断 cue，并展示继续入口

## 测试策略

后端测试：

- `GET /api/v1/games/{session_id}/playback` 对完整局返回 `game_started`、轮次事件和 `game_completed`。
- partial/失败局返回已有事件和 `game_failed`，且 `resumable` 与历史 summary 一致。
- playback 生成不调用模型、不创建 live registry run。
- malformed session 或不存在 session 返回预期错误。
- 事件 ID 稳定递增。

前端测试：

- `/games/history` 每条历史局展示“播放”入口。
- 点击或路由到 `/games/playback/:sessionId` 后渲染播放台。
- 完整局展示胜负结算 cue。
- partial/失败局展示中断状态，并保留“继续对局”入口。
- “继续对局”调用现有 `resumeGameRun`，成功后导航到 `/games/live/:runId`。
- `LiveStageExperience` 能同时支持 live 和 playback 两种来源。

建议验证命令：

```bash
pytest apps/api/tests/test_games_api.py
pnpm --dir apps/web test -- --run src/pages/GameHistoryPage.test.tsx src/pages/GameDetailPage.test.tsx src/pages/LiveGamePage.test.tsx
pnpm --dir apps/web build
```

实现时如果新增专门测试文件，再把对应测试加入命令。

## 分阶段实施

第一阶段：事件契约和 API。

- 新增 playback 响应类型和后端生成器。
- 新增 `GET /api/v1/games/{session_id}/playback`。
- 覆盖完整局、partial 局和错误路径。

第二阶段：前端页面和复用抽取。

- 抽出 `LiveStageExperience`。
- 新增 `GamePlaybackPage` 和路由。
- 新增 `getGamePlayback`。
- 历史列表和复盘详情增加播放入口。

第三阶段：回放体验打磨。

- partial/失败局中断 cue 文案打磨。
- 播放台设置区显示“历史回放”模式和继续入口。
- 视觉回归，确保移动端和桌面端布局不重叠。

第四阶段：未来增强。

- 真实直播事件持久化到历史目录，例如 `live_events.json`。
- playback API 优先返回持久化真实事件，缺失时再合成。
- 在播放台增加章节跳转或关键事件索引。

## 验收标准

- 用户能从历史列表把完整历史对局放到播放台播放。
- 用户能从复盘详情把当前对局放到播放台播放。
- 播放台中玩家、发言、投票、死亡、胜负与静态复盘一致。
- partial/失败局可以播放已有片段，并明确停在中断状态。
- partial/失败局的“继续对局”行为与现有逻辑一致。
- 历史播放不会发起模型请求，不会修改历史日志，不会创建真实 live run。
- 现有实时直播页和静态复盘页行为不回退。

## 自查

- 设计明确区分了查看复盘、播放台回放和继续对局三条路径。
- partial/失败局没有被播放台回放吞掉继续对局能力。
- 后端承担日志到标准事件的适配，前端避免散落历史日志解析。
- 第一版范围聚焦，没有加入拖拽时间轴、导出和逐 token 伪流式等非必要功能。
- 未来可平滑升级到持久化真实直播事件。
