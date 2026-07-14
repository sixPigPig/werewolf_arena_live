from __future__ import annotations

import json
import re
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.werewolf.debate_realism import (
    dialogue_quality_warnings,
    lineup_quality_warnings_from_players,
)
from app.werewolf.evaluation_bundle import build_quality_evaluation_bundle
from app.werewolf.quality_evaluation import evaluate_quality_bundle

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
INVALID_ACTION_MARKERS = ("returned invalid", "invalid witch_poison", "invalid hunter_shoot")


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


@dataclass(frozen=True)
class SelfExplosionBenchmarkReport:
    game_count: int
    chain_three_game_count: int
    chain_three_game_rate: float
    normal_day_debate_game_count: int
    normal_day_debate_game_rate: float
    audited_chain_decision_count: int
    complete_audit_count: int
    audit_completeness_rate: float
    max_chain_length: int
    passed: bool

    def to_dict(self) -> dict[str, int | float | bool]:
        return {
            "game_count": self.game_count,
            "chain_three_game_count": self.chain_three_game_count,
            "chain_three_game_rate": self.chain_three_game_rate,
            "normal_day_debate_game_count": self.normal_day_debate_game_count,
            "normal_day_debate_game_rate": self.normal_day_debate_game_rate,
            "audited_chain_decision_count": self.audited_chain_decision_count,
            "complete_audit_count": self.complete_audit_count,
            "audit_completeness_rate": self.audit_completeness_rate,
            "max_chain_length": self.max_chain_length,
            "passed": self.passed,
        }


def evaluate_replay(path: Path) -> ReplayEvaluationReport:
    data = json.loads(path.read_text(encoding="utf-8"))
    rounds = _rounds_from_data(data)
    issues: list[ReplayEvaluationIssue] = []
    public_good_claims: dict[str, str] = {}
    seen_issue_keys: set[tuple[str, int, str]] = set()
    recent_self_explosions: list[int] = []

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

    error_message = _error_message_from_data(data)
    if any(marker in error_message for marker in INVALID_ACTION_MARKERS):
        issues.append(
            ReplayEvaluationIssue(
                code="invalid_action_abort",
                round_number=0,
                detail=error_message,
            )
        )
    logs_path = path.with_name("game_logs.json")
    if error_message and logs_path.exists():
        try:
            logs_data = json.loads(logs_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logs_data = None
        if logs_data == []:
            issues.append(
                ReplayEvaluationIssue(
                    code="empty_partial_logs",
                    round_number=0,
                    detail="Partial replay has an error but game_logs.json is empty.",
                )
            )

    for round_state in rounds:
        round_number = int(round_state.get("number") or 0)

        if round_state.get("werewolf_self_exploded"):
            recent_self_explosions.append(round_number)
            recent_self_explosions = [
                item for item in recent_self_explosions if round_number - item <= 2
            ]
            if len(recent_self_explosions) >= 3:
                _append_issue(
                    issues,
                    seen_issue_keys,
                    ReplayEvaluationIssue(
                        code="chain_self_explosion_overuse",
                        round_number=round_number,
                        detail="Three werewolf self-explosions occurred within three rounds.",
                    ),
                    key_detail="chain",
                )

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

            if _has_role_term_contradiction(text):
                _append_issue(
                    issues,
                    seen_issue_keys,
                    ReplayEvaluationIssue(
                        code="role_term_contradiction",
                        round_number=round_number,
                        detail="Speech combines incompatible role terms such as 查杀 and 好人.",
                    ),
                    key_detail=f"{speaker}:{text[:80]}",
                )
            if speaker and _has_self_reference_as_group(speaker, text):
                _append_issue(
                    issues,
                    seen_issue_keys,
                    ReplayEvaluationIssue(
                        code="self_reference_as_group",
                        round_number=round_number,
                        detail="Speaker grouped their own seat with other seats as if they were separate.",
                    ),
                    key_detail=f"{speaker}:{text[:80]}",
                )

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


def evaluate_quality_fixture(path: Path, *, hmac_key: str) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("quality fixture must be a JSON object")
    state = data.get("state")
    logs = data.get("logs", [])
    events = data.get("live_events", [])
    voices = data.get("voice_utterances", [])
    if not isinstance(state, dict) or not isinstance(logs, list):
        raise ValueError("quality fixture requires object state and list logs")
    if not isinstance(events, list) or not isinstance(voices, list):
        raise ValueError("quality fixture event and voice sources must be lists")
    bundle = build_quality_evaluation_bundle(
        state=state,
        logs=[item for item in logs if isinstance(item, dict)],
        live_events=[item for item in events if isinstance(item, dict)],
        voice_utterances=[item for item in voices if isinstance(item, dict)],
        run_id=str(data.get("run_id") or "") or None,
    )
    return evaluate_quality_bundle(bundle, hmac_key=hmac_key).to_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a deterministic werewolf fixture")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--strict-p0", action="store_true")
    parser.add_argument("--hmac-key", default="fixture-quality-evaluation-key")
    args = parser.parse_args(argv)
    try:
        report = evaluate_quality_fixture(args.fixture, hmac_key=args.hmac_key)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error_code": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.strict_p0 and int(report.get("issue_counts", {}).get("P0", 0)) > 0:
        return 1
    return 0


def evaluate_self_explosion_benchmark(
    replays: list[dict[str, Any]],
    *,
    max_chain_three_rate: float = 0.05,
    min_normal_day_rate: float = 0.8,
    min_audit_completeness_rate: float = 1.0,
) -> SelfExplosionBenchmarkReport:
    chain_three_games = 0
    normal_day_games = 0
    audited_chain_decisions = 0
    complete_audits = 0
    max_chain_length = 0

    for replay in replays:
        rounds = sorted(
            _rounds_from_data(replay),
            key=lambda round_state: int(round_state.get("number") or 0),
        )
        logs_by_round = _logs_by_round(replay)
        current_chain = 0
        game_max_chain = 0
        has_normal_day = False
        for round_state in rounds:
            round_number = int(round_state.get("number") or 0)
            exploded = bool(round_state.get("werewolf_self_exploded"))
            if exploded:
                prior_chain = current_chain
                current_chain += 1
                game_max_chain = max(game_max_chain, current_chain)
                if prior_chain >= 1:
                    audited_chain_decisions += 1
                    action_log = logs_by_round.get(round_number, {}).get(
                        "werewolf_self_explosion"
                    )
                    if _self_explosion_audit_complete(action_log):
                        complete_audits += 1
            else:
                current_chain = 0

            debate = round_state.get("debate")
            votes = round_state.get("votes")
            if (
                isinstance(debate, list)
                and bool(debate)
                and bool(votes)
                and not round_state.get("day_ended_by_self_explosion")
            ):
                has_normal_day = True

        if game_max_chain >= 3:
            chain_three_games += 1
        if has_normal_day:
            normal_day_games += 1
        max_chain_length = max(max_chain_length, game_max_chain)

    game_count = len(replays)
    chain_rate = chain_three_games / game_count if game_count else 0.0
    normal_day_rate = normal_day_games / game_count if game_count else 0.0
    audit_rate = (
        complete_audits / audited_chain_decisions if audited_chain_decisions else 1.0
    )
    return SelfExplosionBenchmarkReport(
        game_count=game_count,
        chain_three_game_count=chain_three_games,
        chain_three_game_rate=chain_rate,
        normal_day_debate_game_count=normal_day_games,
        normal_day_debate_game_rate=normal_day_rate,
        audited_chain_decision_count=audited_chain_decisions,
        complete_audit_count=complete_audits,
        audit_completeness_rate=audit_rate,
        max_chain_length=max_chain_length,
        passed=(
            game_count > 0
            and chain_rate <= max_chain_three_rate
            and normal_day_rate >= min_normal_day_rate
            and audit_rate >= min_audit_completeness_rate
        ),
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


def _logs_by_round(data: dict[str, Any]) -> dict[int, dict[str, Any]]:
    logs = data.get("logs")
    if not isinstance(logs, list):
        return {}
    return {
        int(log.get("number") or 0): log
        for log in logs
        if isinstance(log, dict) and int(log.get("number") or 0) > 0
    }


def _self_explosion_audit_complete(action_log: object) -> bool:
    if not isinstance(action_log, dict) or action_log.get("decision_schema") != "v1":
        return False
    audit = action_log.get("decision_audit")
    if not isinstance(audit, dict):
        return False
    return all(
        isinstance(audit.get(field), str) and bool(str(audit[field]).strip())
        for field in ("benefit_type", "expected_gain", "primary_risk")
    )


def _error_message_from_data(data: dict[str, Any]) -> str:
    error_message = data.get("error_message")
    if isinstance(error_message, str):
        return error_message
    state = data.get("state")
    if isinstance(state, dict) and isinstance(state.get("error_message"), str):
        return str(state["error_message"])
    return ""


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


def _speech_entry_details(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    messages: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            message = item.get("message")
            if isinstance(message, str):
                speaker = str(item.get("speaker") or item.get("actor") or "")
                messages.append((speaker, message))
                continue
            choice = item.get("choice")
            if isinstance(choice, str):
                speaker = str(item.get("actor") or item.get("speaker") or "")
                messages.append((speaker, choice))
        elif isinstance(item, str):
            messages.append(("", item))
    return messages


def _has_role_term_contradiction(text: str) -> bool:
    return ("查杀" in text and "好人" in text) or ("金水" in text and "狼人" in text)


def _has_self_reference_as_group(speaker: str, text: str) -> bool:
    normalized = text.replace(" ", "")
    number = speaker.replace("玩家", "")
    aliases = [number]
    bare_number = number.replace("号", "")
    if bare_number != number:
        aliases.append(bare_number)
    return (
        "后置位" in normalized or "他们" in normalized or "范围" in normalized
    ) and any(
        pattern in normalized
        for alias in aliases
        for pattern in (f"{alias}、", f"、{alias}", f"{alias}和")
    )


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


if __name__ == "__main__":
    sys.exit(main())
