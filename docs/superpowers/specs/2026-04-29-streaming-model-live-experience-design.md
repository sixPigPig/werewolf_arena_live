# 流式模型直播体验设计

## 背景

当前项目的模型调用是同步非流式请求。后端向 OpenAI-compatible `/chat/completions` 发送 `stream: false`，等待完整响应后读取 `choices[0].message.content`，再解析 JSON、校验行动、推进狼人杀状态。

前端直播页并不是直接订阅模型 token，而是通过后端 SSE 接收对局事件。一次玩家行动通常会经历：

1. `action_requested`
2. `model_request_started`
3. 等待模型完整返回
4. `model_response_received`
5. `action_parsed`
6. `state_updated`

等待模型时网页会停在“请求模型”状态。模型慢时，用户容易感觉页面卡住。

## 目标

最大限度提升网页观战体验，让用户在模型生成期间持续看到有意义的反馈。

核心目标：

- 模型等待期间页面保持“活着”，不出现长时间静止。
- 公开发言类内容尽早逐字展示，形成实时发言感。
- 游戏权威状态仍由完整 JSON 解析后的结果推进，避免半截内容污染规则状态。
- 保持现有 SSE 架构，不引入 WebSocket。
- 兼容不支持流式或流式失败的模型提供方。

非目标：

- 不改变狼人杀规则与行动判定。
- 不让前端直接决定游戏状态。
- 不在第一阶段重写所有 provider 或切换 API 协议。
- 不把原始 JSON token 直接展示给观众。

## 推荐方案

采用“混合流式直播层”。

后端模型请求支持流式读取，但游戏逻辑仍等待完整模型响应后再解析 JSON。流式过程中，后端把可展示的增量内容包装成新的 SSE 事件推给前端。前端用这些事件改善观战感；最终决策仍由 `action_parsed` 和 `state_updated` 确认。

这比纯流式更适合当前项目，因为模型输出是结构化 JSON。若直接展示原始 JSON 流，用户会看到 `{ "reasoning": ... }` 这类半成品，体验反而变差。

## 事件协议

保留现有事件：

- `action_requested`
- `model_request_started`
- `model_request_failed`
- `model_response_received`
- `action_parsed`
- `state_updated`
- 其他对局生命周期事件

新增事件：

### `model_response_delta`

模型生成过程中的增量片段。

建议 payload：

```json
{
  "request_id": "req_xxx",
  "model": "qwen3.6-plus",
  "delta": "我认为",
  "visible_text": "我认为",
  "field": "say",
  "is_public": true
}
```

字段说明：

- `request_id`：一次模型请求的稳定 ID。
- `delta`：已清洗的公开增量文本，第一版与 `visible_text` 保持一致；不得包含原始模型 token、推理字段或私有行动目标。
- `visible_text`：适合前端展示的增量文本。
- `field`：当前可展示字段，如 `say`、`summary`，无法识别时为空。
- `is_public`：是否适合公开展示。

公开 SSE 事件只承载观众可见信息：

- `model_request_started` 只发布 `request_id`、`model`、等待文案、可流式字段和公开标记。
- `model_response_received` 只发布 `request_id`、`model` 和“已接收，正在解析”的状态文案。
- `action_parsed` 可以发布最终 `choice`，但 `result`/`visible_result` 只保留 `say`、`summary` 等白名单展示字段。
- `prompt`、`world_state`、完整 `raw_response` 只保存在内部日志、检查点或复盘数据中，不进入直播 SSE payload。

### `model_thinking_tick`

模型请求仍在进行但短时间没有可展示 token 时发出的心跳事件。

建议 payload：

```json
{
  "request_id": "req_xxx",
  "model": "qwen3.6-plus",
  "elapsed_ms": 4200,
  "message": "正在分析场上发言..."
}
```

用途：

- 前端更新计时和等待文案。
- 让用户确认连接仍然正常。
- 当模型首 token 很慢时弥补空白。

## 可流式展示范围

第一阶段只公开展示“适合观众提前看到”的文本。

公开发言类行动：

- `debate`：展示 `say`
- `sheriff_speech`：展示 `say`
- `sheriff_pk_speech`：展示 `say`
- `summarize`：展示 `summary`

非公开或容易剧透的决策类行动：

- `vote`
- `sheriff_vote`
- `sheriff_runoff_vote`
- `investigate`
- `remove`
- `protect`
- `witch_save`
- `witch_poison`
- `hunter_shoot`
- `speech_order`
- `sheriff_badge`
- `bid`
- `sheriff_run`
- `sheriff_withdraw`

这些行动不提前展示目标，只展示等待状态，如“正在权衡目标”“正在分析局势”。最终选择等 `action_parsed` 或 `state_updated` 揭晓。

## 后端设计

### Provider 能力

新增一个可选流式接口，不破坏现有 `complete_json()`：

```python
class ModelProvider(Protocol):
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        ...

    def stream_json(self, *, model: str, prompt: str, temperature: float) -> Iterator[str]:
        ...
```

实现原则：

- `complete_json()` 继续作为权威、兼容路径。
- 支持流式的 provider 实现 `stream_json()`。
- 不支持流式时自动回退到 `complete_json()`，并仍发送等待心跳。
- 流式读取完成后拼接完整 `raw_response`，走现有 JSON 解析和校验流程。

### 流式解析器

新增一个轻量的展示层解析器，用于从 JSON 文本流中提取可展示字段。

它只服务前端体验，不参与游戏判定。

职责：

- 接收累积的 raw text。
- 对公开字段尝试提取稳定新增片段。
- 避免展示 JSON 标点、字段名、转义残片。
- 解析失败时保持沉默，等待下一段。

第一阶段可保守实现：

- 只识别 `"say": "..."` 和 `"summary": "..."`。
- 仅当字符串内容足够稳定时发布增量。
- 如果无法可靠提取，就不发 `model_response_delta`，只发 `model_thinking_tick`。

### Engine 集成

`GameEngine._player_action()` 当前负责发布 `model_request_started` 并调用 `generate_action()`。建议把流式能力封装在 `generate_action()` 或新 helper 中，避免 engine 直接处理 provider 细节。

推荐新 helper：

```python
generate_action_with_events(
    provider=...,
    action=...,
    world_state=...,
    model=...,
    allowed_values=...,
    result_key=...,
    event_sink=...,
    event_context=...
)
```

它负责：

- 生成 `request_id`。
- 发布等待 tick。
- 消费 provider stream。
- 发布 `model_response_delta`。
- 拼接完整 raw response。
- 调用现有 `parse_json_object()` 和选项校验逻辑。

现有 `generate_action()` 保留给测试和非直播路径。

### 等待心跳实现

同步回退路径不能依赖模型请求循环本身发布 tick，因为 `complete_json()` 会阻塞直到完整响应返回。推荐在一次模型请求开始时创建一个轻量的 `ModelRequestProgress` 控制器：

- 请求开始时记录 `request_id`、开始时间、actor、action、model。
- 启动一个后台 tick worker，每 1-2 秒检查请求是否仍在进行。
- 如果没有新的 `model_response_delta`，发布 `model_thinking_tick`。
- 流式 delta 发布时更新最后活动时间，避免 tick 和文字流同时刷屏。
- 请求成功、失败或重试时停止 worker。

这样无论 provider 走流式还是同步回退，前端都能持续收到进度反馈。

## 前端设计

### SSE Hook

`useGameRunEvents()` 新增事件类型：

- `model_response_delta`
- `model_thinking_tick`

事件仍按 id 去重和排序。

### 观战状态

`deriveLiveSpectatorState()` 增强：

- `model_request_started` 后进入 `requesting`。
- `model_response_delta` 到达时进入 `responding` 或复用 `responded`。
- 保存当前 `request_id` 的累积可见文本。
- `model_thinking_tick` 更新玩家等待文案和耗时。
- `action_parsed` 到达后把临时流式文本收束为正式结果。

可新增状态：

```ts
type LivePlayerStatus =
  | "waiting"
  | "thinking"
  | "requesting"
  | "streaming"
  | "responded"
  | "acted"
  | "out";
```

### 导播舞台

`LiveDirectorStage` 升级为更强的实时主舞台：

- 当前玩家正在思考时显示动态文案和计时。
- 收到公开 `visible_text` 时做打字机式累积展示。
- 非公开行动显示“正在做决定”，不泄露目标。
- 最终 `action_parsed` 或 `state_updated` 到达后切换成正式事件。

### 时间线

默认不把每个 `model_response_delta` 都作为完整时间线卡片展示，避免刷屏。

建议：

- 主舞台消费 delta。
- 调试面板可以显示已清洗的 delta 事件，但不展示原始 prompt、world state 或 raw response。
- 时间线只展示 `model_request_started`、`model_response_received`、`action_parsed`、`state_updated` 等关键节点。

## 错误与降级

如果流式请求失败：

- 发布 `model_request_failed`。
- 如果 provider 支持同步重试，可回退一次 `complete_json()`。
- 前端显示“流式中断，正在重试”。

如果流式过程中没有可展示字段：

- 持续发布 `model_thinking_tick`。
- 最终仍展示完整结果。

如果模型输出不是合法 JSON：

- 沿用现有 retry 机制。
- 每次 retry 使用新的 `request_id`。
- 前端把上一轮临时流式内容标记为已重试或清空，避免误导。

## 开发流程

### 阶段 1：等待体验兜底

目标是在不改 provider 流式能力前，先让页面等待时不静止。

工作：

- 后端为模型请求增加 `request_id`。
- 后端在长时间等待时发布 `model_thinking_tick`。
- 前端消费 tick，显示计时和动态等待文案。
- 导播舞台优化“正在请求模型”的状态。

验收：

- 模型等待超过 2 秒时，页面有持续状态变化。
- SSE 不中断，终局事件仍正常关闭连接。
- 原有对局结果不变。

### 阶段 2：公开文本流式展示

目标是让公开发言逐步出现。

工作：

- provider 增加流式请求路径。
- 后端拼接完整 raw response，保持现有 JSON 解析。
- 新增展示层字段提取器。
- 发布 `model_response_delta`。
- 前端主舞台累积 `visible_text`。

验收：

- `debate`、`sheriff_speech`、`sheriff_pk_speech`、`summarize` 能逐步展示文本。
- 非公开行动不会提前泄露目标。
- 完整结果仍通过 `model_response_received` 和 `action_parsed` 落地。

### 阶段 3：体验打磨与回退完善

目标是提升稳定性和观感。

工作：

- 给不同 action 配置等待文案。
- 优化主舞台排版、打字机节奏、长文本滚动。
- 调试面板展示 request 生命周期。
- 增加流式失败回退测试。

验收：

- 流式失败不会卡住对局。
- 快速模型和慢速模型都有自然反馈。
- 时间线不被 delta 刷屏。

## 测试计划

后端测试：

- provider 同步路径保持兼容。
- 流式 chunk 能拼回完整 raw response。
- `model_response_delta` 只对公开字段发布。
- 非公开行动只发 tick，不发可见 delta。
- 流式失败时发布失败事件并回退或终止。
- SSE 格式包含新增事件类型。

前端测试：

- `useGameRunEvents()` 能接收新增事件。
- spectator state 能累积当前 request 的可见文本。
- 主舞台展示 tick 文案和耗时。
- 主舞台展示公开发言流式内容。
- 时间线不因 delta 事件刷屏。
- 终态事件仍关闭 EventSource。

集成验证：

- 启动 API 和 Web。
- 创建一局演示对局。
- 观察模型等待期间是否持续更新。
- 观察公开发言是否逐步显示。
- 确认对局最终能正常完成并写入日志。

## 风险与取舍

### JSON 流式解析不稳定

风险：模型输出中途不是合法 JSON，字段字符串可能包含转义。

处理：展示层解析器保守提取；提取不了就不展示 delta，只显示 tick。游戏判定只使用完整 JSON。

### Provider 兼容差异

风险：DeepSeek、MiniMax、Qwen 的流式 chunk 格式可能略有差异。

处理：先抽象 OpenAI-compatible SSE chunk 解析器，再为差异写测试；不支持时回退同步。

### 事件量变大

风险：每个 token 都发 SSE 会增加前端压力。

处理：后端做节流，例如每 80-150ms 或累计一定字符后发布一次 delta。

### 公开信息泄露

风险：夜晚行动、投票目标提前显示会破坏观战节奏。

处理：只对白天公开发言和总结展示内容；其他行动仅显示等待文案。

## 推荐优先级

先做阶段 1 和阶段 2。

阶段 1 能快速解决“页面卡住”的感知问题，风险最低。阶段 2 是核心体验提升，让公开发言实时出现。阶段 3 可在基础稳定后继续打磨。

## 确认点

需要确认以下产品选择：

1. 公开流式展示范围是否只包括 `debate`、`sheriff_speech`、`sheriff_pk_speech`、`summarize`。
2. 夜晚行动和投票是否只显示等待状态，不提前显示模型推理或目标。
3. 第一版是否允许同步回退，即模型不支持流式时仍能正常完成对局，只是没有逐字效果。
4. 时间线是否默认隐藏 delta，只在主舞台和调试面板展示。
