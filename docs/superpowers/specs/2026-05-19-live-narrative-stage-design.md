# 狼人杀直播叙事舞台设计

**日期**: 2026-05-19
**范围**: 优化 `apps/web` 中 `/games/live/:runId` 和回放舞台的观战表达，把现有事件驱动舞台升级为“法官旁白 + 玩家发言表演”的狼人杀直播体验。第一版只改前端派生层和舞台展示，不改后端规则、事件协议或模型决策。

## 背景

当前直播页已经具备实时 SSE、前端导播队列、模型公开文本流式事件、上帝视角局势派生、中央圆桌舞台、玩家卡和调试 Action Trace Rail。页面能看见事件，也能追踪玩家状态，但整体仍偏“调试后台”：用户需要从事件标题、payload 文本、玩家状态和右侧情报中自行拼出狼人杀直播流程。

常规狼人杀直播的核心不是单条事件，而是连续的节目节奏：

- 法官引导阶段：天黑请闭眼、天亮公布、进入发言、开始投票、胜负结算。
- 玩家进行表演：思考、操作、公开发言、归票、投票、技能发动。
- 场上给出反馈：下一位发言、死亡公布、票型变化、平安夜、阵营胜负。

本设计的目标是把现有事实事件重新组织成观众能自然理解的叙事流。

## 目标

- 为直播舞台增加“法官旁白”字幕，让阶段推进和结算像狼人杀主持人控场。
- 强化当前玩家表演：玩家等待、思考、逐字发言、最终发言全文、投票或行动状态。
- 保留现有导播播放节奏，长发言仍按 `DirectorCue` 的 1x/2x 机制可读播放。
- 复用现有 SSE 事件、`DirectorCue`、`GodViewState` 和 `LiveSpectatorState`，第一版不要求后端新增字段。
- 未知事件或 payload 不完整时平稳降级，不让舞台空白或崩溃。

## 非目标

- 不新增后端 `narration` 事件。
- 不改变狼人杀规则、胜负判定、模型 prompt、行动解析或公开/私密信息边界。
- 不引入 AI 主播赛况分析；第一版旁白使用确定性模板。
- 不新增语音、弹幕、礼物、直播间互动或观众同步能力。
- 不重做右侧调试轨、底部票型板或玩家配置页。

## 推荐方案

新增前端纯派生模块：

```text
apps/web/src/features/games/liveNarrative.ts
```

它接收现有观战事实：

```text
events[] + current DirectorCue + GodViewState + LiveSpectatorState
```

输出舞台专用叙事状态：

```ts
type LiveNarrativeState = {
  cue: NarrativeCue;
  speaker: NarrativeSpeaker | null;
  nextSpeakerName: string | null;
  judgeLine: string;
  performerLine: string;
  detailLine: string;
};
```

`DirectorCue` 继续负责“播哪条事件、停留多久”；`GodViewState` 继续负责“场上事实是什么”；`LiveNarrativeState` 只负责“这一刻怎么讲给观众听”。这样边界清晰，风险低，也便于用纯函数测试覆盖。

## 数据模型

第一版 `NarrativeCue` 使用确定性字段，不保存复杂历史：

```ts
type NarrativeCueKind =
  | "judge"
  | "player-thinking"
  | "player-speaking"
  | "player-action"
  | "vote"
  | "death"
  | "terminal"
  | "fallback";

type NarrativeCue = {
  eventId: number | null;
  kind: NarrativeCueKind;
  tone: "neutral" | "night" | "day" | "danger" | "safe" | "vote" | "terminal";
  judgeLine: string;
  performerLine: string;
  detailLine: string;
  actorName: string | null;
  action: string | null;
  speechText: string;
};
```

字段语义：

- `judgeLine`：法官/主持人口吻的主字幕。
- `performerLine`：当前玩家状态，例如“8 号 Sam 正在发言”。
- `detailLine`：下一位发言、票型、死亡、平安夜等补充信息。
- `speechText`：公开发言或总结文本，优先来自流式公开文本和 `debate_entry`。
- `tone`：供舞台切换夜晚、白天、危险、平安夜、投票、终局视觉强调。

## 事件映射

`deriveLiveNarrativeState()` 按当前导播 cue 解析，不直接追最新 SSE。核心规则：

- `phase_started/night`：`judgeLine = "天黑请闭眼。"`，`tone = "night"`。
- `phase_started/day`：根据死亡信息生成“天亮了，昨夜有人出局。”或“天亮了，昨夜平安无事。”。
- `phase_started/vote`：生成“发言结束，进入放逐投票。”。
- `phase_started/summary`：生成“本轮进入总结，玩家整理自己的判断。”。
- `action_requested`：根据行动生成玩家思考状态，公开发言显示“准备发言”，投票显示“正在权衡投票”，夜间公开安全行动显示“正在执行夜间行动”。
- `model_request_started` 和 `model_thinking_tick`：沿用后端等待文案，但转换成表演状态。
- `model_response_delta`：合并到当前请求对应 `DirectorCue` 后，显示“玩家正在发言”，`speechText` 使用可见增量文本。
- `action_parsed`：公开 `say`/`summary` 显示为玩家发言或总结；投票、查验、守护等行动只显示公开允许的选择或等待揭晓，不泄露私密信息。
- `state_updated` 中的 `debate_entry`：显示最终发言全文。
- `state_updated` 中的 `votes`：显示“投票结果公布”，补充最高票或票型摘要。
- `state_updated` 中的 `exiled`：显示“X 被放逐出局”。
- `state_updated` 中的 `night_deaths`、`eliminated`、`protected`：显示死亡公布或平安夜。
- `state_updated` 中的 `werewolf_self_exploded`、`hunter_shot`、`idiot_revealed`、`sheriff_badge_target`：显示技能或警徽公布。
- `game_completed`：显示胜利阵营和终局旁白。
- 未识别事件：使用当前 `DirectorCue.title/body` 生成 `fallback`。

## 舞台展示

`LiveDirectorStage` 保留现有圆桌、玩家卡、自动跟随、调试高亮和队列徽标，中心内容改为叙事舞台：

- 顶部小字幕：`judgeLine`，像法官控场。
- 当前玩家区：展示 actor 或当前发言玩家的大头像、座位、角色、阵营和状态。
- 发言区：优先展示 `speechText`，为空时展示 `performerLine` 和 `detailLine`。
- 底部提示：下一位发言、队列剩余、自动跟随。
- 投票、死亡、平安夜、终局用 `tone` 调整边框和强调色。

当前 `LiveDirectorStage.tsx` 已较大。实现时可以先在原文件内接入；如果改动使文件继续膨胀，拆出：

```text
apps/web/src/features/games/components/LiveNarrativeCenter.tsx
```

这个组件只负责中心叙事，不拥有玩家选择、导播控制或上帝视角派生逻辑。

## 数据流

现有链路保持：

```text
SSE -> useGameRunEvents -> events[]
events[] -> useLiveDirector -> current DirectorCue
events[] -> deriveLiveSpectatorState -> LiveSpectatorState
events[] + spectator -> deriveGodViewState -> GodViewState
```

新增链路：

```text
events[] + director.currentCue + spectatorState + godViewState
  -> deriveLiveNarrativeState()
  -> LiveDirectorStage
```

`LiveStageExperience` 负责调用派生函数并把 `narrativeState` 传给 `LiveDirectorStage`。这样页面装配层掌握所有输入，舞台组件只渲染结果。

## 公开信息边界

叙事层只能展示已经进入公开 SSE 或现有前端状态的内容。第一版遵守现有公开策略：

- 公开展示 `debate`、`sheriff_speech`、`sheriff_pk_speech`、`summarize` 的 `say`/`summary`。
- 投票目标只在现有公开事件中出现后展示。
- 查验、守护、女巫、猎人等行动不提前泄露，除非当前事件 payload 已公开对应结算。
- 狼人夜间讨论和击杀共识仍沿用当前后端私密事件策略，不在叙事层补造内容。

## 错误处理

- 没有 `currentCue`：显示“等待导播事件”，并保留圆桌和玩家卡。
- 找不到 actor：使用阶段旁白和 `GodViewState.speakerFlow.current` 兜底。
- payload 缺字段：使用 `DirectorCue.title/body` 降级。
- 长文本为空：显示玩家状态，不渲染空白发言框。
- 旧回放缺少新增事件：仍能通过 `phase_started`、`action_parsed`、`state_updated` 生成基础旁白。

## 测试策略

新增纯函数测试：

- 夜晚、白天、投票、总结阶段生成正确法官旁白。
- `action_requested` 生成玩家思考或准备发言状态。
- `model_response_delta` 和 `debate_entry` 生成玩家发言表演。
- `votes`、`exiled`、`night_deaths`、平安夜生成公开结算旁白。
- `game_completed` 生成终局旁白。
- 未知事件降级到 `DirectorCue`。

更新组件/页面测试：

- `LiveDirectorStage` 显示法官旁白、当前玩家状态和发言文本。
- `LiveStageExperience` 将 `narrativeState` 传入舞台。
- `LiveGamePage.test.tsx` 覆盖直播页出现“天黑请闭眼/天亮了/进入放逐投票”这类观众可见文案。
- 回放页复用同一叙事舞台时，空事件仍显示安全空态。

建议验证命令：

```bash
pnpm --dir apps/web test -- --run src/features/games/liveNarrative.test.ts src/features/games/components/LiveDirectorStage.test.tsx src/pages/LiveGamePage.test.tsx src/pages/GamePlaybackPage.test.tsx
pnpm --dir apps/web build
```

## 验收标准

- 直播页第一眼能看出当前是狼人杀直播，而不是事件调试台。
- 阶段推进由法官旁白串联，观众能理解“现在轮到谁、正在做什么、下一步是什么”。
- 玩家公开发言被突出展示，并保留逐字流式观感。
- 投票、死亡、平安夜、技能、终局以公开结算方式呈现。
- 后端事件协议、游戏规则和私密信息边界保持不变。
- 现有调试轨、神视角信息和导播播放控制不退化。
