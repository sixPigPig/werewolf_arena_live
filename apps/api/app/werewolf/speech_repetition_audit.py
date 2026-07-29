from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.game_session import GameReplayPayload
from app.models.live import LiveEventRecord, LiveRunRecord
from app.werewolf.debate_realism import (
    REPETITION_REWRITE_THRESHOLD,
    assign_speech_mission,
    normalize_dialogue_text,
    repeated_phrase_candidates,
)

_REPETITION_CODES = frozenset({"repeated_debate_phrase", "low_proposition_novelty"})
_TOPIC_OVERLAP_THRESHOLD = 0.25
_SAME_ROUND_TOPIC_OVERLAP_THRESHOLD = 0.2
_PUBLIC_SPEECH_ACTIONS = frozenset(
    {
        "debate",
        "sheriff_speech",
        "sheriff_pk_speech",
        "exile_pk_speech",
        "exile_last_words",
    }
)
_SEAT_REFERENCE_RE = re.compile(r"(?:玩家)?\d{1,2}号(?:位)?(?:玩家)?")
_REPORT_MARKERS = (
    "首先",
    "其次",
    "最后",
    "第一",
    "第二",
    "第三",
    "一是",
    "二是",
    "三是",
    "综合来看",
    "结论先",
    "总结一下",
)
_DEFER_MARKERS = ("先听", "听完", "再听", "再看", "再收", "再落", "再归票")
_REPLY_MARKERS = (
    "我赞同",
    "我同意",
    "我不赞同",
    "我不同意",
    "先回",
    "回应",
    "你刚才",
    "前置位",
)
_HEDGE_MARKERS = ("可能", "暂时", "目前", "我不确定", "先不", "保留", "未必")


def build_speech_repetition_audit(
    *,
    run_id: str,
    session_id: str,
    logs: object,
    player_configs: Sequence[Mapping[str, object]] = (),
    live_no_speech_events: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    profiles = {
        str(item.get("name") or "").strip(): item
        for item in player_configs
        if str(item.get("name") or "").strip()
    }
    turns = _public_speech_turns(logs, profiles)
    spoken = [turn for turn in turns if turn["speech_status"] == "spoken"]
    pairs = _speech_pairs(spoken)
    mission_rounds = _mission_round_summaries(turns)
    counterfactual_mission_rounds = _counterfactual_mission_round_summaries(turns)

    no_speech_reasons = Counter(
        str(turn.get("reason_code") or "unknown")
        for turn in turns
        if turn["speech_status"] == "not_spoken"
    )
    live_event_reasons = Counter(
        str(event.get("public_reason_code") or "unknown") for event in live_no_speech_events
    )
    repetition_flagged = [turn for turn in turns if turn["repetition_flagged"]]
    accepted_repetition_warnings = [
        turn for turn in spoken if "repeated_debate_phrase" in turn["quality_issue_codes"]
    ]
    detector_paradoxes = [
        turn
        for turn in turns
        if turn["quality_requires_rewrite"]
        and "repeated_debate_phrase" in turn["quality_issue_codes"]
        and float(turn["lexical_similarity"] or 0.0) < 0.1
        and float(turn["novelty_score"] or 0.0) >= 0.9
    ]
    dropped_detector_paradoxes = [
        turn for turn in detector_paradoxes if turn["speech_status"] == "not_spoken"
    ]
    historical_repetition_rewrites = [
        turn for turn in turns if "repeated_debate_phrase" in turn["quality_rewrite_codes"]
    ]
    current_boundary_rewrites = [
        turn
        for turn in historical_repetition_rewrites
        if int(turn["new_proposition_count"] or 0) == 0
        and float(turn["lexical_similarity"] or 0.0) >= REPETITION_REWRITE_THRESHOLD
    ]
    avoided_repetition_drops = [
        turn
        for turn in historical_repetition_rewrites
        if turn["speech_status"] == "not_spoken" and turn not in current_boundary_rewrites
    ]
    exact_pairs = [pair for pair in pairs if pair["exact_normalized_match"]]
    high_topic_pairs = [
        pair for pair in pairs if float(pair["bigram_cosine"]) >= _TOPIC_OVERLAP_THRESHOLD
    ]
    same_round_debate_pairs = [
        pair
        for pair in pairs
        if pair["same_round"]
        and pair["left_action"] == "debate"
        and pair["right_action"] == "debate"
    ]
    same_round_topic_pairs = [
        pair
        for pair in same_round_debate_pairs
        if float(pair["bigram_cosine"]) >= _SAME_ROUND_TOPIC_OVERLAP_THRESHOLD
    ]
    spoken_actors = {str(turn["actor"]) for turn in spoken}
    configured_actors = set(profiles)
    model_names = {str(profile.get("model") or "") for profile in profiles.values()}
    personality_ids = {str(profile.get("personality_id") or "") for profile in profiles.values()}
    strategy_profiles = {
        str(profile.get("strategy_profile") or "") for profile in profiles.values()
    }
    mission_count = sum(int(item["assigned_count"]) for item in mission_rounds)
    mission_collision_count = sum(int(item["collision_count"]) for item in mission_rounds)
    counterfactual_mission_collision_count = sum(
        int(item["collision_count"]) for item in counterfactual_mission_rounds
    )

    return {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "session_id": session_id,
        "summary": {
            "public_speech_request_count": len(turns),
            "spoken_count": len(spoken),
            "not_spoken_count": len(turns) - len(spoken),
            "not_spoken_rate": _ratio(len(turns) - len(spoken), len(turns)),
            "not_spoken_reason_counts": dict(sorted(no_speech_reasons.items())),
            "configured_actor_count": len(configured_actors),
            "spoken_actor_count": len(spoken_actors),
            "never_spoken_actors": sorted(configured_actors - spoken_actors),
            "configured_model_count": len(model_names - {""}),
            "configured_personality_id_count": len(personality_ids - {""}),
            "configured_strategy_profile_count": len(strategy_profiles - {""}),
            "quality_checked_count": sum(turn["quality_checked"] for turn in turns),
            "quality_retry_count": sum(
                int(turn["quality_attempt_count"] or 0) > 1 for turn in turns
            ),
            "quality_retry_exhausted_count": sum(
                bool(turn["quality_retry_exhausted"]) for turn in turns
            ),
            "repetition_flagged_turn_count": len(repetition_flagged),
            "repetition_flagged_rate": _ratio(
                len(repetition_flagged),
                sum(turn["quality_checked"] for turn in turns),
            ),
            "accepted_repetition_warning_count": len(accepted_repetition_warnings),
            "low_similarity_high_novelty_rewrite_count": len(detector_paradoxes),
            "low_similarity_high_novelty_dropped_count": len(dropped_detector_paradoxes),
            "repetition_rewrite_threshold": REPETITION_REWRITE_THRESHOLD,
            "historical_repetition_rewrite_count": len(historical_repetition_rewrites),
            "current_boundary_repetition_rewrite_count": len(current_boundary_rewrites),
            "counterfactual_avoided_repetition_drop_count": len(avoided_repetition_drops),
            "mission_assigned_count": mission_count,
            "mission_collision_count": mission_collision_count,
            "mission_collision_rate": _ratio(mission_collision_count, mission_count),
            "round_robin_mission_collision_count": sum(
                int(item["round_robin_collision_count"]) for item in mission_rounds
            ),
            "counterfactual_mission_collision_count": counterfactual_mission_collision_count,
            "counterfactual_avoided_mission_collision_count": max(
                0, mission_collision_count - counterfactual_mission_collision_count
            ),
            "counterfactual_round_robin_mission_collision_count": sum(
                int(item["round_robin_collision_count"]) for item in counterfactual_mission_rounds
            ),
            "counterfactual_max_consecutive_same_mission": max(
                (
                    int(item["max_consecutive_same_mission"])
                    for item in counterfactual_mission_rounds
                ),
                default=0,
            ),
            "max_consecutive_same_mission": max(
                (int(item["max_consecutive_same_mission"]) for item in mission_rounds),
                default=0,
            ),
            "speech_pair_count": len(pairs),
            "exact_duplicate_pair_count": len(exact_pairs),
            "high_topic_overlap_pair_count": len(high_topic_pairs),
            "same_round_debate_pair_count": len(same_round_debate_pairs),
            "same_round_topic_overlap_pair_count": len(same_round_topic_pairs),
            "same_round_topic_overlap_rate": _ratio(
                len(same_round_topic_pairs), len(same_round_debate_pairs)
            ),
            "max_bigram_cosine": max((float(pair["bigram_cosine"]) for pair in pairs), default=0.0),
            "max_fourgram_jaccard": max(
                (float(pair["fourgram_jaccard"]) for pair in pairs), default=0.0
            ),
        },
        "live_event_crosscheck": {
            "player_did_not_speak_count": len(live_no_speech_events),
            "reason_counts": dict(sorted(live_event_reasons.items())),
            "matches_action_log_count": len(live_no_speech_events) == len(turns) - len(spoken),
            "matches_action_log_reasons": live_event_reasons == no_speech_reasons,
        },
        "mission_rounds": mission_rounds,
        "counterfactual_mission_rounds": counterfactual_mission_rounds,
        "top_overlap_pairs": pairs[:10],
        "repeated_phrase_candidates": repeated_phrase_candidates(
            [str(turn["text"]) for turn in spoken if turn["action"] == "debate"],
            min_chars=6,
            min_count=2,
            limit=12,
        ),
        "actor_summaries": _actor_summaries(turns, profiles),
        "turns": turns,
    }


def _public_speech_turns(
    logs: object,
    profiles: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    turns: list[dict[str, object]] = []
    seen_action_ids: set[str] = set()
    for round_number, action_log in _iter_action_logs(logs):
        action = str(action_log.get("action") or "")
        if action not in _PUBLIC_SPEECH_ACTIONS:
            continue
        lm_log = action_log.get("lm_log")
        lm_log = lm_log if isinstance(lm_log, Mapping) else {}
        attempt_outcomes = lm_log.get("attempt_outcomes")
        attempt_outcomes = attempt_outcomes if isinstance(attempt_outcomes, list) else []
        action_id = str(lm_log.get("action_id") or "").strip()
        if action_id and action_id in seen_action_ids:
            continue
        if action_id:
            seen_action_ids.add(action_id)
        actor = str(action_log.get("actor") or "").strip()
        profile = profiles.get(actor, {})
        text = str(action_log.get("choice") or "").strip()
        reason_code = str(
            action_log.get("reason_code") or action_log.get("fallback_reason") or ""
        ).strip()
        status = "spoken" if text else "not_spoken"
        mission = action_log.get("speech_mission")
        mission = mission if isinstance(mission, Mapping) else {}
        report = action_log.get("speech_quality_report")
        report = report if isinstance(report, Mapping) else {}
        issues = report.get("issues")
        issues = issues if isinstance(issues, list) else []
        issue_codes = sorted(
            {
                str(issue.get("code") or "")
                for issue in issues
                if isinstance(issue, Mapping) and str(issue.get("code") or "")
            }
        )
        hard_failure_codes = report.get("hard_failure_codes")
        hard_failure_codes = hard_failure_codes if isinstance(hard_failure_codes, list) else []
        rewrite_codes = sorted(
            {
                str(issue.get("code") or "")
                for issue in issues
                if isinstance(issue, Mapping)
                and issue.get("severity") == "rewrite"
                and str(issue.get("code") or "")
            }
            | {str(code) for code in hard_failure_codes if str(code).strip()}
        )
        initial_codes = action_log.get("speech_quality_initial_codes")
        initial_codes = initial_codes if isinstance(initial_codes, list) else []
        normalized_initial_codes = sorted(
            {str(code) for code in initial_codes if str(code).strip()}
        )
        metrics = _speech_text_metrics(text)
        turns.append(
            {
                "turn_id": action_id or f"r{round_number}:{action}:{actor}:{len(turns) + 1}",
                "action_id": action_id,
                "round": round_number,
                "actor": actor,
                "seat": _int_or_none(profile.get("seat")),
                "model": str(profile.get("model") or ""),
                "personality_id": str(profile.get("personality_id") or ""),
                "strategy_profile": str(profile.get("strategy_profile") or ""),
                "action": action,
                "duration_ms": _int_or_none(action_log.get("duration_ms")),
                "execution_status": str(action_log.get("execution_status") or "") or None,
                "provider_attempt_count": len(attempt_outcomes),
                "provider_attempt_results": [
                    str(outcome.get("attempt_result") or "")
                    for outcome in attempt_outcomes
                    if isinstance(outcome, Mapping)
                ],
                "speech_status": status,
                "reason_code": reason_code or None,
                "text": text,
                "char_count": metrics["char_count"],
                "question_count": metrics["question_count"],
                "seat_reference_count": metrics["seat_reference_count"],
                "report_marker_count": metrics["report_marker_count"],
                "defer_marker_count": metrics["defer_marker_count"],
                "reply_marker_count": metrics["reply_marker_count"],
                "hedge_marker_count": metrics["hedge_marker_count"],
                "mission_kind": str(mission.get("kind") or "") or None,
                "mission_reason_code": str(mission.get("reason_code") or "") or None,
                "mission_completed": (bool(report.get("mission_completed")) if report else None),
                "quality_checked": bool(report),
                "quality_attempt_count": _int_or_none(
                    action_log.get("speech_quality_attempt_count")
                ),
                "quality_retry_exhausted": bool(action_log.get("speech_quality_retry_exhausted")),
                "quality_initial_codes": normalized_initial_codes,
                "quality_issue_codes": issue_codes,
                "quality_rewrite_codes": rewrite_codes,
                "quality_requires_rewrite": bool(report.get("requires_rewrite")),
                "novelty_score": _float_or_none(report.get("novelty_score")),
                "lexical_similarity": _float_or_none(report.get("lexical_similarity")),
                "new_proposition_count": _int_or_none(report.get("new_proposition_count")),
                "repetition_flagged": bool(
                    _REPETITION_CODES & set(normalized_initial_codes + issue_codes)
                ),
            }
        )
    return turns


def _iter_action_logs(logs: object) -> Iterable[tuple[int, Mapping[str, object]]]:
    if not isinstance(logs, list):
        return
    for round_index, round_log in enumerate(logs, start=1):
        if not isinstance(round_log, Mapping):
            continue
        raw_round = round_log.get("number")
        round_number = raw_round if type(raw_round) is int else round_index
        yield from _walk_action_logs(round_log, round_number)


def _walk_action_logs(
    value: object,
    round_number: int,
) -> Iterable[tuple[int, Mapping[str, object]]]:
    if isinstance(value, Mapping):
        if value.get("action"):
            yield round_number, value
        for child in value.values():
            yield from _walk_action_logs(child, round_number)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_action_logs(child, round_number)


def _mission_round_summaries(turns: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    grouped: dict[int, list[tuple[str, str]]] = {}
    for turn in turns:
        if turn.get("action") != "debate":
            continue
        round_number = int(turn.get("round") or 0)
        mission = str(turn.get("mission_kind") or "")
        if mission:
            grouped.setdefault(round_number, []).append(
                (mission, str(turn.get("mission_reason_code") or ""))
            )
    return [
        _mission_round_summary(round_number, assignments)
        for round_number, assignments in sorted(grouped.items())
    ]


def _counterfactual_mission_round_summaries(
    turns: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[int, list[Mapping[str, object]]] = {}
    for turn in turns:
        if turn.get("action") == "debate":
            grouped.setdefault(int(turn.get("round") or 0), []).append(turn)

    summaries: list[dict[str, object]] = []
    for round_number, round_turns in sorted(grouped.items()):
        speech_order = [str(turn.get("actor") or "") for turn in round_turns]
        prior_messages: list[str] = []
        assignments: list[tuple[str, str]] = []
        for turn in round_turns:
            if turn.get("mission_kind"):
                mission = assign_speech_mission(
                    round_number=round_number,
                    stage="debate",
                    speaker=str(turn.get("actor") or ""),
                    speech_order=speech_order,
                    prior_messages=prior_messages,
                    personality_id=str(turn.get("personality_id") or "balanced"),
                    has_public_evidence=(
                        turn.get("mission_reason_code") != "limited_public_evidence"
                    ),
                )
                assignments.append((mission.kind, mission.reason_code))
            text = str(turn.get("text") or "").strip()
            if text:
                prior_messages.append(text)
        if assignments:
            summaries.append(_mission_round_summary(round_number, assignments))
    return summaries


def _mission_round_summary(
    round_number: int,
    assignments: Sequence[tuple[str, str]],
) -> dict[str, object]:
    missions = [kind for kind, _reason in assignments]
    reasons = [reason for _kind, reason in assignments]
    distribution = Counter(missions)
    round_robin_missions = [kind for kind, reason in assignments if reason == "round_robin"]
    return {
        "round": round_number,
        "assigned_count": len(missions),
        "mission_distribution": dict(sorted(distribution.items())),
        "mission_sequence": missions,
        "reason_sequence": reasons,
        "collision_count": len(missions) - len(distribution),
        "round_robin_collision_count": len(round_robin_missions) - len(set(round_robin_missions)),
        "max_consecutive_same_mission": _max_consecutive_same(missions),
    }


def _speech_pairs(spoken: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    pairs: list[dict[str, object]] = []
    for left_index, left in enumerate(spoken):
        for right in spoken[left_index + 1 :]:
            left_text = str(left.get("text") or "")
            right_text = str(right.get("text") or "")
            normalized_left = normalize_dialogue_text(left_text)
            normalized_right = normalize_dialogue_text(right_text)
            pairs.append(
                {
                    "left_turn_id": left.get("turn_id"),
                    "right_turn_id": right.get("turn_id"),
                    "left_round": left.get("round"),
                    "right_round": right.get("round"),
                    "left_actor": left.get("actor"),
                    "right_actor": right.get("actor"),
                    "left_action": left.get("action"),
                    "right_action": right.get("action"),
                    "same_round": left.get("round") == right.get("round"),
                    "same_actor": left.get("actor") == right.get("actor"),
                    "exact_normalized_match": normalized_left == normalized_right,
                    "bigram_cosine": round(
                        _ngram_cosine(normalized_left, normalized_right, size=2), 4
                    ),
                    "fourgram_jaccard": round(
                        _ngram_jaccard(normalized_left, normalized_right, size=4), 4
                    ),
                    "shared_phrases": repeated_phrase_candidates(
                        [left_text, right_text], min_chars=6, min_count=2, limit=4
                    ),
                }
            )
    return sorted(
        pairs,
        key=lambda item: (
            -float(item["bigram_cosine"]),
            -float(item["fourgram_jaccard"]),
            str(item["left_turn_id"]),
        ),
    )


def _actor_summaries(
    turns: Sequence[Mapping[str, object]],
    profiles: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = {actor: [] for actor in profiles}
    for turn in turns:
        grouped.setdefault(str(turn.get("actor") or ""), []).append(turn)
    summaries: list[dict[str, object]] = []
    for actor, actor_turns in grouped.items():
        profile = profiles.get(actor, {})
        spoken = [turn for turn in actor_turns if turn.get("speech_status") == "spoken"]
        summaries.append(
            {
                "actor": actor,
                "seat": _int_or_none(profile.get("seat")),
                "model": str(profile.get("model") or ""),
                "personality_id": str(profile.get("personality_id") or ""),
                "strategy_profile": str(profile.get("strategy_profile") or ""),
                "request_count": len(actor_turns),
                "spoken_count": len(spoken),
                "not_spoken_count": len(actor_turns) - len(spoken),
                "mean_char_count": _mean([float(turn.get("char_count") or 0) for turn in spoken]),
                "question_count": sum(int(turn.get("question_count") or 0) for turn in spoken),
                "defer_marker_count": sum(
                    int(turn.get("defer_marker_count") or 0) for turn in spoken
                ),
            }
        )
    return sorted(summaries, key=lambda item: (item["seat"] is None, item["seat"] or 0))


def _speech_text_metrics(text: str) -> dict[str, int]:
    return {
        "char_count": len(text.strip()),
        "seat_reference_count": len(_SEAT_REFERENCE_RE.findall(text)),
        "question_count": text.count("？") + text.count("?"),
        "report_marker_count": _marker_count(text, _REPORT_MARKERS),
        "defer_marker_count": _marker_count(text, _DEFER_MARKERS),
        "reply_marker_count": _marker_count(text, _REPLY_MARKERS),
        "hedge_marker_count": _marker_count(text, _HEDGE_MARKERS),
    }


def _marker_count(text: str, markers: Sequence[str]) -> int:
    return sum(text.count(marker) for marker in markers)


def _ngram_cosine(left: str, right: str, *, size: int) -> float:
    left_counts = Counter(_ngrams(left, size))
    right_counts = Counter(_ngrams(right, size))
    if not left_counts or not right_counts:
        return 0.0
    numerator = sum(count * right_counts.get(gram, 0) for gram, count in left_counts.items())
    denominator = math.sqrt(
        sum(count * count for count in left_counts.values())
        * sum(count * count for count in right_counts.values())
    )
    return numerator / denominator if denominator else 0.0


def _ngram_jaccard(left: str, right: str, *, size: int) -> float:
    left_grams = set(_ngrams(left, size))
    right_grams = set(_ngrams(right, size))
    union = left_grams | right_grams
    return len(left_grams & right_grams) / len(union) if union else 0.0


def _ngrams(text: str, size: int) -> list[str]:
    if len(text) < size:
        return []
    return [text[index : index + size] for index in range(len(text) - size + 1)]


def _max_consecutive_same(values: Sequence[str]) -> int:
    maximum = 0
    current = 0
    previous = None
    for value in values:
        current = current + 1 if value == previous else 1
        maximum = max(maximum, current)
        previous = value
    return maximum


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _int_or_none(value: object) -> int | None:
    return value if type(value) is int else None


def _float_or_none(value: object) -> float | None:
    return float(value) if type(value) in {int, float} else None


def _load_run_inputs(
    run_id: str,
) -> tuple[LiveRunRecord, object, list[dict[str, object]]]:
    with SessionLocal() as db:
        run = db.get(LiveRunRecord, run_id)
        if run is None:
            raise RuntimeError(f"live run not found: {run_id}")
        replay = db.get(GameReplayPayload, run.session_id)
        if replay is None:
            raise RuntimeError(f"replay payload not found: {run.session_id}")
        events = list(
            db.scalars(
                select(LiveEventRecord)
                .where(
                    LiveEventRecord.run_id == run_id,
                    LiveEventRecord.type == "player_did_not_speak",
                )
                .order_by(LiveEventRecord.event_id)
            )
        )
        event_payloads = [
            {
                "event_id": event.event_id,
                "round": event.round,
                "actor": event.actor,
                "action": event.action,
                "public_reason_code": event.payload.get("public_reason_code"),
            }
            for event in events
        ]
        db.expunge(run)
        return run, replay.logs, event_payloads


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit game-level public speech repetition and no-speech causes."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run, logs, live_no_speech_events = _load_run_inputs(args.run_id)
    report = build_speech_repetition_audit(
        run_id=run.run_id,
        session_id=run.session_id,
        logs=logs,
        player_configs=run.player_configs,
        live_no_speech_events=live_no_speech_events,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
