from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRIVATE_LEAK_PATTERNS = (
    "我作为",
    "我是狼人",
    "狼人身份",
    "夜晚刀",
    "准备刀",
)
SUSPICION_MARKERS = ("怀疑", "可疑", "像狼", "狼人", "出", "票", "抗推")
PRESSURE_MARKERS = ("直接输", "不能出错", "轮次", "生死", "最后")
TOMORROW_MARKERS = ("明天再", "下一轮")


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
    rounds = _rounds_from_data(data)
    issues: list[ReplayEvaluationIssue] = []
    public_good_claims: dict[str, str] = {}
    seen_issue_keys: set[tuple[str, int, str]] = set()

    for round_state in rounds:
        round_number = int(round_state.get("number") or 0)

        for speaker, summary in _summary_entries(round_state.get("summaries")):
            if _contains_private_leak(summary):
                _append_issue(
                    issues,
                    seen_issue_keys,
                    ReplayEvaluationIssue(
                        code="private_summary_leak",
                        round_number=round_number,
                        detail=f"{speaker}: {summary}",
                    ),
                    key_detail=speaker,
                )

        for speech in _speech_entries(round_state.get("sheriff_speeches")):
            for player in _claimed_good_players(speech):
                public_good_claims.setdefault(player, speech)

        debate_text = "\n".join(_speech_entries(round_state.get("debate")))
        for player, claim in public_good_claims.items():
            if (
                _casts_suspicion_on_player(debate_text, player)
                and not _acknowledges_good_claim(debate_text, player)
            ):
                _append_issue(
                    issues,
                    seen_issue_keys,
                    ReplayEvaluationIssue(
                        code="public_claim_not_recalled",
                        round_number=round_number,
                        detail=f"{player} was previously claimed good but challenged without recalling: {claim}",
                    ),
                    key_detail=player,
                )

        if (
            round_number >= 4
            and any(marker in debate_text for marker in TOMORROW_MARKERS)
            and not any(marker in debate_text for marker in PRESSURE_MARKERS)
        ):
            _append_issue(
                issues,
                seen_issue_keys,
                ReplayEvaluationIssue(
                    code="endgame_pressure_miss",
                    round_number=round_number,
                    detail="Endgame debate mentions tomorrow without pressure.",
                ),
                key_detail="tomorrow",
            )

    return ReplayEvaluationReport(
        session_id=str(data.get("session_id") or ""),
        issues=issues,
    )


def _append_issue(
    issues: list[ReplayEvaluationIssue],
    seen_issue_keys: set[tuple[str, int, str]],
    issue: ReplayEvaluationIssue,
    *,
    key_detail: str,
) -> None:
    key = (issue.code, issue.round_number, key_detail)
    if key in seen_issue_keys:
        return
    seen_issue_keys.add(key)
    issues.append(issue)


def _rounds_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = data.get("rounds")
    if isinstance(rounds, list):
        return [round_state for round_state in rounds if isinstance(round_state, dict)]

    state = data.get("state")
    if isinstance(state, dict) and isinstance(state.get("rounds"), list):
        return [
            round_state
            for round_state in state["rounds"]
            if isinstance(round_state, dict)
        ]

    return []


def _summary_entries(value: Any) -> list[tuple[str, str]]:
    if isinstance(value, dict):
        return [(str(actor), str(summary)) for actor, summary in value.items()]
    if not isinstance(value, list):
        return []

    entries: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        actor = str(item.get("actor") or "")
        summary = _summary_text_from_action_log(item)
        if summary:
            entries.append((actor, summary))
    return entries


def _summary_text_from_action_log(item: dict[str, Any]) -> str:
    choice = item.get("choice")
    if isinstance(choice, str):
        return choice

    lm_log = item.get("lm_log")
    if isinstance(lm_log, dict):
        result = lm_log.get("result")
        if isinstance(result, dict):
            for key in ("summary", "say", "speech"):
                value = result.get(key)
                if isinstance(value, str):
                    return value
    return ""


def _contains_private_leak(text: str) -> bool:
    return any(pattern in text for pattern in PRIVATE_LEAK_PATTERNS)


def _speech_entries(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    messages: list[str] = []
    for item in value:
        if isinstance(item, dict):
            message = item.get("message")
            if isinstance(message, str):
                messages.append(message)
        elif isinstance(item, str):
            messages.append(item)
    return messages


def _claimed_good_players(text: str) -> list[str]:
    patterns = (
        r"(?:查验|验了|验到|验人|金水给到|给到)(?P<player>\d+号(?:玩家)?).{0,12}(?:好人|金水)",
        r"(?P<player>\d+号(?:玩家)?)(?:是|为|是个|属于|被报为|被验为)(?:好人|金水)",
        r"(?P<player>\d+号(?:玩家)?)金水",
    )
    players: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            players.append(_normalize_player_ref(match.group("player")))
    return list(dict.fromkeys(players))


def _casts_suspicion_on_player(text: str, player: str) -> bool:
    if not text:
        return False
    for alias in _player_aliases(player):
        index = text.find(alias)
        while index >= 0:
            start = max(0, index - 10)
            end = min(len(text), index + len(alias) + 12)
            window = text[start:end]
            if any(marker in window for marker in SUSPICION_MARKERS):
                return True
            index = text.find(alias, index + len(alias))
    return False


def _acknowledges_good_claim(text: str, player: str) -> bool:
    aliases = _player_aliases(player)
    templates = []
    for alias in aliases:
        templates.extend(
            [
                f"{alias}是好人",
                f"{alias}为好人",
                f"{alias}金水",
                f"报{alias}好人",
                f"报{alias}金水",
                f"验{alias}好人",
                f"验{alias}金水",
            ]
        )
    return any(template in text for template in templates)


def _player_aliases(player: str) -> tuple[str, str]:
    number = _normalize_player_ref(player)
    return (number, f"{number}玩家")


def _normalize_player_ref(player: str) -> str:
    return player.replace("玩家", "")
