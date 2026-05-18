# Frontend-Only Live Playback Pacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除后端执行节奏差异，让对局始终正常速度运行，并把直播播放速度统一收敛到前端 `1x` 正常语速和 `2x` 快速浏览两档。

**Architecture:** 后端删除 `event_pacing` 的存储、校验、返回和 sleep 路径，后台对局直接使用 `EventSink` 发布真实事件。前端删除创建页的“演示慢速”和 run 类型中的 `event_pacing`，在导播层以 `DirectorCue.durationMs` 表示 `1x` 正常语速时长，再由 `useLiveDirector()` 根据 `1 | 2` 计算有效播放时长。

**Tech Stack:** FastAPI、Pydantic、Python dataclass、Pytest、React、TypeScript、Vitest、React Testing Library、TanStack Query。

---

## 文件结构

- Modify: `apps/api/app/werewolf/live.py`
  - 移除 `EventPacingMode`、`validate_event_pacing`、`LiveGameRun.event_pacing`、summary 和 `run_created` payload 中的 `event_pacing`。
- Delete: `apps/api/app/werewolf/pacing.py`
  - 删除后端延迟策略模块；实现完成后不应再有 import。
- Modify: `apps/api/app/api/routes/games.py`
  - `CreateGameRunRequest` 移除 `event_pacing` 字段；create/resume/background 路径不再创建 `EventPacer`，也不再使用 `PacedEventSink`。
- Modify: `apps/api/tests/test_live.py`
  - 改写 registry 测试，断言 run summary 和初始事件不再包含 `event_pacing`。
- Delete: `apps/api/tests/test_werewolf_pacing.py`
  - 删除后端 pacing 单元测试。
- Modify: `apps/api/tests/test_games_api.py`
  - 改写 create run 和 background run 测试，验证旧 `event_pacing` 字段被忽略且不会触发 sleep。
- Modify: `apps/web/src/features/games/types.ts`
  - 删除 `EventPacingMode`，从 `GameRun` 和 `CreateGameRunRequest` 删除 `event_pacing`。
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
  - 删除 `eventPacing` state、`SelectField` import、演示慢速控件和提交字段。
- Modify: `apps/web/src/features/games/components/LiveStatusStrip.tsx`
  - 删除后端节奏标签映射，不再显示“快速执行/标准演示/慢速讲解”。
- Modify: `apps/web/src/features/games/hooks/useLiveDirector.ts`
  - 把 `LiveDirectorSpeed` 改为 `1 | 2`，保留 `1x` 默认值和最短展示时长。
- Modify: `apps/web/src/features/games/liveDirector.ts`
  - 把长文本 duration 调整为 `1x` 正常语速基准。
- Create: `apps/web/src/features/games/components/LiveDirectorControls.test.tsx`
  - 覆盖播放速度控件只提供 `1x` 和 `2x`。
- Modify: `apps/web/src/features/games/hooks/useLiveDirector.test.tsx`
  - 覆盖 `2x` 时长减半和 reset 回到 `1x`。
- Modify: `apps/web/src/features/games/liveDirector.test.ts`
  - 覆盖长文本按正常语速生成 `1x` duration。
- Modify: `apps/web/src/features/games/api/liveRunApi.test.ts`
  - 删除 response fixture 中的 `event_pacing`，断言 API 类型不再依赖该字段。
- Modify: `apps/web/src/pages/GamesPage.test.tsx`
  - 删除“演示慢速”控件断言，所有 create run payload 不再包含 `event_pacing`。
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`
  - 删除“快速执行”状态条断言，更新 run fixture 和播放速度选项断言。
- Modify: `apps/web/src/pages/GameHistoryPage.test.tsx`
  - 删除 run fixture 中遗留的 `event_pacing` 字段。
- Modify: `docs/superpowers/specs/2026-05-15-player-configuration-design.md`
  - 把示例请求中的 `event_pacing` 删除，避免新工作继续复制旧字段。
- Modify: `docs/superpowers/specs/2026-05-16-virtual-player-profiles-design.md`
  - 把示例请求中的 `event_pacing` 删除。

## Task 1: 后端 Registry 去掉 event_pacing

**Files:**
- Modify: `apps/api/tests/test_live.py`
- Modify: `apps/api/app/werewolf/live.py`

- [ ] **Step 1: 改写 registry 失败测试**

在 `apps/api/tests/test_live.py` 中移除 `import pytest`，并把 `test_registry_creates_run_with_initial_event` 后面的两个 pacing 测试替换为下面这个测试：

```python
def test_registry_summary_and_initial_event_do_not_include_event_pacing() -> None:
    registry = LiveRunRegistry()

    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **classic_rule_kwargs(),
    )

    summary = run.to_summary()

    assert "event_pacing" not in summary
    assert "event_pacing" not in run.events[0].payload
```

同时在 `test_registry_creates_run_with_initial_event` 中删除这三行：

```python
assert run.event_pacing == "off"
assert run.to_summary()["event_pacing"] == "off"
assert run.events[0].payload["event_pacing"] == "off"
```

- [ ] **Step 2: 运行 registry 测试确认失败**

Run:

```bash
pytest apps/api/tests/test_live.py -q
```

Expected: FAIL，错误应包含 `event_pacing` 仍存在，或 `LiveRunRegistry.create_run()` 仍接受/校验 pacing。

- [ ] **Step 3: 修改 `live.py` 移除 pacing 字段**

在 `apps/api/app/werewolf/live.py` 中删除：

```python
from app.werewolf.pacing import EventPacingMode, validate_event_pacing
```

删除 `LiveGameRun` 上的字段：

```python
event_pacing: EventPacingMode = "off"
```

从 `to_summary()` 返回值中删除：

```python
"event_pacing": self.event_pacing,
```

把 `LiveRunRegistry.create_run()` 签名中的参数：

```python
event_pacing: EventPacingMode = "off",
```

删掉，并删除函数开头的：

```python
validated_event_pacing = validate_event_pacing(event_pacing)
```

创建 `LiveGameRun(...)` 时删除：

```python
event_pacing=validated_event_pacing,
```

`run_created` payload 中删除：

```python
"event_pacing": validated_event_pacing,
```

- [ ] **Step 4: 跑 registry 测试确认通过**

Run:

```bash
pytest apps/api/tests/test_live.py -q
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/werewolf/live.py apps/api/tests/test_live.py
git commit -m "refactor: remove event pacing from live run registry"
```

## Task 2: 后端 API 和后台执行去掉 pacing sleep

**Files:**
- Modify: `apps/api/tests/test_games_api.py`
- Modify: `apps/api/app/api/routes/games.py`
- Delete: `apps/api/app/werewolf/pacing.py`
- Delete: `apps/api/tests/test_werewolf_pacing.py`

- [ ] **Step 1: 改写 create run API 测试**

在 `apps/api/tests/test_games_api.py` 中，把 `test_create_game_run_accepts_event_pacing` 替换为：

```python
def test_create_game_run_ignores_legacy_event_pacing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"seed": 21, "max_rounds": 1, "event_pacing": "turbo"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert "event_pacing" not in payload
    assert "event_pacing" not in captured[0]
```

删除整个 `test_create_game_run_rejects_unknown_event_pacing` 测试。

- [ ] **Step 2: 改写 background run 测试**

把 `test_run_game_in_background_paces_registry_and_engine_events` 替换为：

```python
def test_run_game_in_background_publishes_registry_and_engine_events_without_pacing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )

    def fake_run_game(*, event_sink, **kwargs: object) -> SimpleNamespace:
        event_sink.publish("phase_started", phase="night")
        return SimpleNamespace(winner="狼人阵营")

    monkeypatch.setattr("app.api.routes.games.run_game", fake_run_game)
    monkeypatch.setattr("app.api.routes.games.settings.werewolf_logs_dir", str(tmp_path))

    _run_game_in_background(
        run_id=run.run_id,
        registry=registry,
        session_id=run.session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id="classic_8",
    )

    assert [event.type for event in registry.events_after(run.run_id)] == [
        "run_created",
        "run_started",
        "phase_started",
        "game_completed",
    ]
```

如果文件中还有 `_resume_game_in_background(..., event_pacing="standard")` 的测试调用，把 `event_pacing` 参数删除。

- [ ] **Step 3: 运行 API 测试确认失败**

Run:

```bash
pytest apps/api/tests/test_games_api.py -q
```

Expected: FAIL，错误应指向 `event_pacing` 仍在 response/captured kwargs 中，或 `_run_game_in_background()` 签名仍要求该参数。

- [ ] **Step 4: 修改 routes imports 和 request schema**

在 `apps/api/app/api/routes/games.py` 中删除 import：

```python
from app.werewolf.pacing import EventPacer, EventPacingMode
```

从 `CreateGameRunRequest` 删除字段：

```python
event_pacing: EventPacingMode = "off"
```

- [ ] **Step 5: 修改 create run 和 resume run 调用**

在 `create_game_run()` 中，`registry.create_run(...)` 删除：

```python
event_pacing=request.event_pacing,
```

后台线程 kwargs 删除：

```python
"event_pacing": request.event_pacing,
```

在 `resume_game_run()` 中，`registry.create_run(...)` 删除：

```python
event_pacing="off",
```

后台线程 kwargs 删除：

```python
"event_pacing": "off",
```

- [ ] **Step 6: 修改 background 函数直接使用 EventSink**

把 `_run_game_in_background()` 签名中的参数删除：

```python
event_pacing: EventPacingMode,
```

删除函数体内：

```python
pacer = EventPacer(event_pacing)
pacer.wait("run_started")
```

把 `run_game(...)` 的 `event_sink` 参数改成：

```python
event_sink=EventSink(registry, run_id),
```

删除两个异常分支中的：

```python
pacer.wait("game_failed")
```

删除完成分支前的：

```python
pacer.wait("game_completed")
```

把 `_resume_game_in_background()` 签名中的参数删除：

```python
event_pacing: EventPacingMode,
```

删除函数体内：

```python
pacer = EventPacer(event_pacing)
pacer.wait("run_started")
```

把 `resume_game(...)` 的 `event_sink` 参数改成：

```python
event_sink=EventSink(registry, run_id),
```

删除两个异常分支中的：

```python
pacer.wait("game_failed")
```

删除完成分支前的：

```python
pacer.wait("game_completed")
```

删除整个 `PacedEventSink` 类。

- [ ] **Step 7: 删除 pacing 模块和测试**

Run:

```bash
rm apps/api/app/werewolf/pacing.py apps/api/tests/test_werewolf_pacing.py
```

- [ ] **Step 8: 确认后端没有 pacing 引用**

Run:

```bash
rg -n "event_pacing|EventPacer|EventPacingMode|PacedEventSink|werewolf\\.pacing" apps/api/app apps/api/tests
```

Expected: command exits with no matches.

- [ ] **Step 9: 跑后端相关测试**

Run:

```bash
pytest apps/api/tests/test_live.py apps/api/tests/test_games_api.py -q
```

Expected: PASS。

- [ ] **Step 10: Commit**

```bash
git add apps/api/app/api/routes/games.py apps/api/tests/test_games_api.py apps/api/app/werewolf/pacing.py apps/api/tests/test_werewolf_pacing.py
git commit -m "refactor: run live games without backend pacing"
```

## Task 3: 前端类型和创建表单移除演示慢速

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`
- Modify: `apps/web/src/features/games/api/liveRunApi.test.ts`
- Modify: `apps/web/src/pages/GameHistoryPage.test.tsx`

- [ ] **Step 1: 改写 GamesPage 创建表单结构测试**

在 `apps/web/src/pages/GamesPage.test.tsx` 中，把顶部控制台测试里的：

```ts
expect(
  within(consoleBar).getByRole("combobox", { name: "演示慢速" }),
).toBeInTheDocument();
```

替换为：

```ts
expect(
  within(consoleBar).queryByRole("combobox", { name: "演示慢速" }),
).not.toBeInTheDocument();
```

把所有 create run payload 断言中的：

```ts
event_pacing: "off",
```

和：

```ts
event_pacing: "standard",
```

删除。删除与选择“演示慢速”相关的交互：

```ts
await userEvent.selectOptions(
  await screen.findByRole("combobox", { name: "演示慢速" }),
  "standard",
);
```

新增一个明确断言到创建 payload 测试中：

```ts
expect(JSON.parse(String(fetchSpy.mock.calls[0]?.[1]?.body))).not.toHaveProperty(
  "event_pacing",
);
```

- [ ] **Step 2: 改写 API fixture 测试**

在 `apps/web/src/features/games/api/liveRunApi.test.ts` 中，删除所有 response fixture 的：

```ts
event_pacing: "standard",
```

```ts
event_pacing: "slow",
```

```ts
event_pacing: "off",
```

把：

```ts
expect(run.event_pacing).toBe("slow");
```

替换为：

```ts
expect("event_pacing" in run).toBe(false);
```

在 `apps/web/src/pages/GameHistoryPage.test.tsx` 中删除 fixture 内的：

```ts
event_pacing: "off",
```

- [ ] **Step 3: 运行前端相关测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx src/features/games/api/liveRunApi.test.ts src/pages/GameHistoryPage.test.tsx
```

Expected: FAIL，错误应指向“演示慢速”仍存在、payload 仍包含 `event_pacing` 或 TypeScript 类型仍声明该字段。

- [ ] **Step 4: 修改前端类型**

在 `apps/web/src/features/games/types.ts` 中删除：

```ts
export type EventPacingMode = "off" | "standard" | "slow";
```

从 `GameRun` 删除：

```ts
event_pacing: EventPacingMode;
```

从 `CreateGameRunRequest` 删除：

```ts
event_pacing?: EventPacingMode;
```

- [ ] **Step 5: 修改 CreateGameRunForm**

在 `apps/web/src/features/games/components/CreateGameRunForm.tsx` 中，从 UI import 删除 `SelectField`：

```ts
SelectField,
```

从 types import 删除 `EventPacingMode`：

```ts
EventPacingMode,
```

删除 state：

```ts
const [eventPacing, setEventPacing] = useState<EventPacingMode>("off");
```

提交 payload 删除：

```ts
event_pacing: eventPacing,
```

删除整个演示慢速控件：

```tsx
<div className="lobby-console-field lobby-console-field-pacing">
  <span className="lobby-console-field-label" id="event-pacing-label">
    演示慢速
  </span>
  <SelectField
    aria-labelledby="event-pacing-label"
    className="lobby-console-select"
    value={eventPacing}
    onChange={(event) =>
      setEventPacing(event.target.value as EventPacingMode)
    }
  >
    <option value="off">关闭</option>
    <option value="standard">标准演示</option>
    <option value="slow">慢速讲解</option>
  </SelectField>
</div>
```

- [ ] **Step 6: 跑前端创建/API 测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx src/features/games/api/liveRunApi.test.ts src/pages/GameHistoryPage.test.tsx
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/pages/GamesPage.test.tsx apps/web/src/features/games/api/liveRunApi.test.ts apps/web/src/pages/GameHistoryPage.test.tsx
git commit -m "refactor: remove backend pacing controls from lobby"
```

## Task 4: 前端导播速度改为 1x/2x

**Files:**
- Modify: `apps/web/src/features/games/hooks/useLiveDirector.ts`
- Modify: `apps/web/src/features/games/hooks/useLiveDirector.test.tsx`
- Modify: `apps/web/src/features/games/components/LiveDirectorControls.tsx`
- Create: `apps/web/src/features/games/components/LiveDirectorControls.test.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 改写 hook 速度测试**

在 `apps/web/src/features/games/hooks/useLiveDirector.test.tsx` 中，把 `setSpeed(1.5)` 测试段替换为：

```ts
act(() => {
  result.current.setSpeed(2);
});
expect(result.current.speed).toBe(2);
expect(result.current.effectiveDurationMs).toBe(500);
```

新增测试：

```ts
it("uses 2x speed by halving non-compressed cue duration", () => {
  const events = [
    event({ id: 1, type: "round_started", round: 1 }),
    event({ id: 2, type: "phase_started", round: 1, phase: "day" }),
  ];
  const { result } = renderHook(() => useLiveDirector(events));

  expect(result.current.speed).toBe(1);
  expect(result.current.effectiveDurationMs).toBe(2500);

  act(() => {
    result.current.setSpeed(2);
  });

  expect(result.current.speed).toBe(2);
  expect(result.current.effectiveDurationMs).toBe(1250);
});
```

如果 reset 测试不存在，新增：

```ts
it("resets speed to 1x when reset key changes", () => {
  const events = [
    event({ id: 1, type: "round_started", round: 1 }),
    event({ id: 2, type: "phase_started", round: 1, phase: "day" }),
  ];
  const { result, rerender } = renderHook(
    ({ resetKey }: { resetKey: string }) =>
      useLiveDirector(events, { resetKey }),
    { initialProps: { resetKey: "run-a" } },
  );

  act(() => {
    result.current.setSpeed(2);
  });
  expect(result.current.speed).toBe(2);

  rerender({ resetKey: "run-b" });

  expect(result.current.speed).toBe(1);
});
```

- [ ] **Step 2: 新建 controls 测试**

创建 `apps/web/src/features/games/components/LiveDirectorControls.test.tsx`：

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LiveDirectorControls } from "./LiveDirectorControls";

describe("LiveDirectorControls", () => {
  it("offers only 1x and 2x playback speed options", () => {
    const onSpeedChange = vi.fn();

    render(
      <LiveDirectorControls
        backlogCount={0}
        isPaused={false}
        onCatchUpToLatest={() => {}}
        onSpeedChange={onSpeedChange}
        onTogglePaused={() => {}}
        speed={1}
      />,
    );

    const select = screen.getByLabelText("播放速度");
    expect(screen.getByRole("option", { name: "1x" })).toHaveValue("1");
    expect(screen.getByRole("option", { name: "2x" })).toHaveValue("2");
    expect(screen.queryByRole("option", { name: "1.5x" })).not.toBeInTheDocument();

    fireEvent.change(select, { target: { value: "2" } });

    expect(onSpeedChange).toHaveBeenCalledWith(2);
  });
});
```

- [ ] **Step 3: 运行导播速度测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/hooks/useLiveDirector.test.tsx src/features/games/components/LiveDirectorControls.test.tsx
```

Expected: FAIL，错误应指向 `1.5x` 仍存在或 `LiveDirectorSpeed` 仍为 `1 | 1.5`。

- [ ] **Step 4: 修改 hook 速度类型**

在 `apps/web/src/features/games/hooks/useLiveDirector.ts` 中把：

```ts
export type LiveDirectorSpeed = 1 | 1.5;
```

改成：

```ts
export type LiveDirectorSpeed = 1 | 2;
```

保留 `setSpeedState(1)` 和 `durationForCue(cue, speed, isCatchingUp)` 的除法逻辑。

- [ ] **Step 5: 修改 controls 选项**

在 `apps/web/src/features/games/components/LiveDirectorControls.tsx` 中把：

```tsx
<option value="1.5">1.5x</option>
```

改成：

```tsx
<option value="2">2x</option>
```

- [ ] **Step 6: 更新 LiveGamePage 测试 fixture 和选项断言**

在 `apps/web/src/pages/LiveGamePage.test.tsx` 中删除 run fixture 里的：

```ts
event_pacing: "off",
```

把任何 `1.5x` 相关断言改成：

```ts
expect(screen.getByRole("option", { name: "2x" })).toBeInTheDocument();
expect(screen.queryByRole("option", { name: "1.5x" })).not.toBeInTheDocument();
```

- [ ] **Step 7: 跑导播速度和直播页测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/hooks/useLiveDirector.test.tsx src/features/games/components/LiveDirectorControls.test.tsx src/pages/LiveGamePage.test.tsx
```

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/games/hooks/useLiveDirector.ts apps/web/src/features/games/hooks/useLiveDirector.test.tsx apps/web/src/features/games/components/LiveDirectorControls.tsx apps/web/src/features/games/components/LiveDirectorControls.test.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat: use 1x and 2x live director speeds"
```

## Task 5: 1x 长文本时长改为正常语速基准

**Files:**
- Modify: `apps/web/src/features/games/liveDirector.ts`
- Modify: `apps/web/src/features/games/liveDirector.test.ts`

- [ ] **Step 1: 写长文本语速测试**

在 `apps/web/src/features/games/liveDirector.test.ts` 中新增：

```ts
it("uses normal speech pace for visible long text at 1x", () => {
  const message =
    "我现在给出完整发言，先说明昨晚信息，再解释投票理由，最后给出今天建议。";
  const cue = toDirectorCue(
    event({
      id: 9,
      type: "state_updated",
      actor: "李四",
      action: "debate",
      payload: {
        debate_entry: { speaker: "李四", message },
      },
    }),
  );

  expect(cue.body).toBe(`李四：${message}`);
  expect(cue.importance).toBe("key");
  expect(cue.compressible).toBe(false);
  expect(cue.durationMs).toBeGreaterThanOrEqual(9000);
  expect(cue.durationMs).toBeLessThanOrEqual(20000);
});

it("caps very long visible text duration", () => {
  const message = "重要发言".repeat(80);
  const cues = buildDirectorCues([
    event({
      id: 2,
      type: "model_request_started",
      actor: "张三",
      action: "debate",
      payload: { request_id: "req_long", model: "deepseek-chat" },
    }),
    event({
      id: 3,
      type: "model_response_delta",
      actor: "张三",
      action: "debate",
      payload: {
        request_id: "req_long",
        visible_text: message,
        is_public: true,
      },
    }),
  ]);

  expect(cues[0].durationMs).toBe(20000);
});
```

- [ ] **Step 2: 运行 liveDirector 测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveDirector.test.ts
```

Expected: FAIL，第一条测试应显示当前 `longTextDuration()` 时长过短或上限仍为 `12000`。

- [ ] **Step 3: 修改 longTextDuration 算法**

在 `apps/web/src/features/games/liveDirector.ts` 中，把：

```ts
function longTextDuration(text: string): number {
  return Math.min(12000, Math.max(6000, 3500 + text.length * 45));
}
```

替换为：

```ts
const NORMAL_CHARS_PER_SECOND = 4;
const NORMAL_WORDS_PER_MINUTE = 150;
const LONG_TEXT_LEAD_IN_MS = 1000;
const MIN_TEXT_DURATION_MS = 6000;
const MAX_TEXT_DURATION_MS = 20000;

function longTextDuration(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) {
    return MIN_TEXT_DURATION_MS;
  }

  const chineseCharacterCount = Array.from(trimmed).filter((char) =>
    /[\u3400-\u9fff]/u.test(char),
  ).length;
  const wordCount = trimmed.match(/[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*/g)?.length ?? 0;
  const chineseMs = (chineseCharacterCount / NORMAL_CHARS_PER_SECOND) * 1000;
  const wordMs = (wordCount / NORMAL_WORDS_PER_MINUTE) * 60_000;
  const estimatedMs = LONG_TEXT_LEAD_IN_MS + Math.max(chineseMs, wordMs);

  return Math.min(
    MAX_TEXT_DURATION_MS,
    Math.max(MIN_TEXT_DURATION_MS, Math.round(estimatedMs)),
  );
}
```

- [ ] **Step 4: 跑 liveDirector 测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveDirector.test.ts
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/games/liveDirector.ts apps/web/src/features/games/liveDirector.test.ts
git commit -m "feat: pace live director text at normal speech speed"
```

## Task 6: 直播状态条移除后端节奏展示

**Files:**
- Modify: `apps/web/src/features/games/components/LiveStatusStrip.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 改写状态条测试**

在 `apps/web/src/pages/LiveGamePage.test.tsx` 中，把：

```ts
expect(liveNavContext).toHaveTextContent("快速执行");
expect(liveNavContext).not.toHaveTextContent("节奏：快速执行");
```

替换为：

```ts
expect(liveNavContext).not.toHaveTextContent("快速执行");
expect(liveNavContext).not.toHaveTextContent("标准演示");
expect(liveNavContext).not.toHaveTextContent("慢速讲解");
expect(liveNavContext).not.toHaveTextContent("节奏：");
```

- [ ] **Step 2: 运行状态条测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: FAIL，状态条仍显示 `快速执行`。

- [ ] **Step 3: 修改 LiveStatusStrip**

在 `apps/web/src/features/games/components/LiveStatusStrip.tsx` 中删除：

```ts
const eventPacingLabels = {
  off: "快速执行",
  standard: "标准演示",
  slow: "慢速讲解",
} as const;
```

删除函数体内：

```ts
const eventPacingLabel =
  eventPacingLabels[run.event_pacing as keyof typeof eventPacingLabels] ??
  eventPacingLabels.off;
```

删除 nav 版本中的节奏 `<span>`：

```tsx
<span className="text-amber-200">
  <span aria-hidden="true" className="mr-2 leading-none">
    ⚡
  </span>
  {eventPacingLabel}
</span>
```

删除 panel 版本中的节奏文本：

```tsx
<span className="text-slate-400">节奏：{eventPacingLabel}</span>
```

- [ ] **Step 4: 跑直播页测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/games/components/LiveStatusStrip.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "refactor: remove backend pacing label from live status"
```

## Task 7: 清理文档示例和全局引用

**Files:**
- Modify: `docs/superpowers/specs/2026-05-15-player-configuration-design.md`
- Modify: `docs/superpowers/specs/2026-05-16-virtual-player-profiles-design.md`
- Inspect: `apps/api/app`, `apps/api/tests`, `apps/web/src`

- [ ] **Step 1: 清理两个 spec 示例**

在 `docs/superpowers/specs/2026-05-15-player-configuration-design.md` 和 `docs/superpowers/specs/2026-05-16-virtual-player-profiles-design.md` 中，把 JSON 示例里的这一行删除：

```json
"event_pacing": "standard",
```

- [ ] **Step 2: 全局搜索旧字段**

Run:

```bash
rg -n "event_pacing|EventPacer|EventPacingMode|演示慢速|标准演示|慢速讲解|快速执行|1\\.5x" apps/api/app apps/api/tests apps/web/src docs/superpowers/specs/2026-05-15-player-configuration-design.md docs/superpowers/specs/2026-05-16-virtual-player-profiles-design.md
```

Expected: no matches, except unrelated `1.5` references for sheriff vote weight, CSS spacing, and other non-playback content. If `1.5x` appears, remove it.

- [ ] **Step 3: 跑目标测试套件**

Run:

```bash
pytest apps/api/tests/test_live.py apps/api/tests/test_games_api.py -q
pnpm --dir apps/web test -- --run src/features/games/liveDirector.test.ts src/features/games/hooks/useLiveDirector.test.tsx src/features/games/components/LiveDirectorControls.test.tsx src/features/games/api/liveRunApi.test.ts src/pages/GamesPage.test.tsx src/pages/LiveGamePage.test.tsx src/pages/GameHistoryPage.test.tsx
pnpm --dir apps/web build
```

Expected: all commands PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-15-player-configuration-design.md docs/superpowers/specs/2026-05-16-virtual-player-profiles-design.md
git commit -m "docs: remove legacy event pacing examples"
```

## Task 8: 最终验证

**Files:**
- Inspect only.

- [ ] **Step 1: 后端搜索确认**

Run:

```bash
rg -n "event_pacing|EventPacer|EventPacingMode|PacedEventSink|werewolf\\.pacing" apps/api/app apps/api/tests
```

Expected: no matches.

- [ ] **Step 2: 前端播放速度搜索确认**

Run:

```bash
rg -n "1\\.5x|LiveDirectorSpeed = 1 \\| 1\\.5|演示慢速|标准演示|慢速讲解|快速执行|event_pacing" apps/web/src
```

Expected: no matches. If `1.5` appears only as sheriff vote weight or CSS spacing under a broader search, leave it alone.

- [ ] **Step 3: 完整相关测试**

Run:

```bash
pytest apps/api/tests/test_live.py apps/api/tests/test_games_api.py -q
pnpm --dir apps/web test -- --run src/features/games/liveDirector.test.ts src/features/games/hooks/useLiveDirector.test.tsx src/features/games/components/LiveDirectorControls.test.tsx src/features/games/api/liveRunApi.test.ts src/pages/GamesPage.test.tsx src/pages/LiveGamePage.test.tsx src/pages/GameHistoryPage.test.tsx
pnpm --dir apps/web build
```

Expected: PASS.

- [ ] **Step 4: Commit verification-only cleanup if needed**

If Step 1 or Step 2 finds stale references and you remove them, commit those edits:

```bash
git add apps/api apps/web docs
git commit -m "chore: clean up legacy pacing references"
```

If there are no edits after verification, do not create a commit.

## Self-Review

- Spec coverage: covered backend normal-speed execution, removal of lobby slow controls, frontend-only `1x/2x` playback speed, normal speech timing, status strip cleanup, compatibility with old `event_pacing` input, and regression testing.
- Placeholder scan: no placeholder sections or incomplete steps.
- Type consistency: `LiveDirectorSpeed` is consistently `1 | 2`; `event_pacing` is removed from backend run summaries and frontend `GameRun`/`CreateGameRunRequest`.
- Scope check: this is one coherent migration from backend pacing to frontend playback pacing; no unrelated rules, model, avatar, or layout work is included.
