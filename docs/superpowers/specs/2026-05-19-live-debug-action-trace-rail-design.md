# 观战页 Action Trace Rail 调试事件设计

## 背景

当前观战页右侧已经有“事件记录”和折叠的“调试事件”，但调试事件仍接近 raw event list。它能看到事件发生过，却不容易回答调试时最重要的问题：

- 一次玩家行动从请求到状态更新是否完整？
- 模型输出、解析结果、状态变化和舞台表现是否一致？
- 某个异常是模型没返回、解析没成功、状态没更新，还是前端没有正确展示？

本设计把调试事件重构为右侧 `Action Trace Rail`，以“行动包”为基本单位展示因果链。

## 目标

- 将单条事件列表升级为按行动聚合的追踪轨道。
- 默认视图能快速扫出每个行动包的链路健康度。
- 选中行动包后能深挖 prompt、模型原文、解析结果、payload 和状态 diff。
- 与中央舞台联动，高亮 actor、target 或被状态影响的玩家。
- 保持观战页主舞台和现有上帝视角信息结构稳定，第一版不大改布局。

## 非目标

- 不修改后端事件协议。
- 不引入新的 UI 依赖。
- 不做完整 DevTools 替代品，例如任意 JSON 查询、断点或事件重放编辑。
- 不把所有事件都强行聚合；无法归属的系统事件保留为独立系统包。
- 不改变普通观战用户的默认叙事体验，调试轨道仍属于开发/排查视图。

## 推荐方案

采用右侧 `Trace Rail` 方案：

- 右侧 `GodViewIntelPanel` 保留“事件记录 / 死亡信息 / 身份线索”等观战信息。
- 当前折叠的“调试事件”升级为 `Action Trace Rail`。
- 调试轨道默认按最新行动倒序显示。
- 每个行动包展示事件编号范围、行动摘要、链路节点、状态影响和异常提示。
- 点击行动包后，在右侧下方或同一包内展开详情，并让中央舞台高亮相关玩家。

相比底部工作台，这个方案不会挤压当前直播台；相比舞台 overlay，它更适合承载调试细节。后续可以在选中行动包时加入轻量 overlay，高亮 actor / target。

## 行动包模型

行动包是前端派生结构，不要求后端新增字段。

```ts
type LiveDebugTrace = {
  id: string;
  eventIds: number[];
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  choice: string | null;
  title: string;
  status: "ok" | "warning" | "error" | "system";
  nodes: Array<{
    kind: "request" | "model" | "parsed" | "state" | "stage" | "system";
    eventId: number;
    label: string;
    status: "ok" | "warning" | "error" | "muted";
  }>;
  impactSummary: string[];
  warnings: string[];
  prompt?: string;
  rawResponse?: string;
  parsed?: unknown;
  payloads: Array<{ eventId: number; type: string; payload: unknown }>;
  stateDiff: Array<{ label: string; before: string; after: string }>;
  relatedPlayers: string[];
};
```

第一版聚合优先级：

- `action_requested` 开启一个行动包，使用 `actor + action + round + phase` 作为主归属线索。
- 同一 actor/action 附近的 `model_request_started`、`model_response_received`、`action_parsed` 归入该包。
- 紧随其后的相关 `state_updated` 归入该包，尤其是包含 `debate_entry`、`votes`、`eliminated`、`exiled`、`attacked`、`protected`、`investigated` 等字段时。
- `phase_started`、`round_started`、`game_started`、`game_completed` 等没有明确 actor 的事件形成系统包。
- `model_response_delta` 和 `model_thinking_tick` 默认不单独展示，只作为模型节点的耗时/流式状态信息来源。

## 右侧轨道展示

每个行动包压缩态展示：

- 编号范围：例如 `#118-124`。
- 标题：例如 `Sam · 公开发言`、`狼人 · 击杀共识`。
- 状态徽标：`OK`、`需关注`、`异常`、`系统`。
- 节点条：`request / model / parsed / state / stage`。
- 一行影响摘要：例如 `active speaker = Sam；新增公开发言；舞台焦点切到 8 号`。

展开态展示：

- 触发链路：逐项列出事件编号、事件类型和中文说明。
- 状态 diff：展示关键字段变化，而不是裸 JSON。
- 模型区：`Prompt`、`Raw response`、`Parsed result`，长内容折叠或限高滚动。
- Payload 区：保留原始 JSON，作为最后兜底。
- 关联玩家：列出 actor、choice、target、死亡/放逐/被保护玩家。

## 异常提示

轨道应主动标记不一致，而不是只展示数据：

- 有 `action_requested`，但没有模型返回：`模型返回缺失`。
- 有模型返回，但没有 `action_parsed`：`解析结果缺失`。
- 有 `action_parsed.choice`，但没有相关状态变化：`选择未影响状态`。
- 有 `state_updated` 改变死亡、票型、警徽或发言状态，但舞台当前焦点没有对应变化：`舞台表现可能未同步`。
- `action_parsed` 与 `state_updated` 字段冲突：例如 choice 是 A，但状态记录目标为 B，标记为 `解析与状态不一致`。

这些提示都在前端派生，不阻断观战页运行。

## 舞台联动

选中行动包后：

- 中央舞台高亮 actor。
- 如果能推导出 target，轻微高亮 target。
- 如果状态影响到死亡、放逐、守护、查验、警徽，相关玩家使用对应 tone。
- 顶部或舞台中心显示当前行动包编号范围，方便和右侧轨道对齐。

未选中行动包时，舞台保持现有导播逻辑。

## 组件与数据流

新增前端派生函数：

- `buildLiveDebugTraces(events, directorCue?, godViewState?)`
- 输入实时或回放可见事件。
- 输出 `LiveDebugTrace[]` 和当前选中 trace 的高亮信息。

建议新增组件：

- `LiveDebugTraceRail.tsx`
  - 渲染行动包列表、过滤开关和展开详情。
- `LiveDebugTraceCard.tsx`
  - 渲染单个行动包压缩态和展开态。
- 可选 `LiveDebugTraceDetails.tsx`
  - 负责 prompt/raw/parsed/payload/state diff 的分区展示。

现有接入点：

- `LiveStageExperience.tsx` 管理 `selectedTraceId`。
- `GodViewIntelPanel.tsx` 接收 `debugTraceRail`，替换当前 `debugTimeline`。
- `LiveDirectorStage.tsx` 接收 `selectedTrace` 或 `highlightedPlayers`，做舞台联动。

## 测试范围

派生层测试：

- 将一组 `action_requested → model_response_received → action_parsed → state_updated` 聚合为一个 trace。
- 系统事件形成系统 trace。
- `model_response_delta` 不污染列表，但可计入模型节点状态。
- 缺少 `action_parsed` 时标记 warning。
- parsed choice 与 state payload 冲突时标记 error。

组件测试：

- 轨道渲染行动包编号范围、标题、节点条和影响摘要。
- 点击行动包展开详情。
- “只看异常”过滤 OK trace。
- 选中行动包时回调高亮玩家。

页面测试：

- 观战页仍展示现有上帝视角内容。
- 调试轨道替换原 raw timeline。
- 回放页在可见事件变化时 trace 随 playback current event 更新。

## 实施顺序

1. 先实现 `buildLiveDebugTraces` 和测试。
2. 用 `LiveDebugTraceRail` 替换当前折叠的 raw `LiveEventTimeline`。
3. 加入展开详情和“只看异常”过滤。
4. 接入舞台高亮。
5. 根据真实对局事件补齐异常规则。

## 验收标准

- 调试时能用行动包而不是 raw event 定位一轮玩家行为。
- 至少能清楚看到 request、model、parsed、state 四个节点是否齐全。
- 展开行动包后能看到模型输入输出和关键 payload。
- 状态变化用人能读懂的 diff 展示。
- 不破坏当前观战舞台、右侧情报区和回放播放逻辑。
