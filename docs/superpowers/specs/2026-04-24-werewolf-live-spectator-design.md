# 狼人杀实时观战阶段二设计方案

**日期**: 2026-04-24
**范围**: 规划阶段二开发，让前端可以发起本机单用户对局，并在对局运行时实时观看模型调用、解析结果和局势变化。实现时会修改 `apps/api` 和 `apps/web`。

## 1. 背景

阶段一已经实现只读复盘工作台：前端通过 `GET /api/v1/games` 和 `GET /api/v1/games/{session_id}` 查看已经落盘的完整或 partial 对局日志。

阶段二需要从“对局结束后查看”升级为“发起对局并实时观看”。用户确认当前目标是本机开发、单用户后台运行，因此不需要多人房间、任务队列、持久化调度或复杂权限系统。

## 2. 目标

- 前端可以发起一局新的狼人杀对局。
- 对局在后端后台运行，不阻塞 HTTP 请求。
- 前端可以实时看到更细粒度过程：
  - 对局开始、回合开始、阶段开始。
  - 玩家开始思考和准备模型请求。
  - 模型原文返回。
  - 模型结果被解析成行动。
  - 发言、投票、死亡、放逐、胜负等局势更新。
- 对局完成后仍写出当前阶段一兼容的日志文件，并可进入完整复盘页。
- 避免固定高频轮询造成过多请求。

## 3. 非目标

- 不做多人在线房间。
- 不做观战者聊天或控制指令。
- 不做暂停、恢复、取消、人工干预。
- 不做持久化任务队列。
- 不做跨进程运行状态恢复。服务重启后，内存运行状态可以丢失；已落盘日志仍可从复盘列表查看。
- 不把 WebSocket 作为第一版实时通道。

## 4. 推荐方案

采用 **内存运行器 + 后台线程/任务 + SSE 实时事件流**。

SSE 适合当前场景，因为实时观战主要是后端向前端单向推送事件。相比固定轮询，SSE 没有持续空请求；相比 WebSocket，SSE 的前后端实现更轻，浏览器原生支持自动重连。

保留低频状态查询作为兜底：SSE 不可用或断线过久时，前端可以每 10-15 秒查询一次运行状态。

## 5. 后端 API 契约

新增 API：

```text
POST /api/v1/games/runs
GET  /api/v1/games/runs/{run_id}
GET  /api/v1/games/runs/{run_id}/events
```

`POST /api/v1/games/runs` 请求：

```json
{
  "villager_model": "deepseek-chat",
  "werewolf_model": "deepseek-chat",
  "seed": 21,
  "max_rounds": 8
}
```

响应：

```json
{
  "run_id": "run_8f2a21b4",
  "session_id": "session_20260424_120000_ab12cd34",
  "status": "queued",
  "created_at": "2026-04-24T12:00:00Z"
}
```

`GET /api/v1/games/runs/{run_id}` 响应：

```json
{
  "run_id": "run_8f2a21b4",
  "session_id": "session_20260424_120000_ab12cd34",
  "status": "running",
  "created_at": "2026-04-24T12:00:00Z",
  "started_at": "2026-04-24T12:00:01Z",
  "completed_at": null,
  "error": null,
  "event_count": 42
}
```

运行状态枚举：

```text
queued | running | completed | failed
```

`GET /api/v1/games/runs/{run_id}/events` 使用 `text/event-stream`。每条事件包含递增 id，便于前端去重和断线后恢复。

## 6. 实时事件契约

事件基础结构：

```json
{
  "id": 17,
  "type": "action_parsed",
  "run_id": "run_8f2a21b4",
  "session_id": "session_20260424_120000_ab12cd34",
  "created_at": "2026-04-24T12:00:05Z",
  "round": 1,
  "phase": "day",
  "actor": "张三",
  "action": "debate",
  "payload": {}
}
```

事件类型：

```text
game_started
round_started
phase_started
action_requested
model_request_started
model_response_received
action_parsed
state_updated
game_completed
game_failed
heartbeat
```

事件语义：

- `game_started`: 玩家、角色、模型、session 初始化完成。
- `round_started`: 新回合进入 active 状态。
- `phase_started`: `night`、`day`、`vote`、`summary` 阶段开始。
- `action_requested`: 某玩家准备执行行动，前端可显示“正在思考”。
- `model_request_started`: 模型请求即将发出，可带 prompt 摘要或完整 prompt。
- `model_response_received`: 模型返回原文，可更新 DebugPanel。
- `action_parsed`: raw response 已解析为结构化结果，例如 `vote`、`remove`、`protect`、`say`。
- `state_updated`: GameState 产生用户可见变化，例如发言追加、投票记录、玩家出局、胜利阵营更新。
- `game_completed`: 对局成功结束，日志已落盘或即将可读取。
- `game_failed`: 对局失败，partial 日志已落盘或即将可读取。
- `heartbeat`: 长时间无业务事件时保持连接活跃。

前端应按事件 `id` 去重。SSE 重连后，如果浏览器提供 `Last-Event-ID`，后端应尽量补发该 id 之后仍在内存中的事件。

## 7. 后端结构

新增本机内存运行器模块，建议放在：

```text
apps/api/app/werewolf/live.py
```

核心对象：

- `LiveGameRun`: 保存 `run_id`、`session_id`、状态、时间戳、错误、事件列表。
- `LiveEvent`: 标准化实时事件。
- `LiveRunRegistry`: 管理当前进程内的运行记录和订阅者。
- `EventSink`: 引擎可调用的事件出口。

`GameEngine` 增加可选 `event_sink` 参数，默认使用空实现，保证现有 CLI、复盘 API 和测试不受影响。

模型动作生命周期集中在 `_player_action()`，因此这里是最重要的事件注入点：

1. `action_requested`
2. `model_request_started`
3. 调用 `generate_action`
4. `model_response_received`
5. `action_parsed`

回合、阶段、状态变化事件分别在 `run()`、`_run_night_phase()`、`_run_day_phase()`、`_run_voting()`、`_run_summaries()` 中发布。

最终仍调用 `save_game()`，保持 `game_complete.json`、`game_partial.json`、`game_logs.json` 格式兼容阶段一复盘。

## 8. 前端结构

新增页面：

```text
/games/live/:runId
```

建议文件：

```text
apps/web/src/features/games/api/createGameRun.ts
apps/web/src/features/games/api/getGameRun.ts
apps/web/src/features/games/hooks/useGameRunEvents.ts
apps/web/src/pages/LiveGamePage.tsx
apps/web/src/features/games/components/CreateGameRunForm.tsx
apps/web/src/features/games/components/LiveEventTimeline.tsx
apps/web/src/features/games/components/LiveStatusStrip.tsx
```

`/games` 页面增加发起入口。提交后创建 run，并跳转到 `/games/live/:runId`。

实时页面沿用复盘工作台的信息架构：

- 左侧：玩家状态、角色、模型、存活/出局。
- 中间：实时事件时间线。
- 右侧：DebugPanel，点击模型相关事件查看 prompt、raw response、parsed result。

完成后：

- 显示 completed 状态。
- 提供进入 `/games/:sessionId` 的复盘入口。
- 让 TanStack Query 失效 `["games"]`，刷新对局列表。

## 9. 错误与断线处理

- 创建对局失败：表单展示简短错误。
- SSE 连接断开：显示“正在重连”，让浏览器自动重连。
- 重连后事件重复：按 `id` 去重。
- 长时间无法恢复 SSE：启用低频 `GET /runs/{run_id}` 兜底状态查询。
- 对局失败：展示 `game_failed` 事件和 partial 复盘入口。
- 页面刷新：通过 `GET /runs/{run_id}` 获取当前状态，再订阅 SSE；如果运行记录已丢失但 session 已落盘，引导用户回 `/games` 查找。

## 10. 测试策略

后端：

- 创建 run 返回 `queued/running` 状态。
- SSE 能收到 `game_started`、至少一个 action 生命周期事件、终态事件。
- `EventSink` 默认空实现不影响现有 `run_game()`。
- 失败时产生 `failed` 状态并保留错误信息。

前端：

- `/games` 可以提交创建对局表单。
- 创建成功后跳转 live 页面。
- live 页面能消费模拟 SSE 事件并追加时间线。
- `action_requested` 显示 pending 状态。
- `model_response_received` 和 `action_parsed` 能进入 DebugPanel。
- `game_completed` 显示复盘入口并刷新 games 查询。

验证命令：

```bash
cd apps/api && .venv/bin/python -m pytest
cd apps/web && pnpm test -- --run
cd apps/web && pnpm build
```

## 11. 分阶段实施

第一步：后端 live run 骨架

- 增加 run registry、事件模型、创建 run API、状态查询 API。
- 后台运行真实 `run_game`，终态可查询。

第二步：引擎事件 sink

- 给 `GameEngine` 和 `run_game()` 增加可选事件 sink。
- 发布回合、阶段、模型调用生命周期、状态更新事件。
- 保持最终日志格式不变。

第三步：SSE API

- 增加 `/events` endpoint。
- 支持事件 replay、heartbeat、终态关闭。

第四步：前端发起与实时观战

- `/games` 增加发起表单。
- 新增 live 页面和 SSE hook。
- 实时追加 timeline，复用 DebugPanel。

第五步：体验优化

- 搜索、状态过滤、角色视角切换。
- 根据真实日志量评估是否引入虚拟列表。
