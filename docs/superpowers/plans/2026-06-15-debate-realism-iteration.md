# Debate Realism Iteration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make werewolf debate output detectably less repetitive by catching homogeneous lineups, adding turn-specific debate guidance, and surfacing dialogue-quality warnings before another `game_d2c4a7c2` style replay ships as clean.

**Architecture:** Add a small pure helper module for dialogue normalization, repeated phrase detection, debate turn guidance, and lineup quality checks. Feed that helper into evaluator, prompt construction, engine warning events, and create-run summaries without changing hidden-role rules or model provider boundaries. This iteration is warn-and-guide, not hard-block or discard-and-retry, because public streaming currently exposes first-pass debate text as it is generated.

**Tech Stack:** Python dataclasses, FastAPI route summaries, pytest, existing Werewolf engine/prompt/evaluator modules, TypeScript type normalization.

---

## File Structure

- Create `apps/api/app/werewolf/debate_realism.py`: pure functions for dialogue normalization, repeated phrase detection, catchphrase extraction, debate guidance, and lineup quality warnings.
- Create `apps/api/tests/test_werewolf_debate_realism.py`: focused tests for the new helper functions.
- Modify `apps/api/app/werewolf/evaluator.py`: use the helper to flag homogeneous player lineups and repeated/low-novelty debates in replay files.
- Modify `apps/api/tests/test_werewolf_evaluator.py`: add replay fixtures that reproduce the `game_d2c4a7c2` failure mode.
- Modify `apps/api/app/werewolf/prompts_zh.py`: render debate guidance and quality feedback sections.
- Modify `apps/api/tests/test_werewolf_lm.py`: assert prompt sections are rendered.
- Modify `apps/api/app/werewolf/engine.py`: add debate guidance to `world_state` and publish dialogue quality warnings with prior debate context.
- Modify `apps/api/tests/test_werewolf_runner.py`: assert world state and live warning events include debate realism signals.
- Modify `apps/api/app/werewolf/action_quality.py`: delegate debate repetition checks to `debate_realism.py` while preserving existing warning codes.
- Modify `apps/api/tests/test_werewolf_action_quality.py`: cover new warning codes through the public helper.
- Modify `apps/api/app/werewolf/live.py`: carry lineup quality warnings in live run summaries and run-created events.
- Modify `apps/api/app/api/routes/games.py`: compute lineup quality warnings after player configs are resolved.
- Modify `apps/api/tests/test_games_api.py`: assert create-run responses include soft warnings for homogeneous libraries.
- Modify `apps/web/src/features/games/types.ts`: type the optional `lineup_quality_warnings` response field.

---

### Task 1: Dialogue Realism Helper

**Files:**
- Create: `apps/api/app/werewolf/debate_realism.py`
- Test: `apps/api/tests/test_werewolf_debate_realism.py`

- [ ] **Step 1: Write the failing helper tests**

Create `apps/api/tests/test_werewolf_debate_realism.py`:

```python
from app.werewolf.debate_realism import (
    catchphrases_from_personality,
    debate_guidance_for_turn,
    dialogue_quality_warnings,
    lineup_quality_warnings,
    repeated_phrase_candidates,
)
from app.werewolf.player_configs import PlayerConfig


ANALYTICAL_PERSONALITY = (
    "重视票型、发言顺序和行为一致性。\n"
    "角色简介: 沉稳控场，喜欢先盘逻辑再给站边。\n"
    "常用表达: 我先盘票型；这里不急着站死"
)


def test_repeated_phrase_candidates_detects_round_level_repetition() -> None:
    messages = [
        "守夜潜行第一夜出局，狼人刀法值得关注。先听一圈发言，我盘逻辑不急着站边。",
        "守夜潜行第一夜出局，刀法很有针对性。先不站死，听后面发言再盘票型。",
        "守夜潜行第一夜被刀，刀法有指向性。我不急着站边，但会留意谁在带节奏。",
    ]

    phrases = repeated_phrase_candidates(messages, min_chars=4, min_count=2)

    assert "守夜潜行" in phrases
    assert "不急着站" in phrases
    assert len(phrases) <= 8


def test_catchphrases_from_personality_reads_profile_line() -> None:
    assert catchphrases_from_personality(ANALYTICAL_PERSONALITY) == [
        "我先盘票型",
        "这里不急着站死",
    ]


def test_dialogue_quality_warnings_detects_repetition_and_catchphrase_overuse() -> None:
    warnings = dialogue_quality_warnings(
        text="我先盘票型。第一轮全票挂警徽定狼，这里不急着站死，先听后置位补充。",
        prior_texts=[
            "我先盘票型。第一轮全票挂警徽定狼，说明大家都觉得他发言差。",
            "第一轮全票挂警徽定狼，但我不急着站边。",
        ],
        personality=ANALYTICAL_PERSONALITY,
    )

    assert "catchphrase_overuse" in warnings
    assert "repeated_debate_phrase" in warnings
    assert "low_novelty_debate" in warnings


def test_debate_guidance_for_turn_assigns_distinct_speaker_jobs() -> None:
    first = debate_guidance_for_turn(
        speaker="票台换票",
        active_players=["票台换票", "狼啸听风", "烛火潜行"],
        prior_messages=[],
        personality=ANALYTICAL_PERSONALITY,
    )
    final = debate_guidance_for_turn(
        speaker="烛火潜行",
        active_players=["票台换票", "狼啸听风", "烛火潜行"],
        prior_messages=[
            "票台换票：我先盘票型。第一轮全票挂警徽定狼。",
            "狼啸听风：盘票型。票台换票行为矛盾。",
        ],
        personality=ANALYTICAL_PERSONALITY,
    )

    assert any("第 1/3 位" in line for line in first)
    assert any("开一个新信息点" in line for line in first)
    assert any("第 3/3 位" in line for line in final)
    assert any("明确票口" in line for line in final)
    assert any("避免复用" in line for line in final)


def test_lineup_quality_warnings_detects_homogeneous_profiles() -> None:
    configs = [
        PlayerConfig(
            seat=seat,
            profile_id=f"profile-{seat}",
            name=f"玩家{seat}",
            model="model",
            personality_id="analytical",
            personality=ANALYTICAL_PERSONALITY,
            appearance_id="default",
            avatar_prompt="",
            tags=("控场", "复盘"),
        )
        for seat in range(1, 5)
    ]

    warnings = lineup_quality_warnings(configs)

    assert warnings == [
        {
            "code": "homogeneous_personality_lineup",
            "detail": "4 players share personality_id analytical.",
        },
        {
            "code": "shared_catchphrase_lineup",
            "detail": "4 players share catchphrase 我先盘票型.",
        },
        {
            "code": "shared_tag_lineup",
            "detail": "4 players share tag 控场.",
        },
    ]
```

- [ ] **Step 2: Run helper tests and verify they fail**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_debate_realism.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.werewolf.debate_realism'`.

- [ ] **Step 3: Implement the helper module**

Create `apps/api/app/werewolf/debate_realism.py`:

```python
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.werewolf.player_configs import PlayerConfig

PUNCTUATION_RE = re.compile(r"[\s，。！？、；：,.!?;:\"'《》（）()【】\[\]{}<>-]+")
CATCHPHRASE_LINE_RE = re.compile(r"^常用表达:\s*(.+)$", re.MULTILINE)
CATCHPHRASE_SPLIT_RE = re.compile(r"[；;、,，\n]+")
LOW_NOVELTY_THRESHOLD = 0.45


def normalize_dialogue_text(text: str) -> str:
    return PUNCTUATION_RE.sub("", text.strip())


def catchphrases_from_personality(personality: str) -> list[str]:
    match = CATCHPHRASE_LINE_RE.search(personality or "")
    if not match:
        return []
    phrases: list[str] = []
    seen: set[str] = set()
    for item in CATCHPHRASE_SPLIT_RE.split(match.group(1)):
        phrase = item.strip()
        if not phrase or phrase in seen:
            continue
        phrases.append(phrase)
        seen.add(phrase)
    return phrases


def repeated_phrase_candidates(
    texts: list[str],
    *,
    min_chars: int = 4,
    min_count: int = 2,
    limit: int = 8,
) -> list[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        normalized = normalize_dialogue_text(text)
        seen_for_text: set[str] = set()
        max_chars = min(8, len(normalized))
        for size in range(min_chars, max_chars + 1):
            for index in range(0, len(normalized) - size + 1):
                phrase = normalized[index : index + size]
                if _is_weak_phrase(phrase):
                    continue
                seen_for_text.add(phrase)
        counts.update(seen_for_text)

    phrases: list[str] = []
    for phrase, count in counts.most_common():
        if count < min_count:
            continue
        if any(phrase in existing or existing in phrase for existing in phrases):
            continue
        phrases.append(phrase)
        if len(phrases) >= limit:
            break
    return phrases


def dialogue_quality_warnings(
    *,
    text: str,
    prior_texts: list[str] | tuple[str, ...] = (),
    personality: str = "",
) -> list[str]:
    warnings: list[str] = []
    normalized = normalize_dialogue_text(text)
    normalized_catchphrases = [
        normalize_dialogue_text(phrase)
        for phrase in catchphrases_from_personality(personality)
        if normalize_dialogue_text(phrase)
    ]
    if any(phrase in normalized for phrase in normalized_catchphrases):
        warnings.append("catchphrase_overuse")

    prior = [str(item) for item in prior_texts if str(item).strip()]
    if prior:
        repeated = repeated_phrase_candidates([*prior, text], min_chars=4, min_count=2)
        if any(phrase in normalized for phrase in repeated):
            warnings.append("repeated_debate_phrase")
        overlap = _fourgram_overlap_ratio(normalized, prior)
        if overlap >= LOW_NOVELTY_THRESHOLD:
            warnings.append("low_novelty_debate")

    return warnings


def debate_guidance_for_turn(
    *,
    speaker: str,
    active_players: list[str],
    prior_messages: list[str],
    personality: str,
) -> list[str]:
    total = max(1, len(active_players))
    position = min(total, len(prior_messages) + 1)
    lines = [f"你是本轮第 {position}/{total} 位发言。"]
    if position == 1:
        lines.append("开一个新信息点：优先提出夜死、票型、身份声明或发言顺序中的一个可验证疑点。")
    elif position == total:
        lines.append("你是末置位：必须收束分歧，明确票口，并点名回应至少一名玩家。")
    elif position >= max(1, total - 1):
        lines.append("你是后置位：不要复述前置位结论，补一个反证、追问或票型解释。")
    else:
        lines.append("你是中置位：选择一个前置位观点进行赞同或反驳，并给出新的理由。")

    forbidden = repeated_phrase_candidates(prior_messages, min_chars=4, min_count=2, limit=5)
    catchphrases = catchphrases_from_personality(personality)
    avoid = list(dict.fromkeys([*forbidden, *catchphrases]))[:6]
    if avoid:
        lines.append(f"避免复用这些已出现或个人口癖表达：{'、'.join(avoid)}。")
    lines.append("发言必须新增一个未被前置位完整说过的事实、反问或投票解释。")
    return lines


def lineup_quality_warnings(configs: list[PlayerConfig]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    personality_counts = Counter(config.personality_id for config in configs if config.personality_id)
    catchphrase_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    for config in configs:
        catchphrase_counts.update(catchphrases_from_personality(config.personality))
        tag_counts.update(config.tags)

    for personality_id, count in personality_counts.most_common(1):
        if count >= 4:
            warnings.append(
                {
                    "code": "homogeneous_personality_lineup",
                    "detail": f"{count} players share personality_id {personality_id}.",
                }
            )
    for phrase, count in catchphrase_counts.most_common(1):
        if count >= 4:
            warnings.append(
                {
                    "code": "shared_catchphrase_lineup",
                    "detail": f"{count} players share catchphrase {phrase}.",
                }
            )
    for tag, count in tag_counts.most_common(1):
        if count >= 4:
            warnings.append(
                {
                    "code": "shared_tag_lineup",
                    "detail": f"{count} players share tag {tag}.",
                }
            )
    return warnings


def lineup_quality_warnings_from_players(players: list[dict[str, Any]]) -> list[dict[str, str]]:
    configs = [
        PlayerConfig(
            seat=index,
            profile_id=str(player.get("profile_id") or ""),
            name=str(player.get("name") or ""),
            model=str(player.get("model") or ""),
            personality_id=str(player.get("personality_id") or ""),
            personality=str(player.get("personality") or ""),
            appearance_id=str(player.get("appearance_id") or ""),
            avatar_prompt=str(player.get("avatar_prompt") or ""),
            tags=tuple(str(tag) for tag in player.get("tags") or []),
        )
        for index, player in enumerate(players, start=1)
        if isinstance(player, dict)
    ]
    return lineup_quality_warnings(configs)


def _fourgram_overlap_ratio(text: str, prior_texts: list[str]) -> float:
    own = _ngrams(text, 4)
    if len(own) < 8:
        return 0.0
    prior: set[str] = set()
    for prior_text in prior_texts:
        prior.update(_ngrams(normalize_dialogue_text(prior_text), 4))
    if not prior:
        return 0.0
    return len(own & prior) / len(own)


def _ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return set()
    return {text[index : index + size] for index in range(0, len(text) - size + 1)}


def _is_weak_phrase(phrase: str) -> bool:
    return len(set(phrase)) <= 1 or phrase.isdigit()
```

- [ ] **Step 4: Run helper tests and verify they pass**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_debate_realism.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit helper**

Run:

```bash
git add apps/api/app/werewolf/debate_realism.py apps/api/tests/test_werewolf_debate_realism.py
git commit -m "feat: add debate realism helpers"
```

---

### Task 2: Replay Evaluator Regression Coverage

**Files:**
- Modify: `apps/api/app/werewolf/evaluator.py`
- Test: `apps/api/tests/test_werewolf_evaluator.py`

- [ ] **Step 1: Write failing evaluator tests**

Append to `apps/api/tests/test_werewolf_evaluator.py`:

```python
def test_evaluator_flags_homogeneous_lineup_and_repeated_debate(tmp_path) -> None:
    personality = (
        "重视票型、发言顺序和行为一致性。\n"
        "常用表达: 我先盘票型；这里不急着站死"
    )
    replay = {
        "session_id": "game_repetition_eval",
        "winner": "狼人阵营",
        "players": [
            {
                "name": f"玩家{index}",
                "role": "村民",
                "model": "deepseek-v4-flash",
                "personality_id": "analytical",
                "personality": personality,
                "tags": ["控场", "复盘"],
            }
            for index in range(1, 5)
        ],
        "rounds": [
            {
                "number": 2,
                "summaries": {},
                "sheriff_speeches": [],
                "debate": [
                    {"speaker": "玩家1", "message": "我先盘票型。第一轮全票挂警徽定狼，这里不急着站死。"},
                    {"speaker": "玩家2", "message": "我先盘票型。第一轮全票挂警徽定狼，这里不急着站死，先听后置位。"},
                    {"speaker": "玩家3", "message": "我先盘票型。第一轮全票挂警徽定狼，先听后置位补充。"},
                ],
            }
        ],
    }
    path = tmp_path / "game_complete.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    report = evaluate_replay(path)

    assert "homogeneous_personality_lineup" in report.issue_codes
    assert "shared_catchphrase_lineup" in report.issue_codes
    assert "repeated_debate_phrase" in report.issue_codes
    assert "low_novelty_debate" in report.issue_codes
```

- [ ] **Step 2: Run evaluator test and verify it fails**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_evaluator.py::test_evaluator_flags_homogeneous_lineup_and_repeated_debate \
  -q
```

Expected: FAIL because the evaluator returns no new dialogue realism codes.

- [ ] **Step 3: Import helper functions**

In `apps/api/app/werewolf/evaluator.py`, add this import after the existing imports:

```python
from app.werewolf.debate_realism import (
    dialogue_quality_warnings,
    lineup_quality_warnings_from_players,
)
```

- [ ] **Step 4: Add lineup issues at the start of evaluation**

In `evaluate_replay()`, after `recent_self_explosions: list[int] = []`, insert:

```python
    players = data.get("players")
    if isinstance(players, list):
        for warning in lineup_quality_warnings_from_players(players):
            issues.append(
                ReplayEvaluationIssue(
                    code=warning["code"],
                    round_number=0,
                    detail=warning["detail"],
                )
            )
```

- [ ] **Step 5: Add debate repetition issues inside each round**

In `evaluate_replay()`, inside the loop over `round_state`, replace the current debate detail loop:

```python
        for speaker, text in _speech_entry_details(round_state.get("debate")):
```

with:

```python
        prior_debate_texts: list[str] = []
        for speaker, text in _speech_entry_details(round_state.get("debate")):
            for warning in dialogue_quality_warnings(
                text=text,
                prior_texts=prior_debate_texts,
                personality=_player_personality(data, speaker),
            ):
                _append_issue(
                    issues,
                    seen_issue_keys,
                    ReplayEvaluationIssue(
                        code=warning,
                        round_number=round_number,
                        detail=f"{speaker}: {text}",
                    ),
                    key_detail=f"{speaker}:{warning}:{text[:80]}",
                )
            prior_debate_texts.append(text)
```

Then add this helper near `_error_message_from_data()`:

```python
def _player_personality(data: dict[str, Any], speaker: str) -> str:
    players = data.get("players")
    if not isinstance(players, list):
        return ""
    for player in players:
        if not isinstance(player, dict):
            continue
        if str(player.get("name") or "") == speaker:
            return str(player.get("personality") or "")
    return ""
```

- [ ] **Step 6: Run evaluator tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_evaluator.py -q
```

Expected: PASS.

- [ ] **Step 7: Verify the observed replay turns red**

Run:

```bash
cd apps/api && .venv/bin/python -m app.cli evaluate-replay --source logs/game_d2c4a7c2/game_complete.json
```

Expected output includes:

```text
session_id=game_d2c4a7c2
issues=
```

and the issue list printed by the CLI includes `homogeneous_personality_lineup`, `shared_catchphrase_lineup`, `repeated_debate_phrase`, or `low_novelty_debate`.

- [ ] **Step 8: Commit evaluator coverage**

Run:

```bash
git add apps/api/app/werewolf/evaluator.py apps/api/tests/test_werewolf_evaluator.py
git commit -m "feat: evaluate repetitive debate realism"
```

---

### Task 3: Prompt Debate Guidance

**Files:**
- Modify: `apps/api/app/werewolf/prompts_zh.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Test: `apps/api/tests/test_werewolf_lm.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing prompt test**

Append to `apps/api/tests/test_werewolf_lm.py`:

```python
def test_debate_prompt_renders_turn_guidance_and_quality_feedback() -> None:
    prompt, _schema = build_prompt(
        "debate",
        {
            **_world_state_for_special_action("村民", ""),
            "debate": ["票台换票：我先盘票型。第一轮全票挂警徽定狼。"],
            "debate_guidance": [
                "你是本轮第 2/3 位发言。",
                "你是中置位：选择一个前置位观点进行赞同或反驳，并给出新的理由。",
                "避免复用这些已出现或个人口癖表达：我先盘票型。",
            ],
            "quality_feedback": "上次发言重复了我先盘票型，请换表达并新增反问。",
        },
    )

    assert "本轮发言任务" in prompt
    assert "你是本轮第 2/3 位发言。" in prompt
    assert "避免复用这些已出现或个人口癖表达：我先盘票型。" in prompt
    assert "质量反馈" in prompt
    assert "上次发言重复了我先盘票型" in prompt
```

- [ ] **Step 2: Write failing world-state test**

Append to `apps/api/tests/test_werewolf_runner.py` near the other `_world_state` tests:

```python
def test_world_state_includes_debate_guidance_for_current_speaker() -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="debate_guidance_world_state",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=2026061504,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    active_players = [player.name for player in state.players]
    player = state.players[1]
    player.personality = "常用表达: 我先盘票型；这里不急着站死"
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.debate.append(
        DebateEntry(speaker=active_players[0], message="我先盘票型。第一轮先听发言。")
    )

    world_state = engine._world_state(player, [], round_state)

    assert "debate_guidance" in world_state
    assert any("第 2/6 位" in line for line in world_state["debate_guidance"])
    assert any("避免复用" in line for line in world_state["debate_guidance"])
```

- [ ] **Step 3: Run prompt and world-state tests and verify they fail**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_debate_prompt_renders_turn_guidance_and_quality_feedback \
  tests/test_werewolf_runner.py::test_world_state_includes_debate_guidance_for_current_speaker \
  -q
```

Expected: FAIL because prompt rendering and world-state guidance are absent.

- [ ] **Step 4: Render guidance sections in prompts**

In `apps/api/app/werewolf/prompts_zh.py`, add `_render_debate_guidance(world_state)` and `_render_quality_feedback(world_state)` to the `sections` list after `_render_debate(world_state)`:

```python
        _render_debate(world_state),
        _render_debate_guidance(world_state),
        _render_quality_feedback(world_state),
        _render_instruction(action, world_state),
```

Add these functions after `_render_debate()`:

```python
def _render_debate_guidance(world_state: dict[str, Any]) -> str:
    guidance = world_state.get("debate_guidance") or []
    if not guidance:
        return ""
    return "本轮发言任务：\n" + "\n".join(f"- {line}" for line in guidance)


def _render_quality_feedback(world_state: dict[str, Any]) -> str:
    feedback = str(world_state.get("quality_feedback") or "").strip()
    if not feedback:
        return ""
    return f"质量反馈：\n- {feedback}"
```

- [ ] **Step 5: Add guidance to engine world state**

In `apps/api/app/werewolf/engine.py`, add this import:

```python
from app.werewolf.debate_realism import debate_guidance_for_turn
```

In `_world_state()`, add:

```python
            "debate_guidance": self._debate_guidance(player, active_players, round_state),
```

after the existing `"debate": debate,` entry.

Add this method after `_world_state()`:

```python
    def _debate_guidance(
        self,
        player: Player,
        active_players: list[str],
        round_state: RoundState,
    ) -> list[str]:
        return debate_guidance_for_turn(
            speaker=player.name,
            active_players=active_players,
            prior_messages=[
                f"{entry.speaker}：{entry.message}"
                for entry in round_state.debate
            ],
            personality=player.personality,
        )
```

- [ ] **Step 6: Run prompt and world-state tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_debate_prompt_renders_turn_guidance_and_quality_feedback \
  tests/test_werewolf_runner.py::test_world_state_includes_debate_guidance_for_current_speaker \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit prompt guidance**

Run:

```bash
git add apps/api/app/werewolf/prompts_zh.py apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_lm.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: guide debate turns away from repetition"
```

---

### Task 4: Runtime Dialogue Quality Warnings

**Files:**
- Modify: `apps/api/app/werewolf/action_quality.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Test: `apps/api/tests/test_werewolf_action_quality.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing action-quality tests**

Append to `apps/api/tests/test_werewolf_action_quality.py`:

```python
def test_action_quality_flags_debate_repetition_with_context() -> None:
    warnings = action_quality_warnings(
        action="debate",
        text="我先盘票型。第一轮全票挂警徽定狼，这里不急着站死。",
        prior_texts=[
            "我先盘票型。第一轮全票挂警徽定狼，说明大家都觉得他发言差。",
            "第一轮全票挂警徽定狼，先听后置位。",
        ],
        personality="常用表达: 我先盘票型；这里不急着站死",
    )

    assert "catchphrase_overuse" in warnings
    assert "repeated_debate_phrase" in warnings
    assert "low_novelty_debate" in warnings
```

- [ ] **Step 2: Write failing engine warning test**

Append to `apps/api/tests/test_werewolf_runner.py` near `test_action_quality_warning_event_is_published_for_stage_mismatch`:

```python
def test_debate_action_quality_warning_uses_prior_round_context() -> None:
    sink = CapturingEventSink()
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="debate_quality_warning",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=2026061505,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
        event_sink=sink,
        rng=random.Random(1),
    )
    player = state.players[1]
    player.personality = "常用表达: 我先盘票型；这里不急着站死"
    round_state = RoundState(number=1, players=[player.name for player in state.players])
    round_state.debate.append(
        DebateEntry(
            speaker=state.players[0].name,
            message="我先盘票型。第一轮全票挂警徽定狼。",
        )
    )

    engine._publish_action_quality_warnings(
        round_state=round_state,
        phase="day",
        actor=player.name,
        action=ACTION_DEBATE,
        text="我先盘票型。第一轮全票挂警徽定狼，这里不急着站死。",
        prior_texts=[entry.message for entry in round_state.debate],
        personality=player.personality,
    )

    warning_event = next(event for event in sink.events if event["type"] == "action_quality_warning")
    assert "catchphrase_overuse" in warning_event["payload"]["warnings"]
    assert "repeated_debate_phrase" in warning_event["payload"]["warnings"]
```

- [ ] **Step 3: Run warning tests and verify they fail**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_action_quality.py::test_action_quality_flags_debate_repetition_with_context \
  tests/test_werewolf_runner.py::test_debate_action_quality_warning_uses_prior_round_context \
  -q
```

Expected: FAIL because `action_quality_warnings()` does not accept `prior_texts` or `personality`.

- [ ] **Step 4: Extend action quality helper**

In `apps/api/app/werewolf/action_quality.py`, add:

```python
from app.werewolf.debate_realism import dialogue_quality_warnings
```

Change the function signature:

```python
def action_quality_warnings(
    *,
    action: str,
    text: str,
    actor: str | None = None,
    endgame: bool = False,
    prior_texts: list[str] | tuple[str, ...] = (),
    personality: str = "",
) -> list[str]:
```

Before `return warnings`, insert:

```python
    if action == "debate":
        for warning in dialogue_quality_warnings(
            text=text,
            prior_texts=prior_texts,
            personality=personality,
        ):
            if warning not in warnings:
                warnings.append(warning)
```

- [ ] **Step 5: Pass prior debate context from engine**

In `apps/api/app/werewolf/engine.py`, change `_publish_action_quality_warnings()` signature:

```python
    def _publish_action_quality_warnings(
        self,
        *,
        round_state: RoundState,
        phase: str,
        actor: str,
        action: str,
        text: str,
        prior_texts: list[str] | tuple[str, ...] = (),
        personality: str = "",
    ) -> None:
```

Change its call to `action_quality_warnings()`:

```python
        warnings = action_quality_warnings(
            action=action,
            text=text,
            actor=actor,
            endgame=len(round_state.players) <= 4,
            prior_texts=prior_texts,
            personality=personality,
        )
```

In `_run_debate_phase()`, change the warning call to:

```python
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="day",
                actor=speaker,
                action=ACTION_DEBATE,
                text=message,
                prior_texts=[entry.message for entry in round_state.debate],
                personality=player.personality,
            )
```

- [ ] **Step 6: Run warning tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_action_quality.py \
  tests/test_werewolf_runner.py::test_debate_action_quality_warning_uses_prior_round_context \
  tests/test_werewolf_runner.py::test_action_quality_warning_event_is_published_for_stage_mismatch \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit runtime warnings**

Run:

```bash
git add apps/api/app/werewolf/action_quality.py apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_action_quality.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: warn on repetitive debate output"
```

---

### Task 5: Soft Lineup Quality Warnings In Create-Run Summary

**Files:**
- Modify: `apps/api/app/werewolf/live.py`
- Modify: `apps/api/app/api/routes/games.py`
- Modify: `apps/api/tests/test_games_api.py`
- Modify: `apps/web/src/features/games/types.ts`

- [ ] **Step 1: Write failing API test**

Append to `apps/api/tests/test_games_api.py`:

```python
def test_create_game_run_returns_lineup_quality_warnings_for_homogeneous_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(6)
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)

    def fake_background_run(**kwargs: object) -> None:
        del kwargs

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "starter_6", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    warnings = response.json()["lineup_quality_warnings"]
    assert warnings[0]["code"] == "homogeneous_personality_lineup"
```

- [ ] **Step 2: Run API test and verify it fails**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_games_api.py::test_create_game_run_returns_lineup_quality_warnings_for_homogeneous_profiles \
  -q
```

Expected: FAIL with `KeyError: 'lineup_quality_warnings'`.

- [ ] **Step 3: Extend live run summary**

In `apps/api/app/werewolf/live.py`, add a field to `LiveGameRun`:

```python
    lineup_quality_warnings: list[dict[str, str]] = field(default_factory=list)
```

Add it to `to_summary()` after `player_configs`:

```python
            "lineup_quality_warnings": _copy_json_payload(self.lineup_quality_warnings),
```

Change `LiveRunRegistry.create_run()` signature:

```python
        lineup_quality_warnings: list[dict[str, str]] | None = None,
```

Set local data before the lock:

```python
        lineup_warning_data = _copy_json_payload(lineup_quality_warnings or [])
```

Pass it into `LiveGameRun(...)`:

```python
                lineup_quality_warnings=lineup_warning_data,
```

Add it to the `run_created` payload:

```python
                    "lineup_quality_warnings": lineup_warning_data,
```

- [ ] **Step 4: Compute warnings in create-run route**

In `apps/api/app/api/routes/games.py`, add this import:

```python
from app.werewolf.debate_realism import lineup_quality_warnings
```

After `validate_unique_effective_player_names(...)` succeeds, insert:

```python
    lineup_warnings = lineup_quality_warnings(player_configs)
```

Pass warnings into `registry.create_run(...)`:

```python
        lineup_quality_warnings=lineup_warnings,
```

- [ ] **Step 5: Update TypeScript response type**

In `apps/web/src/features/games/types.ts`, add:

```ts
export type LineupQualityWarning = {
  code: string;
  detail: string;
};
```

Add this field to `GameRun`:

```ts
  lineup_quality_warnings?: LineupQualityWarning[];
```

- [ ] **Step 6: Run API and type-adjacent tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_games_api.py::test_create_game_run_returns_lineup_quality_warnings_for_homogeneous_profiles -q
cd apps/web && pnpm test -- --run src/features/games/api/liveRunApi.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit lineup warnings**

Run:

```bash
git add apps/api/app/werewolf/live.py apps/api/app/api/routes/games.py apps/api/tests/test_games_api.py apps/web/src/features/games/types.ts
git commit -m "feat: surface lineup quality warnings"
```

---

### Task 6: Full Verification

**Files:**
- No source edits.

- [ ] **Step 1: Run focused API tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_debate_realism.py \
  tests/test_werewolf_evaluator.py \
  tests/test_werewolf_action_quality.py \
  tests/test_werewolf_lm.py::test_debate_prompt_renders_turn_guidance_and_quality_feedback \
  tests/test_werewolf_runner.py::test_world_state_includes_debate_guidance_for_current_speaker \
  tests/test_werewolf_runner.py::test_debate_action_quality_warning_uses_prior_round_context \
  tests/test_games_api.py::test_create_game_run_returns_lineup_quality_warnings_for_homogeneous_profiles \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run replay evaluator on the observed bad game**

Run:

```bash
cd apps/api && .venv/bin/python -m app.cli evaluate-replay --source logs/game_d2c4a7c2/game_complete.json
```

Expected: output includes `session_id=game_d2c4a7c2`, `issues=` with a value greater than `0`, and at least one dialogue realism code.

- [ ] **Step 3: Run existing API regression tests touched by this plan**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_games_api.py \
  tests/test_werewolf_runner.py \
  tests/test_werewolf_lm.py \
  tests/test_werewolf_evaluator.py \
  tests/test_werewolf_action_quality.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Run web tests for typed API surface**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/api/liveRunApi.test.ts src/features/games/api/adapters.test.ts
```

Expected: PASS.

- [ ] **Step 5: Review git diff**

Run:

```bash
git diff --stat
git diff -- apps/api/app/werewolf/debate_realism.py apps/api/app/werewolf/evaluator.py apps/api/app/werewolf/prompts_zh.py apps/api/app/werewolf/engine.py apps/api/app/werewolf/action_quality.py apps/api/app/werewolf/live.py apps/api/app/api/routes/games.py apps/web/src/features/games/types.ts
```

Expected: diff is limited to debate realism helpers, evaluator/prompt/engine warning integration, run summary warnings, and tests from this plan.

---

## Self-Review

**Spec coverage:** The plan covers the observed root causes: identical player personality/catchphrases, prompt-level turn guidance, evaluator blind spots, runtime warning visibility, and API-level lineup warnings. It intentionally leaves public-stream discard-and-retry out of this iteration because current streaming would expose first-pass public debate text before a replacement could be chosen.

**Placeholder scan:** The plan contains concrete file paths, commands, expected failures, expected passes, and code blocks for each source change. It avoids unspecified future work inside the implementation tasks.

**Type consistency:** New warning codes are strings across Python evaluator, action quality events, live summaries, and TypeScript API types. `lineup_quality_warnings` is a list of `{code, detail}` dictionaries in Python and `LineupQualityWarning[]` in TypeScript.
