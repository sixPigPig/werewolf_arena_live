# 狼人杀对局复盘工作台前端设计方案

**日期**: 2026-04-24
**范围**: 规划前端第一阶段开发。实现时会修改 `apps/web`，并需要后端提供只读日志 API；本设计不包含实时房间、在线玩家操作或自动发起真实模型对局。

## 1. 背景

参考项目的 `index.html` 和 `index.ts` 是一个静态日志查看器。它最有价值的部分不是页面样式，而是复盘交互：

- 按轮次展示夜晚、白天、竞价、发言、投票、总结。
- 点击任意游戏事件，在右侧查看 prompt、raw response、parsed result。
- 同时展示玩家列表、角色、模型和胜负结果。

当前项目已有 React + Vite + React Router + TanStack Query 骨架，但前端仍是健康检查页面。后端已能通过 CLI 生成中文狼人杀日志，因此前端第一阶段应优先做“对局复盘工作台”，让已有日志可被检查、分析和调试。

## 2. 目标

第一阶段目标是让用户可以在浏览器中查看已完成或失败的狼人杀对局：

- 查看历史 session 列表。
- 打开某个 session 的复盘页面。
- 查看玩家、角色、模型、胜利阵营和每轮关键事件。
- 查看夜晚行动、白天发言、投票、总结。
- 点击任意行动查看模型 prompt、raw response、解析结果。
- 支持 complete 和 partial 游戏日志。

## 3. 非目标

本阶段不做以下内容：

- 不做实时在线对局房间。
- 不做 WebSocket。
- 不做前端触发真实 DeepSeek 对局的默认入口。
- 不做登录、权限、多人协作。
- 不直接照搬参考项目的 DOM 手写代码。
- 不把日志文件路径直接暴露成前端硬编码地址。

## 4. 推荐方案

采用 React 工具型工作台方案，页面结构参考原 viewer 的三栏布局：

```text
+----------------+-------------------------------+----------------------+
| 玩家与对局信息 |          对局时间线            |       调试面板       |
| Players        | Round 1 Night / Day / Vote     | Prompt / Raw / JSON  |
+----------------+-------------------------------+----------------------+
```

推荐路由：

```text
/games
/games/:sessionId
```

`/games` 展示已有 session，`/games/:sessionId` 展示复盘工作台。首页 `/` 可以重定向到 `/games`，或显示最近一局的入口。

## 5. 后端 API 契约

前端不直接读取 `apps/api/logs/...` 文件，而通过后端只读 API 获取数据。

建议新增 API：

```text
GET /api/v1/games
GET /api/v1/games/{session_id}
```

`GET /api/v1/games` 返回：

```json
{
  "sessions": [
    {
      "session_id": "session_20260424_050950_66ea9f38",
      "status": "complete",
      "winner": "狼人阵营",
      "round_count": 3,
      "created_at": "2026-04-24T05:09:50Z"
    }
  ]
}
```

`GET /api/v1/games/{session_id}` 返回聚合后的复盘数据：

```json
{
  "session_id": "session_20260424_050950_66ea9f38",
  "status": "complete",
  "state": {},
  "logs": []
}
```

后端可以继续保留原始 `game_complete.json`、`game_partial.json`、`game_logs.json`，但 API 层应屏蔽文件细节。

## 6. 前端数据模型

前端需要定义一层稳定类型，而不是直接把后端 JSON 传进所有组件。

核心类型：

- `GameSessionSummary`: session 列表项。
- `GameReplay`: 单局聚合数据。
- `Player`: 玩家姓名、角色、模型、观察信息。
- `Round`: 每轮状态，包括夜晚、白天、投票、总结。
- `ActionLog`: 单个模型调用事件，包括 actor、action、choice、prompt、raw response、parsed result。
- `SelectedDebugItem`: 右侧调试面板当前选中项。

如果后端日志格式未来调整，优先在 `api/adapter` 中适配，避免 UI 组件感知原始日志细节。

## 7. 页面与组件

建议文件结构：

```text
apps/web/src/features/games
  /api
    getGameDetail.ts
    listGames.ts
  /components
    ActionCard.tsx
    BidChart.tsx
    DebugPanel.tsx
    DayPhase.tsx
    GameLayout.tsx
    NightPhase.tsx
    PlayerPanel.tsx
    RoundTimeline.tsx
    SessionList.tsx
    SummaryStrip.tsx
    VoteTable.tsx
  types.ts

apps/web/src/pages
  GamesPage.tsx
  GameDetailPage.tsx
```

组件职责：

- `GamesPage`: 加载并展示 session 列表。
- `GameDetailPage`: 加载单局复盘数据，管理当前选中的 debug item。
- `GameLayout`: 三栏布局。
- `PlayerPanel`: 玩家、角色、模型、胜利阵营、轮次数。
- `RoundTimeline`: 按轮渲染所有阶段。
- `NightPhase`: 狼人、预言家、医生行动和夜晚结果。
- `DayPhase`: 竞价、发言、投票、总结。
- `BidChart`: 用柱状或紧凑条形展示发言意愿。
- `VoteTable`: 展示谁投给谁。
- `DebugPanel`: 展示 prompt、raw response、parsed result。

## 8. 交互设计

复盘页面的核心交互：

- 点击行动卡片，右侧固定调试面板更新。
- 当前选中行动在时间线中高亮。
- 轮次可折叠，默认展开最近或全部展开。
- 角色用颜色和标签区分：
  - 狼人：红色
  - 预言家：绿色
  - 医生：蓝色
  - 村民：中性色
- partial 对局显示错误信息和失败轮次。
- 空 session 列表显示明确空状态。

界面应是工具型、信息密集、稳定可扫描。不要做营销页、巨大 hero 或装饰性卡片堆叠。

## 9. 状态与错误处理

使用 TanStack Query 处理服务端状态：

- session 列表：`queryKey: ["games"]`
- 单局详情：`queryKey: ["games", sessionId]`

需要覆盖状态：

- loading
- error
- empty sessions
- game not found
- partial game
- malformed log fallback

错误文案应简短，不暴露密钥或完整内部异常。

## 10. 测试策略

优先测试行为而非样式：

- `GamesPage` 加载 session 列表。
- `GameDetailPage` 展示玩家、胜利阵营和轮次。
- 点击行动卡片后，`DebugPanel` 显示 prompt/raw response/result。
- partial 对局显示错误状态。
- API adapter 能把后端聚合数据转换成 UI 使用的数据结构。

验证命令：

```bash
cd apps/web && pnpm test -- --run
cd apps/web && pnpm build
```

如果实现时新增后端 API，还需要运行：

```bash
cd apps/api && .venv/bin/python -m pytest
cd apps/api && .venv/bin/ruff check .
```

## 11. 分阶段实施

建议分两步：

### 阶段一：只读复盘

- 后端只读 games API。
- 前端 session 列表。
- 前端复盘工作台。
- Debug 面板。
- 测试与构建通过。

### 阶段二：对局发起与体验优化

- 前端可选触发新对局。
- 对局运行状态轮询。
- 更细致的过滤、搜索、角色视角切换。
- 性能优化和大型日志虚拟列表。

本设计只覆盖阶段一。
