# 观战页阶段条开发文档

## 背景

观战页和历史回放页现在共用一套播放模型：页面拿到完整或实时增长的 `LiveGameEvent[]`，交给 `useLiveDirector` 生成导播 cue，再用 `currentEventId` 截断事件列表，最后由 `deriveLiveSpectatorState`、`deriveGodViewState`、`deriveLiveNarrativeState` 派生舞台内容。

因此，阶段条应该基于事件流本身，而不是基于最终复盘 `rounds` 或后端额外状态。这样实时观战和历史回放可以复用同一套阶段定位逻辑，点击阶段后也只需要改变导播当前事件位置，现有舞台派生逻辑会自然回到对应阶段。

## 目标

- 在观战/回放舞台增加阶段条，展示主阶段序列：`夜一 -> 昼一 -> 夜二 -> 昼二 -> ...`。
- 点击某个阶段后，从该阶段起点继续播放。
- 阶段条支持实时观战和历史回放。
- 阶段条状态与导播播放进度同步，不能出现阶段高亮和舞台内容不一致。
- 不改变后端事件结构，不引入新的接口契约。

## 非目标

- 不做精细到行动级的时间轴跳转，例如“预言家查验”“警长投票”。
- 不把 `vote`、`summary` 单独展示为主阶段节点。
- 不重写导播播放模型。
- 不新增后端阶段索引字段，除非后续发现事件流不能覆盖需求。

## 现有依据

- `LiveGamePage` 通过 `useLiveDirector(events)` 得到 `currentEventId`，并用 `events.filter(event.id <= currentEventId)` 得到舞台可见事件。
- `GamePlaybackPage` 也使用同样的导播截断模型。
- `LiveGameEvent` 已包含阶段定位需要的字段：`id`、`type`、`round`、`phase`。
- 历史回放构造器会为每轮生成 `phase_started`，包括 `phase="night"` 和 `phase="day"`。
- 实时引擎可能还会产生 `phase="vote"`、`phase="summary"`，但用户期望的主阶段条只展示夜/昼。

## 推荐方案

基于完整事件列表建立阶段索引：

1. 扫描 `LiveGameEvent[]`。
2. 只取 `event.type === "phase_started"` 的事件。
3. 只保留 `event.phase === "night"` 或 `event.phase === "day"`。
4. 要求 `event.round` 是有效数字。
5. 每个阶段节点记录该阶段起始事件 id。
6. 点击阶段节点时调用导播跳转方法，将 `currentEventId` 设置为该阶段起始事件 id。

这样，跳转后的舞台事件列表会变成：

```ts
const visibleEvents = events.filter((event) => event.id <= currentEventId);
```

现有派生状态会自动回到目标阶段起点。

## 阶段数据模型

新增一个轻量模型，建议放在 `packages/game-client/src/live/livePhaseBar.ts`，并由 `packages/game-client/src/live/index.ts` 导出，供 `apps/web` 复用。

```ts
export type LivePhaseKind = "night" | "day";

export type LivePhaseSegment = {
  id: string;
  round: number;
  phase: LivePhaseKind;
  label: string;
  startEventId: number;
  isCurrent: boolean;
  isVisited: boolean;
};
```

字段说明：

- `id`: 稳定 React key，格式建议为 `round-${round}-${phase}`。
- `round`: 狼人杀轮次，来自 `LiveGameEvent.round`。
- `phase`: 主阶段类型，只允许 `night` / `day`。
- `label`: 中文短标签，例如 `夜一`、`昼一`。
- `startEventId`: 阶段起点事件 id，用于导播跳转。
- `isCurrent`: 当前播放位置是否落在该阶段范围内。
- `isVisited`: 当前播放位置是否已经到达或越过该阶段起点。

## 阶段标签规则

阶段条使用短标签，减少横向空间压力：

```ts
夜一、昼一、夜二、昼二
```

数字建议用中文数字。一到十可直接映射；超过十时可以先显示阿拉伯数字，例如 `夜11`，避免为了极端局数引入复杂格式化。

建议封装：

```ts
function phaseSegmentLabel(round: number, phase: LivePhaseKind): string {
  const prefix = phase === "night" ? "夜" : "昼";
  return `${prefix}${roundLabel(round)}`;
}
```

## 当前阶段判定

推荐用“事件 id 区间”判定当前阶段。

构造阶段列表后，每个阶段的有效范围是：

```ts
[segment.startEventId, nextSegment.startEventId)
```

最后一个阶段的范围是：

```ts
[segment.startEventId, Infinity)
```

当 `currentEventId` 位于该范围内时，该阶段 `isCurrent = true`。

边界处理：

- `currentEventId === null`: 所有阶段 `isCurrent=false`、`isVisited=false`。
- 当前播放还在 `game_started` 或 `round_started`，尚未到第一段 `phase_started`: 不高亮任何阶段。
- 当前播放进入 `vote` 或 `summary`: 不单独新增节点，仍高亮最近的 `day` 阶段。
- 当前播放到 `game_completed` 或 `game_failed`: 高亮最后一个已进入的主阶段。

## 阶段提取函数

建议新增纯函数：

```ts
export function buildLivePhaseSegments(
  events: LiveGameEvent[],
  currentEventId: number | null,
): LivePhaseSegment[] {
  // 1. filter phase_started night/day with numeric round
  // 2. sort by event.id
  // 3. de-duplicate by round + phase, keep earliest event id
  // 4. compute isVisited/isCurrent by currentEventId and next segment start
}
```

去重规则：

- 如果同一 `round + phase` 出现多次，保留最早的 `event.id`。
- 这能容忍重连、回放修复或后端重复事件。

排序规则：

- 优先使用事件 id 升序。
- 不手动重排成 `night/day`，避免事件流真实顺序和 UI 跳转目标不一致。

## 导播跳转能力

`useLiveDirector` 现在有内部 `moveToIndex(nextIndex)`，但没有公开跳转 API。需要新增：

```ts
seekToEventId: (eventId: number) => void;
```

行为细节：

- 找到 `cues.findIndex((cue) => cue.eventId >= eventId)`。
- 如果正好存在 `cue.eventId === eventId`，跳到该 cue。
- 如果没有完全匹配，跳到第一个大于该 id 的 cue。
- 如果目标小于第一个 cue，跳到第一个 cue。
- 如果目标大于最后一个 cue，跳到最后一个 cue。
- 跳转后重置 `startedAtRef`，避免继承上一个 cue 的剩余播放时间。
- 保持当前暂停状态不变：暂停时点击阶段仍停在目标阶段；播放中点击阶段则从目标阶段继续自动播放。

为什么用 `cue.eventId >= eventId`：

- `buildDirectorCues` 会合并 `model_response_delta` 到 `model_request_started` 的 cue，部分事件不会生成独立 cue。
- 阶段起点 `phase_started` 通常会生成 cue，但使用 `>=` 能让 API 更稳健。

## UI 组件设计

新增组件：

```tsx
type LivePhaseBarProps = {
  segments: LivePhaseSegment[];
  onSelectPhase: (segment: LivePhaseSegment) => void;
};
```

建议位置：

- 放在 `LiveStageExperience` 内，`LiveStageModule` 上方。
- 这样左右信息面板、底部状态板和舞台布局不需要重排。

空状态：

- 当 `segments.length === 0` 时不渲染阶段条。
- 实时刚开始、尚未收到第一段 `phase_started` 时页面保持现状。

视觉状态：

- 当前阶段：高亮边框和更强文字色。
- 已经过阶段：正常可点击状态。
- 未经过阶段：历史回放里可以点击，因为完整事件已知；实时观战里不会出现未来阶段，所以无需 disabled。
- Hover/focus：使用现有暗色哥特 UI 的 amber/teal 色系，保持与观战页一致。

交互状态：

- 每个阶段节点使用 `<button type="button">`。
- `aria-current="step"` 标记当前阶段。
- `aria-label` 建议为 `从夜一开始播放`、`从昼二开始播放`。
- 横向内容超出时允许水平滚动，不换行挤压舞台。

## 页面集成

在 `LiveGamePage`：

```ts
const phaseSegments = useMemo(
  () => buildLivePhaseSegments(events, director.currentEventId),
  [events, director.currentEventId],
);
```

然后传给 `LiveStageExperience`：

```tsx
<LiveStageExperience
  phaseSegments={phaseSegments}
  onSelectPhase={(segment) => director.seekToEventId(segment.startEventId)}
  ...
/>
```

在 `GamePlaybackPage`：

```ts
const phaseSegments = useMemo(
  () => buildLivePhaseSegments(allEvents, director.currentEventId),
  [allEvents, director.currentEventId],
);
```

注意：

- 构建阶段条要用完整事件列表，不是 `visibleEvents/stageEvents`。
- 舞台派生仍继续使用截断后的 `visibleEvents/stageEvents`。
- 这是实现“可以点击未来阶段回放”的关键。

## 实时观战和历史回放差异

历史回放：

- `allEvents` 一次性完整返回。
- 阶段条一开始就能展示完整阶段序列。
- 点击任意阶段都能跳转。

实时观战：

- `events` 由 SSE 持续增长。
- 阶段条只展示已经到达的阶段。
- 如果用户点击较早阶段回看，SSE 继续接收新事件，阶段条会继续增长。
- 若播放中停留在旧阶段，`backlogCount` 会自然增加，现有“追到最新”能力仍可用。

## `vote` / `summary` 处理

主阶段条只展示 `night/day`：

- `vote` 阶段视作白天后半段，继续高亮当前轮 `day`。
- `summary` 阶段视作本轮收尾，继续高亮当前轮 `day`。

如果后续产品希望展示更细粒度阶段，可以在同一个阶段模型上扩展 `LivePhaseKind`，但当前不要提前设计复杂层级。

## 样式建议

新增 CSS class 建议：

- `.live-phase-bar`
- `.live-phase-bar-track`
- `.live-phase-segment`
- `.live-phase-segment-current`
- `.live-phase-segment-visited`

布局建议：

- 外层宽度 `100%`。
- 内层 `display:flex; gap:0.5rem; overflow-x:auto;`.
- 按钮固定最小宽度，避免文字和状态变化造成布局抖动。
- 不使用大卡片，不把阶段条做成独立浮层。

## 测试计划

### 纯函数测试

新增 `packages/game-client/src/live/livePhaseBar.test.ts`：

- 从 `phase_started night/day` 事件生成 `夜一/昼一/夜二/昼二`。
- 忽略 `vote`、`summary`、`round_started`、`state_updated`。
- 同一 `round + phase` 重复时保留最早事件。
- `currentEventId` 在夜间区间时，高亮对应夜。
- `currentEventId` 在昼间、投票、总结、终局事件时，高亮对应昼。
- `currentEventId` 在第一阶段前时，不高亮任何阶段。

### Hook 测试

补充 `useLiveDirector` 的行为测试，或通过组件测试覆盖：

- `seekToEventId` 能跳到目标 cue。
- 目标 event id 没有对应 cue 时，跳到后续最近 cue。
- 暂停状态下跳转后仍保持暂停。
- 播放状态下跳转后继续自动播放。

### 页面/组件测试

在 `GamePlaybackPage.test.tsx` 或新增组件测试里覆盖：

- 回放页渲染阶段条。
- 阶段条包含 `夜一`、`昼一`、`夜二`。
- 点击 `昼一` 后，当前阶段标记切换到 `昼一`。
- 点击阶段后，舞台只展示该阶段起点及之前事件派生出的状态。

在 `LiveGamePage.test.tsx` 覆盖：

- 实时收到第一轮夜晚阶段后显示 `夜一`。
- 后续收到白天阶段后追加 `昼一`。
- 点击已出现的阶段能回退播放位置。

## 验收标准

- 历史回放页进入后，完整阶段条按事件顺序显示。
- 实时观战页随着事件到达逐步出现阶段节点。
- 点击 `夜二` 后，舞台从第二轮夜晚阶段开始播放。
- 点击 `昼一` 后，阶段高亮和舞台内容都回到第一轮白天。
- 播放速度、暂停/继续、追到最新仍可正常使用。
- 没有 `phase_started` 事件的异常数据不会导致页面报错。
- 阶段条横向溢出时可滚动，不压缩或遮挡舞台布局。

## 风险和注意事项

- 不要用 `visibleEvents` 构建阶段条，否则历史回放只能看到已播放到的阶段，无法点击未来阶段。
- 不要直接 `setCurrentEventId(segment.startEventId)` 暴露到页面层，应该通过 `useLiveDirector` 的跳转 API，统一处理 cue 映射和计时器重置。
- 不要单独把 `vote` 显示成 `昼一` 后面的节点，否则会偏离用户期望的主阶段序列。
- 不要依赖最终 `rounds`，实时观战无法保证有完整轮次状态。
- 如果未来后端事件 id 不连续也没关系，阶段跳转只依赖相对大小和 cue 映射。

## 建议实施顺序

1. 在 `packages/game-client/src/live/` 新增阶段提取纯函数和测试。
2. 为 `useLiveDirector` 增加 `seekToEventId`，补充跳转测试。
3. 新增 `LivePhaseBar` 组件和组件测试。
4. 在 `GamePlaybackPage` 接入阶段条，先验证历史回放完整跳转。
5. 在 `LiveGamePage` 接入阶段条，验证实时增长和回退播放。
6. 做一次移动/窄屏视觉检查，确认横向滚动和按钮状态不会挤压舞台。
