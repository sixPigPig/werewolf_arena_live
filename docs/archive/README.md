# 归档文档

这里的文档描述的是 **V1 引擎**（`apps/api/app/werewolf/`）的设计与行为。当前唯一在演进的对局路径是 Live V2，V1 已于 2026-08-20 决定整体退场。

**不要把这里的任何内容当作当前实现的依据。** 需要了解现状请看仓库根目录的 `README.md`、`docs/architecture.md` 和 `docs/live-v2-refactor-guidelines.md`。

归档于 2026-08-20。文件通过 `git mv` 移动，历史完整保留。

## 目录

### `plans/`（18 份）

2026-07-16 之前的实施计划。**这里的 checkbox 完全不可信**：18 份里有 16 份所有任务都未勾选，但对照代码，绝大多数功能其实已经落地。按未勾选的任务继续开发会重做已完成的工作。

### `v1-specs/`（19 份）

V1 的设计文档，按主题分为几组：

- **V1 直播与语音**：phase bar、字幕、动作可见性、语音流、语音持久化、回放语音、录制回放
- **P0 到 P3 修复系列**：四份 remediation 设计，全部锚定 `werewolf/engine.py`
- **发言与活人感**：lifelike player system、speech-v2 两份。这套对应 V1 的 `speech_delivery` 与 `speech_gate`，Live V2 用的是另一条管线，不要混用
- **其他 V1 引擎修复**：resume 连续性、隐私投影、自爆遗言、终局结算、娱乐规则

注意 `2026-07-15-privacy-audience-contract-v2-remediation-design.md` 名字里的 "v2" 指的是隐私契约的第二版，与 Live V2 无关。

### `reviews/`

`2026-07-20-liveness-panel-pilot` 是 V1 时代 PersonaRenderer 的盲评实验记录，作为历史证据保留。

### 顶层两份

- `run-05aa0b0f2b92-quality-remediation-plan.md`：单局质量复盘，P0 到 P3 的同源叙事。其中记录的功能开关默认值（发言质量重试、动作预算为 false）已与代码不符，现在两者默认都是 true
- `speech-realism-study-summary.md`：V1 的发言真实感实验复盘

## 仍然有效的部分

归档不等于全错。以下内容跨引擎有效，只是载体文档进了 archive：

- 规则快照冻结、revision 精确匹配这套契约，Live V2 同样遵守
- 隐私投影的产品意图（普通直播不含秘密信息）在 Live V2 准则第 13 节延续
- P0 到 P3 里对局质量问题的**现象描述**仍有参考价值，但**修复方案**都是针对 V1 引擎的
