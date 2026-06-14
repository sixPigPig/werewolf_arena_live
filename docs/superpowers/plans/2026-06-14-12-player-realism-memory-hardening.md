# 12 Player Realism Memory Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent private model thoughts from leaking into live/replay, preserve long-lived public facts, and reduce obvious machine-like behavior in 12 player seer-witch-hunter-idiot games.

**Architecture:** Split model memory into private per-player summaries and deterministic public round briefs, then add a public fact ledger that feeds every model action. Layer lightweight quality guards and endgame context into prompts without changing core role rules or victory conditions. Frontend live/replay surfaces read only public summaries and fact-driven narrative fields by default.

**Tech Stack:** Python dataclasses, pytest, and FastAPI-side replay serialization in `apps/api`; React/TypeScript, Vitest, and existing live director/replay components in `apps/web`.

---

## File Structure

- Modify `apps/api/app/werewolf/models.py`: add public facts, private summaries, and public summary fields.
- Modify `apps/api/app/werewolf/checkpoint.py`: load new fields when resuming and keep old logs compatible.
- Modify `apps/api/app/werewolf/engine.py`: record public facts, keep model summaries private, publish public round briefs, add endgame context, and emit action quality warnings.
- Create `apps/api/app/werewolf/public_facts.py`: focused helpers for public fact formatting and prompt compression.
- Create `apps/api/app/werewolf/action_quality.py`: focused helpers for stage mismatch and repeated-template warnings.
- Modify `apps/api/app/werewolf/prompts_zh.py`: render public facts and endgame context; tighten summary, witch, hunter, and public speech instructions.
- Modify `apps/api/app/werewolf/replay_playback.py`: include new public fields and keep old replay payloads safe.
- Modify `apps/api/tests/test_werewolf_runner.py`: cover private summary isolation, public fact propagation, and endgame context.
- Modify `apps/api/tests/test_werewolf_resume.py`: cover checkpoint compatibility for new fields.
- Modify `apps/api/tests/test_werewolf_lm.py`: cover prompt rendering and action instructions.
- Create `apps/api/tests/test_werewolf_action_quality.py`: cover quality warning helpers.
- Create `apps/api/tests/test_werewolf_public_facts.py`: cover public fact compression.
- Modify `apps/web/src/features/games/types.ts`: add `public_facts`, `public_summary`, and optional `private_summaries` types.
- Modify `apps/web/src/features/games/api/adapters.ts`: normalize new replay fields and keep debug items explicit about private memory.
- Modify `apps/web/src/features/games/liveDirector.ts`: render `public_summary`, ignore `private_summaries`, and explain sheriff-election interruption.
- Modify `apps/web/src/features/games/liveNarrative.ts`: use public summary and self-explosion continuation copy.
- Modify `apps/web/src/features/games/components/SummaryStrip.tsx`: render public summaries only.
- Modify `apps/web/src/features/games/components/DayPhase.tsx`: pass public summaries to SummaryStrip.
- Modify `apps/web/src/features/games/liveDirector.test.ts`, `apps/web/src/features/games/liveNarrative.test.ts`, `apps/web/src/features/games/api/adapters.test.ts`, and `apps/web/src/features/games/components/DayPhase.test.tsx`: cover no-leak and narrative behavior.
- Create `apps/api/app/werewolf/evaluator.py`: offline replay evaluator for the observed failure modes.
- Create `apps/api/tests/test_werewolf_evaluator.py`: fixture-based evaluator coverage.

---

### Task 1: Private Summary Boundary

**Files:**
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/checkpoint.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/replay_playback.py`
- Test: `apps/api/tests/test_werewolf_runner.py`
- Test: `apps/api/tests/test_werewolf_resume.py`

- [ ] **Step 1: Write failing backend summary isolation tests**

Append to `apps/api/tests/test_werewolf_runner.py`:

```python
def test_model_summaries_are_private_and_public_brief_is_safe() -> None:
    round_state = RoundState(number=4, players=["10号玩家", "12号玩家"])
    round_state.private_summaries["10号玩家"] = (
        "本轮我作为10号狼人，准备夜晚刀9号。"
    )
    round_state.public_summary = "第4轮：1号玩家被放逐，票型记录已更新。"

    payload = round_state.to_dict()

    assert payload["public_summary"] == "第4轮：1号玩家被放逐，票型记录已更新。"
    assert payload["summaries"] == {}
    assert payload["private_summaries"]["10号玩家"] == (
        "本轮我作为10号狼人，准备夜晚刀9号。"
    )


def test_summary_phase_does_not_publish_private_summaries() -> None:
    class CapturingSink:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def publish(self, event_type: str, **kwargs: object) -> None:
            self.events.append({"type": event_type, **kwargs})

    sink = CapturingSink()
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="summary_test",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260614,
        rule_set=rule_set,
    )
    provider = FakeProvider(
        [
            {"reasoning": "私密复盘", "summary": "我作为狼人继续隐藏身份。"}
            for _ in state.players
        ]
    )
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=1,
        rule_set=rule_set,
        event_sink=sink,
        rng=random.Random(1),
    )
    round_state = RoundState(number=1, players=[player.name for player in state.players])
    round_log = RoundLog(number=1)
    active_players = [player.name for player in state.players]

    engine._run_summaries(round_state, round_log, active_players)

    summary_events = [
        event
        for event in sink.events
        if event["type"] == "state_updated" and event.get("phase") == "summary"
    ]
    assert summary_events
    assert all(
        "private_summaries" not in (event.get("payload") or {})
        for event in summary_events
    )
    assert all("我作为狼人" not in str(event.get("payload")) for event in summary_events)
```

Append to `apps/api/tests/test_werewolf_resume.py`:

```python
def test_round_state_from_dict_defaults_new_summary_fields() -> None:
    round_state = round_state_from_dict({"number": 1, "players": ["1号玩家"]})

    assert round_state.public_summary == ""
    assert round_state.private_summaries == {}
```

- [ ] **Step 2: Run failing backend tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_model_summaries_are_private_and_public_brief_is_safe \
  tests/test_werewolf_runner.py::test_summary_phase_does_not_publish_private_summaries \
  tests/test_werewolf_resume.py::test_round_state_from_dict_defaults_new_summary_fields \
  -q
```

Expected: FAIL because `private_summaries` and `public_summary` do not exist and `_run_summaries()` publishes full summaries.

- [ ] **Step 3: Add summary fields to RoundState**

In `apps/api/app/werewolf/models.py`, add fields after `summaries`:

```python
    private_summaries: dict[str, str] = field(default_factory=dict)
    public_summary: str = ""
```

Update `RoundState.to_dict()` near `summaries`:

```python
            "summaries": self.summaries,
            "private_summaries": self.private_summaries,
            "public_summary": self.public_summary,
```

- [ ] **Step 4: Load new summary fields from checkpoints**

In `apps/api/app/werewolf/checkpoint.py`, update `round_state_from_dict()` where `RoundState(...)` is constructed:

```python
        summaries=copy.deepcopy(data.get("summaries", {})),
        private_summaries=copy.deepcopy(data.get("private_summaries", {})),
        public_summary=str(data.get("public_summary") or ""),
```

- [ ] **Step 5: Generate public round brief and stop publishing private summaries**

In `apps/api/app/werewolf/engine.py`, add a helper near `_run_summaries()`:

```python
    def _public_round_brief(self, round_state: RoundState) -> str:
        parts: list[str] = [f"第{round_state.number}轮"]
        if round_state.night_deaths:
            deaths = "、".join(death.player for death in round_state.night_deaths)
            parts.append(f"夜晚{deaths}出局")
        if round_state.werewolf_self_exploded:
            parts.append(f"{round_state.werewolf_self_exploded}自爆，白天结束")
        if round_state.exiled:
            parts.append(f"{round_state.exiled}被放逐")
        if round_state.hunter_shot:
            parts.append(f"猎人带走{round_state.hunter_shot}")
        if round_state.idiot_revealed:
            parts.append(f"{round_state.idiot_revealed}翻牌免死")
        if len(parts) == 1:
            parts.append("没有公开出局")
        return "；".join(parts) + "。"
```

Change `_run_summaries()` so model summaries are private and payload is safe:

```python
            if isinstance(summary, str) and summary:
                round_state.private_summaries[name] = summary
                player.add_observation(f"第{round_state.number}轮总结：{summary}")
            round_log.summaries.append(action_log)

        round_state.public_summary = self._public_round_brief(round_state)
        self._publish_state_updated(
            round_state=round_state,
            phase="summary",
            action="summarize",
            payload={"public_summary": round_state.public_summary},
        )
```

Remove the per-player `state_updated` publish inside the summary loop.

- [ ] **Step 6: Keep replay playback safe**

In `apps/api/app/werewolf/replay_playback.py`, where round payloads are normalized, include:

```python
        "public_summary": str(round_state.get("public_summary") or ""),
        "private_summaries": _dict_or_empty(round_state.get("private_summaries")),
```

Keep existing `summaries` normalization for legacy files. Do not map `private_summaries` into `summaries`.

- [ ] **Step 7: Run backend summary tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_model_summaries_are_private_and_public_brief_is_safe \
  tests/test_werewolf_runner.py::test_summary_phase_does_not_publish_private_summaries \
  tests/test_werewolf_resume.py::test_round_state_from_dict_defaults_new_summary_fields \
  -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/werewolf/models.py \
  apps/api/app/werewolf/checkpoint.py \
  apps/api/app/werewolf/engine.py \
  apps/api/app/werewolf/replay_playback.py \
  apps/api/tests/test_werewolf_runner.py \
  apps/api/tests/test_werewolf_resume.py
git commit -m "fix: keep werewolf summaries private"
```

---

### Task 2: Public Fact Ledger

**Files:**
- Create: `apps/api/app/werewolf/public_facts.py`
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/checkpoint.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/prompts_zh.py`
- Test: `apps/api/tests/test_werewolf_public_facts.py`
- Test: `apps/api/tests/test_werewolf_runner.py`
- Test: `apps/api/tests/test_werewolf_lm.py`

- [ ] **Step 1: Write failing public fact tests**

Create `apps/api/tests/test_werewolf_public_facts.py`:

```python
from app.werewolf.public_facts import PublicFact, compressed_public_facts


def test_compressed_public_facts_keeps_key_claims_and_recent_events() -> None:
    facts = [
        PublicFact(round_number=1, category="claim", text="7号玩家警上自称预言家，报3号玩家为好人。"),
        PublicFact(round_number=2, category="claim", text="7号玩家警上声明6号玩家为好人。"),
        PublicFact(round_number=3, category="death", text="7号玩家夜晚出局，将警徽交给3号玩家。"),
        PublicFact(round_number=4, category="vote", text="第4轮票型：1号玩家->6号玩家；6号玩家->1号玩家。"),
    ]

    lines = compressed_public_facts(facts, max_lines=3)

    assert "7号玩家警上声明6号玩家为好人。" in lines
    assert "第4轮票型" in "\n".join(lines)
    assert len(lines) == 3
```

Append to `apps/api/tests/test_werewolf_lm.py`:

```python
def test_prompt_renders_public_facts() -> None:
    prompt, _schema = build_prompt(
        "debate",
        {
            **_world_state_for_special_action("村民", ""),
            "public_facts": ["7号玩家警上声明6号玩家为好人。"],
        },
    )

    assert "公开事实记录" in prompt
    assert "7号玩家警上声明6号玩家为好人。" in prompt
```

Append to `apps/api/tests/test_werewolf_runner.py`:

```python
def test_world_state_includes_public_facts_for_late_day_actions() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="facts_test",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260614,
        rule_set=rule_set,
    )
    state.public_facts.append(
        {
            "round_number": 2,
            "category": "claim",
            "text": "7号玩家警上声明6号玩家为好人。",
        }
    )
    engine = GameEngine(
        state=state,
        provider=FakeProvider([]),
        max_rounds=1,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    players = state.player_by_name()
    round_state = RoundState(number=4, players=[player.name for player in state.players])

    world_state = engine._world_state(players["1号玩家"], [], round_state)

    assert "7号玩家警上声明6号玩家为好人。" in world_state["public_facts"]
```

- [ ] **Step 2: Run failing public fact tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_public_facts.py \
  tests/test_werewolf_lm.py::test_prompt_renders_public_facts \
  tests/test_werewolf_runner.py::test_world_state_includes_public_facts_for_late_day_actions \
  -q
```

Expected: FAIL because public fact helpers and model fields do not exist.

- [ ] **Step 3: Create public fact helper**

Create `apps/api/app/werewolf/public_facts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PINNED_CATEGORIES = {"claim", "sheriff", "death", "vote", "reveal"}


@dataclass(frozen=True)
class PublicFact:
    round_number: int
    category: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "category": self.category,
            "text": self.text,
        }


def public_fact_from_dict(data: dict[str, Any]) -> PublicFact:
    return PublicFact(
        round_number=int(data.get("round_number") or 0),
        category=str(data.get("category") or "event"),
        text=str(data.get("text") or ""),
    )


def compressed_public_facts(
    facts: list[PublicFact],
    *,
    max_lines: int = 18,
) -> list[str]:
    if max_lines <= 0:
        return []

    pinned = [fact for fact in facts if fact.category in PINNED_CATEGORIES]
    recent = facts[-max_lines:]
    merged: list[PublicFact] = []
    seen: set[tuple[int, str, str]] = set()
    for fact in [*pinned, *recent]:
        key = (fact.round_number, fact.category, fact.text)
        if key in seen or not fact.text:
            continue
        seen.add(key)
        merged.append(fact)
    return [fact.text for fact in merged[-max_lines:]]
```

- [ ] **Step 4: Add public facts to GameState serialization**

In `apps/api/app/werewolf/models.py`, add to `GameState`:

```python
    public_facts: list[dict[str, Any]] = field(default_factory=list)
```

Add to `GameState.to_dict()`:

```python
            "public_facts": self.public_facts,
```

In `apps/api/app/werewolf/checkpoint.py`, update `game_state_from_dict()`:

```python
        public_facts=copy.deepcopy(data.get("public_facts", [])),
```

- [ ] **Step 5: Render public facts in prompts**

In `apps/api/app/werewolf/prompts_zh.py`, add `_render_public_facts()` after `_render_observations()`:

```python
def _render_public_facts(world_state: dict[str, Any]) -> str:
    facts = world_state.get("public_facts") or []
    if not facts:
        return "公开事实记录：暂无。"
    return "公开事实记录：\n" + "\n".join(f"- {fact}" for fact in facts)
```

Add it to `build_prompt()` sections after observations:

```python
        _render_public_facts(world_state),
```

- [ ] **Step 6: Feed compressed public facts into world state**

In `apps/api/app/werewolf/engine.py`, import helpers:

```python
from app.werewolf.public_facts import PublicFact, compressed_public_facts, public_fact_from_dict
```

Add methods near `_world_state()`:

```python
    def _add_public_fact(self, round_number: int, category: str, text: str) -> None:
        self.state.public_facts.append(
            PublicFact(
                round_number=round_number,
                category=category,
                text=text,
            ).to_dict()
        )

    def _public_fact_lines(self) -> list[str]:
        facts = [public_fact_from_dict(item) for item in self.state.public_facts]
        return compressed_public_facts(facts)
```

Update `_world_state()`:

```python
            "public_facts": self._public_fact_lines(),
```

- [ ] **Step 7: Record key public facts from game flow**

In `_resolve_werewolf_self_explosion()`, after `_announce(...)`:

```python
        self._add_public_fact(
            round_state.number,
            "reveal",
            f"第{round_state.number}轮：{wolf}自爆为狼人，白天立即结束。",
        )
```

In `_elect_sheriff()`, after `_announce(...)`:

```python
        self._add_public_fact(
            round_state.number,
            "sheriff",
            f"第{round_state.number}轮：{sheriff}当选警长，投票计为{self.rule_set.sheriff_vote_weight:g}票。",
        )
```

In `_run_sheriff_election_if_needed()`, after appending a sheriff speech:

```python
            self._add_public_fact(
                round_state.number,
                "claim",
                f"第{round_state.number}轮警上发言：{name}：{message}",
            )
```

In `_run_voting()` caller after `round_state.votes.append(votes)`:

```python
        self._add_public_fact(
            round_state.number,
            "vote",
            "第"
            f"{round_state.number}轮票型："
            + "；".join(f"{voter}->{target}" for voter, target in votes.items()),
        )
```

In `_finish_deferred_night_deaths_if_needed()` and `_run_night_phase()` after night death announcement, record:

```python
            self._add_public_fact(
                round_state.number,
                "death",
                f"第{round_state.number}轮：夜晚，{eliminated_names}出局。",
            )
```

- [ ] **Step 8: Run public fact tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_public_facts.py \
  tests/test_werewolf_lm.py::test_prompt_renders_public_facts \
  tests/test_werewolf_runner.py::test_world_state_includes_public_facts_for_late_day_actions \
  -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/api/app/werewolf/public_facts.py \
  apps/api/app/werewolf/models.py \
  apps/api/app/werewolf/checkpoint.py \
  apps/api/app/werewolf/engine.py \
  apps/api/app/werewolf/prompts_zh.py \
  apps/api/tests/test_werewolf_public_facts.py \
  apps/api/tests/test_werewolf_runner.py \
  apps/api/tests/test_werewolf_lm.py
git commit -m "feat: add public fact ledger"
```

---

### Task 3: Endgame Context And Role-Specific Prompting

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/prompts_zh.py`
- Test: `apps/api/tests/test_werewolf_lm.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing prompt tests**

Append to `apps/api/tests/test_werewolf_lm.py`:

```python
def test_prompt_renders_endgame_context() -> None:
    prompt, _schema = build_prompt(
        "debate",
        {
            **_world_state_for_special_action("村民", ""),
            "endgame_context": [
                "当前存活 4 人，公开已出 3 名狼人，可能只剩 1 狼。",
                "本轮错误放逐可能导致狼人夜晚获胜。",
            ],
        },
    )

    assert "残局压力" in prompt
    assert "本轮错误放逐可能导致狼人夜晚获胜。" in prompt


def test_hunter_prompt_requires_candidate_comparison() -> None:
    prompt, _schema = build_prompt(
        "hunter_shoot",
        _world_state_for_special_action("猎人", "10号玩家、12号玩家、不发动技能"),
    )

    assert "候选嫌疑对比" in prompt
    assert "随机" in prompt


def test_witch_poison_prompt_requires_reason_to_hold_poison() -> None:
    prompt, _schema = build_prompt(
        "witch_poison",
        _world_state_for_special_action("女巫", "10号玩家、不使用毒药"),
    )

    assert "如果不使用毒药" in prompt
    assert "保留毒药仍有收益" in prompt
```

Append to `apps/api/tests/test_werewolf_runner.py`:

```python
def test_world_state_marks_four_player_endgame_pressure() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="endgame_test",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260614,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=FakeProvider([]),
        max_rounds=1,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    players = state.player_by_name()
    active_players = ["6号玩家", "9号玩家", "10号玩家", "12号玩家"]
    round_state = RoundState(number=5, players=active_players)
    for player in state.players:
        player.gamestate.current_players = active_players

    world_state = engine._world_state(players["6号玩家"], [], round_state)

    assert any("当前存活 4 人" in line for line in world_state["endgame_context"])
    assert any("错误放逐" in line for line in world_state["endgame_context"])
```

- [ ] **Step 2: Run failing endgame tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_prompt_renders_endgame_context \
  tests/test_werewolf_lm.py::test_hunter_prompt_requires_candidate_comparison \
  tests/test_werewolf_lm.py::test_witch_poison_prompt_requires_reason_to_hold_poison \
  tests/test_werewolf_runner.py::test_world_state_marks_four_player_endgame_pressure \
  -q
```

Expected: FAIL because endgame context is not rendered and role instructions are too loose.

- [ ] **Step 3: Add endgame context to engine world state**

In `apps/api/app/werewolf/engine.py`, add helper:

```python
    def _endgame_context(self, active_players: list[str]) -> list[str]:
        players_by_name = self.state.player_by_name()
        living_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        revealed_wolves = [
            player.name
            for player in self.state.players
            if self._is_werewolf(player) and player.revealed_role and player.name not in active_players
        ]
        lines = [
            f"当前存活 {len(active_players)} 人，公开已出 {len(revealed_wolves)} 名狼人。",
        ]
        if 0 < len(living_wolves) <= 1 and len(active_players) <= 4:
            lines.append("本轮错误放逐可能导致狼人夜晚获胜。")
        if self.rule_set.win_condition == WIN_CONDITION_SLAUGHTER_SIDE:
            living_gods = [
                name
                for name in active_players
                if role_category(self.rule_set, players_by_name[name].role) == ROLE_CATEGORY_GOD
            ]
            living_civilians = [
                name
                for name in active_players
                if role_category(self.rule_set, players_by_name[name].role)
                == ROLE_CATEGORY_CIVILIAN
            ]
            lines.append(
                f"屠边局当前存活神职 {len(living_gods)} 人、平民 {len(living_civilians)} 人。"
            )
        return lines
```

Update `_world_state()`:

```python
            "endgame_context": self._endgame_context(active_players),
```

- [ ] **Step 4: Render endgame context in prompts**

In `apps/api/app/werewolf/prompts_zh.py`, add:

```python
def _render_endgame_context(world_state: dict[str, Any]) -> str:
    lines = world_state.get("endgame_context") or []
    if not lines:
        return ""
    return "残局压力：\n" + "\n".join(f"- {line}" for line in lines)
```

Add this to `build_prompt()` after public facts:

```python
        _render_endgame_context(world_state),
```

- [ ] **Step 5: Tighten role instructions**

Replace the `witch_poison` instruction branch with:

```python
    if action == "witch_poison":
        return (
            "行动：女巫夜晚毒药。\n"
            f"候选人：{options}。\n"
            "你可以选择一名玩家使用毒药，或选择不使用毒药。"
            "如果不使用毒药，必须说明保留毒药仍有收益，不能只说信息不足。"
            "结合公开事实、票型和警徽流判断。被毒死的猎人不能开枪。"
            "输出字段 reasoning 和 poison。"
        )
```

Replace the `hunter_shoot` instruction branch with:

```python
    if action == "hunter_shoot":
        return (
            "行动：猎人死亡开枪。\n"
            f"候选人：{options}。\n"
            "你可以选择一名存活玩家带走，或选择不发动技能。"
            "必须给出候选嫌疑对比；不能只因为信息不足就随机开枪。"
            "结合公开事实、发言、票型和阵营目标做判断。输出字段 reasoning 和 shoot。"
        )
```

Replace the `debate` instruction branch with:

```python
    if action == "debate":
        return (
            "行动：白天公开发言。\n"
            "如果你是狼人，要误导局势、转移怀疑、保护队友；如果你是好人，要寻找矛盾、提出怀疑并推动团队协作。\n"
            "发言必须引用至少一条公开事实、票型或前置位发言，不要只复述别人结论。\n"
            "发言必须是中文，简洁、有策略、像真实玩家。输出字段 reasoning 和 say。"
        )
```

- [ ] **Step 6: Run endgame tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_prompt_renders_endgame_context \
  tests/test_werewolf_lm.py::test_hunter_prompt_requires_candidate_comparison \
  tests/test_werewolf_lm.py::test_witch_poison_prompt_requires_reason_to_hold_poison \
  tests/test_werewolf_runner.py::test_world_state_marks_four_player_endgame_pressure \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/engine.py \
  apps/api/app/werewolf/prompts_zh.py \
  apps/api/tests/test_werewolf_lm.py \
  apps/api/tests/test_werewolf_runner.py
git commit -m "feat: add endgame pressure prompts"
```

---

### Task 4: Stage Consistency Warnings

**Files:**
- Create: `apps/api/app/werewolf/action_quality.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Test: `apps/api/tests/test_werewolf_action_quality.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing action quality tests**

Create `apps/api/tests/test_werewolf_action_quality.py`:

```python
from app.werewolf.action_quality import action_quality_warnings


def test_sheriff_speech_warns_when_player_announces_withdrawal() -> None:
    warnings = action_quality_warnings(
        action="sheriff_speech",
        text="我是3号，上警竞选警长。我退水，警徽投给8号。",
    )

    assert "sheriff_speech_mentions_withdraw" in warnings


def test_sheriff_speech_warns_on_conflicting_badge_goal() -> None:
    warnings = action_quality_warnings(
        action="sheriff_speech",
        text="我认8号真预言家。希望大家把警徽投给我。",
    )

    assert "sheriff_speech_conflicting_badge_goal" in warnings


def test_endgame_warning_for_tomorrow_without_pressure() -> None:
    warnings = action_quality_warnings(
        action="debate",
        text="今天先出6号，如果他是好人，明天再看情况。",
        endgame=True,
    )

    assert "endgame_tomorrow_without_pressure" in warnings
```

Append to `apps/api/tests/test_werewolf_runner.py`:

```python
def test_action_quality_warning_event_is_published_for_stage_mismatch() -> None:
    class CapturingSink:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def publish(self, event_type: str, **kwargs: object) -> None:
            self.events.append({"type": event_type, **kwargs})

    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="quality_test",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260614,
        rule_set=rule_set,
    )
    sink = CapturingSink()
    engine = GameEngine(
        state=state,
        provider=FakeProvider([]),
        max_rounds=1,
        rule_set=rule_set,
        event_sink=sink,
        rng=random.Random(1),
    )
    round_state = RoundState(number=2, players=[player.name for player in state.players])

    engine._publish_action_quality_warnings(
        round_state=round_state,
        phase="day",
        actor="3号玩家",
        action="sheriff_speech",
        text="我退水，警徽投给8号。",
    )

    warning_events = [event for event in sink.events if event["type"] == "action_quality_warning"]
    assert warning_events
    assert warning_events[0]["payload"]["warnings"] == ["sheriff_speech_mentions_withdraw"]
```

- [ ] **Step 2: Run failing action quality tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_action_quality.py \
  tests/test_werewolf_runner.py::test_action_quality_warning_event_is_published_for_stage_mismatch \
  -q
```

Expected: FAIL because helper and publisher do not exist.

- [ ] **Step 3: Create action quality helper**

Create `apps/api/app/werewolf/action_quality.py`:

```python
from __future__ import annotations


def action_quality_warnings(
    *,
    action: str,
    text: str,
    endgame: bool = False,
) -> list[str]:
    warnings: list[str] = []
    normalized = text.replace(" ", "")

    if action == "sheriff_speech" and "退水" in normalized:
        warnings.append("sheriff_speech_mentions_withdraw")

    if action == "sheriff_speech":
        recognizes_other = "认" in normalized and "真预" in normalized
        asks_badge_for_self = "警徽投给我" in normalized or "把警徽投给我" in normalized
        if recognizes_other and asks_badge_for_self:
            warnings.append("sheriff_speech_conflicting_badge_goal")

    if endgame and action == "debate":
        mentions_tomorrow = "明天再" in normalized or "下一轮" in normalized
        mentions_pressure = "不能出错" in normalized or "直接输" in normalized or "轮次" in normalized
        if mentions_tomorrow and not mentions_pressure:
            warnings.append("endgame_tomorrow_without_pressure")

    return warnings
```

- [ ] **Step 4: Publish warnings from engine**

In `apps/api/app/werewolf/engine.py`, import:

```python
from app.werewolf.action_quality import action_quality_warnings
```

Add method near `_publish_state_updated()`:

```python
    def _publish_action_quality_warnings(
        self,
        *,
        round_state: RoundState,
        phase: str,
        actor: str,
        action: str,
        text: str,
    ) -> None:
        warnings = action_quality_warnings(
            action=action,
            text=text,
            endgame=len(round_state.players) <= 4,
        )
        if not warnings:
            return
        self._publish(
            "action_quality_warning",
            round_number=round_state.number,
            phase=phase,
            actor=actor,
            action=action,
            payload={"warnings": warnings, "text": text},
        )
```

Call it after successful public speech actions:

```python
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="day",
                actor=name,
                action=ACTION_SHERIFF_SPEECH,
                text=message,
            )
```

and in `_run_debate_phase()` after `message` is validated:

```python
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="day",
                actor=speaker,
                action=ACTION_DEBATE,
                text=message,
            )
```

- [ ] **Step 5: Run action quality tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_action_quality.py \
  tests/test_werewolf_runner.py::test_action_quality_warning_event_is_published_for_stage_mismatch \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/action_quality.py \
  apps/api/app/werewolf/engine.py \
  apps/api/tests/test_werewolf_action_quality.py \
  apps/api/tests/test_werewolf_runner.py
git commit -m "feat: flag stage consistency warnings"
```

---

### Task 5: Frontend Public Summary And Sheriff Interruption Narrative

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/api/adapters.ts`
- Modify: `apps/web/src/features/games/liveDirector.ts`
- Modify: `apps/web/src/features/games/liveNarrative.ts`
- Modify: `apps/web/src/features/games/components/SummaryStrip.tsx`
- Modify: `apps/web/src/features/games/components/DayPhase.tsx`
- Test: `apps/web/src/features/games/liveDirector.test.ts`
- Test: `apps/web/src/features/games/liveNarrative.test.ts`
- Test: `apps/web/src/features/games/api/adapters.test.ts`
- Test: `apps/web/src/features/games/components/DayPhase.test.tsx`

- [ ] **Step 1: Write failing frontend tests**

Append to `apps/web/src/features/games/liveDirector.test.ts`:

```typescript
it("uses public_summary and ignores private summary payloads", () => {
  const event = liveEvent({
    type: "state_updated",
    phase: "summary",
    action: "summarize",
    payload: {
      public_summary: "第4轮：1号玩家被放逐。",
      private_summaries: {
        "10号玩家": "我作为10号狼人，准备夜晚刀9号。",
      },
      summaries: {
        "10号玩家": "我作为10号狼人，准备夜晚刀9号。",
      },
    },
  });

  const card = eventToDirectorCard(event);

  expect(card?.body).toContain("第4轮：1号玩家被放逐。");
  expect(card?.body).not.toContain("10号狼人");
  expect(card?.body).not.toContain("刀9号");
});
```

Append to `apps/web/src/features/games/liveNarrative.test.ts`:

```typescript
it("explains sheriff election continuation after first pre-election self explosion", () => {
  const item = narrativeItemForEvent(
    liveEvent({
      type: "state_updated",
      phase: "day",
      action: "werewolf_self_explosion",
      actor: "4号玩家",
      payload: {
        werewolf_self_exploded: "4号玩家",
        sheriff_election_pending: true,
        sheriff_badge_lost: false,
        sheriff_badge_lost_reason: "首爆中断警长竞选",
      },
    }),
  );

  expect(item?.body).toContain("中断警长竞选");
  expect(item?.body).toContain("次日继续竞选");
});
```

Append to `apps/web/src/features/games/api/adapters.test.ts`:

```typescript
it("normalizes public summary without exposing private summaries as round summaries", () => {
  const replay = adaptGameReplay({
    session_id: "game_summary",
    players: [],
    winner: "",
    rule_set: null,
    rounds: [
      {
        number: 1,
        players: [],
        night_deaths: [],
        day_deaths: [],
        debate: [],
        votes: [],
        summaries: {},
        private_summaries: {
          "10号玩家": "我作为10号狼人。",
        },
        public_summary: "第1轮：无人被放逐。",
      },
    ],
  });

  expect(replay.rounds[0].public_summary).toBe("第1轮：无人被放逐。");
  expect(Object.values(replay.rounds[0].summaries).join("")).not.toContain("10号狼人");
});
```

- [ ] **Step 2: Run failing frontend tests**

Run:

```bash
pnpm --dir apps/web test -- --run \
  src/features/games/liveDirector.test.ts \
  src/features/games/liveNarrative.test.ts \
  src/features/games/api/adapters.test.ts
```

Expected: FAIL because the public summary and interruption copy are not handled yet.

- [ ] **Step 3: Add frontend types**

In `apps/web/src/features/games/types.ts`, add to `GameRound`:

```typescript
  public_summary?: string;
  private_summaries?: Record<string, string>;
  public_facts?: Array<{ round_number: number; category: string; text: string }>;
```

- [ ] **Step 4: Normalize public summary safely**

In `apps/web/src/features/games/api/adapters.ts`, update round normalization:

```typescript
    public_summary: typeof rawRound.public_summary === "string" ? rawRound.public_summary : "",
    private_summaries: isRecord(rawRound.private_summaries)
      ? stringRecord(rawRound.private_summaries)
      : {},
    public_facts: Array.isArray(rawRound.public_facts)
      ? rawRound.public_facts.filter(isRecord).map((fact) => ({
          round_number: Number(fact.round_number ?? 0),
          category: String(fact.category ?? "event"),
          text: String(fact.text ?? ""),
        }))
      : [],
```

Ensure `round.summaries` continues to use only `rawRound.summaries` and never falls back to `private_summaries`.

- [ ] **Step 5: Render public summary in live director**

In `apps/web/src/features/games/liveDirector.ts`, handle `public_summary` before `summaries`:

```typescript
  const publicSummary = stringField(payload, "public_summary");
  if (publicSummary) {
    return {
      ...base,
      title: "回合公开总结",
      body: publicSummary,
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }
```

Remove or narrow the existing `payload.summaries` branch so it ignores summary payloads when `payload.private_summaries` exists:

```typescript
  const summaries = payload.summaries;
  if (isRecord(summaries) && !isRecord(payload.private_summaries)) {
```

- [ ] **Step 6: Explain sheriff interruption in live narrative**

In `apps/web/src/features/games/liveNarrative.ts`, where self-explosion state updates are described, add:

```typescript
  if (
    action === "werewolf_self_explosion" &&
    payload.werewolf_self_exploded &&
    payload.sheriff_election_pending === true
  ) {
    return {
      title: `${payload.werewolf_self_exploded} 自爆`,
      body: "自爆中断警长竞选；警徽未流失，次日继续竞选。",
      tone: "danger",
    };
  }
```

- [ ] **Step 7: Use public summary in replay components**

In `apps/web/src/features/games/components/SummaryStrip.tsx`, accept public summary:

```typescript
type SummaryStripProps = {
  summaries: Record<string, string>;
  publicSummary?: string;
};

export function SummaryStrip({ summaries, publicSummary }: SummaryStripProps) {
  if (publicSummary) {
    return <p className="break-words text-sm text-slate-700">{publicSummary}</p>;
  }
```

In `apps/web/src/features/games/components/DayPhase.tsx`, pass:

```tsx
<SummaryStrip summaries={round.summaries} publicSummary={round.public_summary} />
```

- [ ] **Step 8: Run frontend tests**

Run:

```bash
pnpm --dir apps/web test -- --run \
  src/features/games/liveDirector.test.ts \
  src/features/games/liveNarrative.test.ts \
  src/features/games/api/adapters.test.ts \
  src/features/games/components/DayPhase.test.tsx
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/features/games/types.ts \
  apps/web/src/features/games/api/adapters.ts \
  apps/web/src/features/games/liveDirector.ts \
  apps/web/src/features/games/liveNarrative.ts \
  apps/web/src/features/games/components/SummaryStrip.tsx \
  apps/web/src/features/games/components/DayPhase.tsx \
  apps/web/src/features/games/liveDirector.test.ts \
  apps/web/src/features/games/liveNarrative.test.ts \
  apps/web/src/features/games/api/adapters.test.ts \
  apps/web/src/features/games/components/DayPhase.test.tsx
git commit -m "fix: show only public round summaries"
```

---

### Task 6: Offline Replay Evaluator

**Files:**
- Create: `apps/api/app/werewolf/evaluator.py`
- Modify: `apps/api/app/cli.py`
- Test: `apps/api/tests/test_werewolf_evaluator.py`
- Test: `apps/api/tests/test_werewolf_cli.py`

- [ ] **Step 1: Write failing evaluator tests**

Create `apps/api/tests/test_werewolf_evaluator.py`:

```python
import json

from app.werewolf.evaluator import evaluate_replay


def test_evaluator_flags_private_summary_leak_and_forgotten_public_claim(tmp_path) -> None:
    replay = {
        "session_id": "game_eval",
        "winner": "狼人阵营",
        "players": [],
        "rounds": [
            {
                "number": 2,
                "sheriff_speeches": [
                    {"speaker": "7号玩家", "message": "我是7号预言家，昨晚查验6号，6号是好人。"}
                ],
                "summaries": {},
                "private_summaries": {},
                "debate": [],
            },
            {
                "number": 4,
                "sheriff_speeches": [],
                "summaries": {"10号玩家": "我作为10号狼人，准备夜晚刀9号。"},
                "private_summaries": {},
                "debate": [
                    {"speaker": "1号玩家", "message": "我怀疑6号，他比较划水。"}
                ],
            },
        ],
    }
    path = tmp_path / "game_complete.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    report = evaluate_replay(path)

    assert "private_summary_leak" in report.issue_codes
    assert "public_claim_not_recalled" in report.issue_codes
```

Append to `apps/api/tests/test_werewolf_cli.py`:

```python
def test_evaluate_replay_command_prints_issue_codes(tmp_path, capsys) -> None:
    replay = {
        "session_id": "game_eval",
        "winner": "",
        "players": [],
        "rounds": [
            {
                "number": 1,
                "summaries": {"10号玩家": "我作为10号狼人。"},
                "private_summaries": {},
                "debate": [],
                "sheriff_speeches": [],
            }
        ],
    }
    path = tmp_path / "game_complete.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    exit_code = main(["evaluate-replay", "--source", str(path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "private_summary_leak" in output
```

- [ ] **Step 2: Run failing evaluator tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_evaluator.py \
  tests/test_werewolf_cli.py::test_evaluate_replay_command_prints_issue_codes \
  -q
```

Expected: FAIL because evaluator and CLI command do not exist.

- [ ] **Step 3: Create evaluator**

Create `apps/api/app/werewolf/evaluator.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRIVATE_LEAK_PATTERNS = (
    "我作为",
    "我是狼人",
    "夜晚刀",
    "准备刀",
)


@dataclass(frozen=True)
class ReplayEvaluationIssue:
    code: str
    round_number: int
    detail: str


@dataclass(frozen=True)
class ReplayEvaluationReport:
    session_id: str
    issues: list[ReplayEvaluationIssue]

    @property
    def issue_codes(self) -> list[str]:
        return [issue.code for issue in self.issues]


def evaluate_replay(path: Path) -> ReplayEvaluationReport:
    data = json.loads(path.read_text(encoding="utf-8"))
    issues: list[ReplayEvaluationIssue] = []
    rounds = data.get("rounds") or []
    public_good_claims: list[str] = []

    for round_state in rounds:
        round_number = int(round_state.get("number") or 0)
        for speaker, summary in _summary_entries(round_state.get("summaries")):
            if _contains_private_leak(summary):
                issues.append(
                    ReplayEvaluationIssue(
                        code="private_summary_leak",
                        round_number=round_number,
                        detail=f"{speaker}: {summary}",
                    )
                )

        for speech in round_state.get("sheriff_speeches") or []:
            message = str(speech.get("message") or "")
            public_good_claims.extend(_claimed_good_players(message))

        debate_text = "\n".join(
            str(entry.get("message") or "") for entry in round_state.get("debate") or []
        )
        for player in public_good_claims:
            if player in debate_text and f"{player}是好人" not in debate_text and f"{player}金水" not in debate_text:
                issues.append(
                    ReplayEvaluationIssue(
                        code="public_claim_not_recalled",
                        round_number=round_number,
                        detail=f"{player} was previously claimed good but discussed without that fact.",
                    )
                )

        if round_number >= 4 and ("明天再" in debate_text or "下一轮" in debate_text):
            if "直接输" not in debate_text and "不能出错" not in debate_text:
                issues.append(
                    ReplayEvaluationIssue(
                        code="endgame_pressure_miss",
                        round_number=round_number,
                        detail="Endgame debate mentions tomorrow without pressure.",
                    )
                )

    return ReplayEvaluationReport(
        session_id=str(data.get("session_id") or ""),
        issues=issues,
    )


def _summary_entries(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, dict):
        return []
    return [(str(actor), str(summary)) for actor, summary in value.items()]


def _contains_private_leak(text: str) -> bool:
    return any(pattern in text for pattern in PRIVATE_LEAK_PATTERNS)


def _claimed_good_players(text: str) -> list[str]:
    players: list[str] = []
    for match in re.finditer(r"(\\d+号玩家).{0,12}(?:好人|金水)", text):
        players.append(match.group(1))
    return players
```

- [ ] **Step 4: Add CLI command**

In `apps/api/app/cli.py`, import:

```python
from app.werewolf.evaluator import evaluate_replay
```

Add parser:

```python
    evaluate_parser = subparsers.add_parser(
        "evaluate-replay",
        help="Evaluate a game_complete.json replay for realism and information-boundary issues.",
    )
    evaluate_parser.add_argument("--source", type=Path, required=True)
    evaluate_parser.set_defaults(func=_evaluate_replay_command)
```

Add command function:

```python
def _evaluate_replay_command(args: argparse.Namespace) -> int:
    report = evaluate_replay(args.source)
    print(f"session_id={report.session_id}")
    if not report.issues:
        print("issues=0")
        return 0
    print(f"issues={len(report.issues)}")
    for issue in report.issues:
        print(f"{issue.code} round={issue.round_number} detail={issue.detail}")
    return 0
```

- [ ] **Step 5: Run evaluator tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_evaluator.py \
  tests/test_werewolf_cli.py::test_evaluate_replay_command_prints_issue_codes \
  -q
```

Expected: PASS.

- [ ] **Step 6: Run evaluator on the real replay**

Run:

```bash
cd apps/api && .venv/bin/python -m app.cli evaluate-replay \
  --source ../../artifacts/real_12_player_eval/game_e9937133/game_complete.json
```

Expected output includes:

```text
session_id=game_e9937133
private_summary_leak
public_claim_not_recalled
```

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/evaluator.py \
  apps/api/app/cli.py \
  apps/api/tests/test_werewolf_evaluator.py \
  apps/api/tests/test_werewolf_cli.py
git commit -m "feat: add replay realism evaluator"
```

---

### Task 7: Full Verification

**Files:**
- No source edits in this task.

- [ ] **Step 1: Run focused API tests**

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py \
  tests/test_werewolf_lm.py \
  tests/test_werewolf_resume.py \
  tests/test_werewolf_public_facts.py \
  tests/test_werewolf_action_quality.py \
  tests/test_werewolf_evaluator.py \
  tests/test_werewolf_cli.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run focused web tests**

```bash
pnpm --dir apps/web test -- --run \
  src/features/games/liveDirector.test.ts \
  src/features/games/liveNarrative.test.ts \
  src/features/games/api/adapters.test.ts \
  src/features/games/components/DayPhase.test.tsx
```

Expected: all selected tests pass.

- [ ] **Step 3: Run full API test suite**

```bash
cd apps/api && .venv/bin/python -m pytest
```

Expected: full API suite passes.

- [ ] **Step 4: Run full web test suite**

```bash
pnpm --dir apps/web test -- --run
```

Expected: full web suite passes.

- [ ] **Step 5: Commit verification notes if docs changed during execution**

If execution updates docs with verification notes, commit them:

```bash
git add docs/superpowers/specs/2026-06-14-12-player-realism-memory-hardening-design.md \
  docs/superpowers/plans/2026-06-14-12-player-realism-memory-hardening.md
git commit -m "docs: record realism hardening verification"
```

## Self-Review

- Spec coverage: P0 private summary boundary is Task 1 and Task 5; P0 public facts is Task 2; P1 endgame and role prompting is Task 3; P1 stage consistency is Task 4; P1 narrative clarity is Task 5; P2 evaluator is Task 6.
- Placeholder scan: the plan contains exact file paths, test snippets, implementation snippets, commands, and expected outcomes.
- Type consistency: `private_summaries`, `public_summary`, and `public_facts` are added in backend model serialization before frontend normalization references them.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-14-12-player-realism-memory-hardening.md`. Two execution options:

**1. Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
