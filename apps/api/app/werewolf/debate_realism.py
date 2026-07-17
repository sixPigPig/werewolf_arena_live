from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from app.werewolf.player_configs import PlayerConfig, player_config_from_dict
from app.werewolf.lineup_quality import evaluate_lineup_quality, legacy_lineup_warnings

PUNCTUATION_RE = re.compile(r"[\s，。！？、；：,.!?;:\"'《》（）()【】\[\]{}<>-]+")
CATCHPHRASE_LINE_RE = re.compile(r"^常用表达:\s*(.+)$", re.MULTILINE)
CATCHPHRASE_SPLIT_RE = re.compile(r"[；;、,，\n]+")
PLAYER_REFERENCE_RE = re.compile(
    r"^(?:玩家)?(?:\d{1,2}|[一二三四五六七八九十]{1,3})号(?:位)?(?:玩家)?$"
)
PLAYER_REFERENCE_IN_TEXT_RE = re.compile(
    r"(?:玩家)?(?:\d{1,2}|[一二三四五六七八九十]{1,3})号(?:位)?(?:玩家)?"
)
LOW_NOVELTY_THRESHOLD = 0.45
SPEECH_MISSION_KINDS = (
    "fact_checker",
    "vote_analyst",
    "contradiction_hunter",
    "devil_advocate",
    "risk_controller",
    "consolidator",
)
SpeechMissionKind = Literal[
    "fact_checker",
    "vote_analyst",
    "contradiction_hunter",
    "devil_advocate",
    "risk_controller",
    "consolidator",
]
SpeechQualitySeverity = Literal["warning", "rewrite"]
_MISSION_INSTRUCTIONS: dict[SpeechMissionKind, str] = {
    "fact_checker": "纠正或确认一条已经公开发生的事实，并说明它如何影响当前判断。",
    "vote_analyst": "解释一处已有票型、警徽或站边变化，并给出你的票口。",
    "contradiction_hunter": "指出一名玩家前后表述中的具体矛盾或需要回答的问题。",
    "devil_advocate": "对当前多数结论提出最强反例或尚未排除的风险。",
    "risk_controller": "说明判断失败的成本、轮次资源或终局风险，并给出稳妥方案。",
    "consolidator": "合并已有公开信息，形成一个明确且下一步可验证的结论。",
}
_MISSION_COMPLETION_MARKERS: dict[SpeechMissionKind, tuple[str, ...]] = {
    "fact_checker": ("事实", "确认", "纠正", "记录", "实际", "票型"),
    "vote_analyst": ("票", "投", "改票", "上票", "警徽", "站边"),
    "contradiction_hunter": ("矛盾", "前后", "改口", "不一致", "解释", "回答"),
    "devil_advocate": ("但是", "反过来", "未必", "反例", "不同意", "不能排除"),
    "risk_controller": ("风险", "代价", "输", "终局", "轮次", "资源", "不能出错"),
    "consolidator": ("综合", "总结", "因此", "结论", "今天", "下一步", "票"),
}
_AGREEMENT_MARKERS = ("同意", "赞同", "跟票", "也投", "支持", "站边")
_DISAGREEMENT_MARKERS = ("不同意", "不赞同", "反对", "未必", "不能跟")
_SEAT_REFERENCE = r"(?:玩家)?(\d{1,2})号(?:位)?(?:玩家)?"
_PLAYER_VOTE_PATTERN = re.compile(
    rf"{_SEAT_REFERENCE}.{{0,12}}?(?:投|票给|改票|上票).{{0,4}}?{_SEAT_REFERENCE}"
)
_ACTOR_TARGET_PATTERN = re.compile(
    rf"(?:投|票给|放逐|出|怀疑|认狼|踩|保|信|站边).{{0,6}}?{_SEAT_REFERENCE}"
)
_IDENTITY_PATTERN = re.compile(
    rf"{_SEAT_REFERENCE}[^，。！？；;,.!?]{{0,8}}?"
    r"(不是|不像|是|像)(狼人|狼|好人|预言家|女巫|猎人|守卫|村民)"
)
COMMON_GAME_ANCHORS = {
    "预言家查验",
    "预言家发言",
    "女巫用药",
    "猎人开枪",
    "守卫守护",
    "狼人阵营",
    "好人阵营",
    "村民身份",
    "平民身份",
    "角色身份",
    "身份信息",
    "身份声明",
    "查验结果",
    "投票位置",
    "投票行为",
    "投票记录",
    "投票理由",
    "投票解释",
    "发言顺序",
    "发言位置",
    "发言内容",
    "站边理由",
    "票型信息",
    "票型位置",
    "倒牌信息",
    "夜间信息",
    "上票位置",
    "警上发言",
    "警下发言",
    "出局玩家",
}
PUBLIC_SPEECH_CHARACTER_LIMITS: dict[str, int] = {
    "sheriff_speech": 180,
    "debate": 220,
    "sheriff_pk_speech": 180,
    "exile_pk_speech": 180,
    "exile_last_words": 150,
    "werewolf_discuss": 60,
    "werewolf_kill_vote": 60,
}
_ROLE_TERM_RE = re.compile(r"查杀|金水|好人|狼人|狼")
_ROLE_TERM_AFTER_SEAT_RE = re.compile(
    rf"{_SEAT_REFERENCE}"
    r"(?:这张牌)?(?:也|又|仍然|还是|同时|更)?"
    r"(?:是|为|像|偏像|更像|我认|我认为)?"
    r"(查杀|金水|好人|狼人|狼)"
)
_ROLE_TERM_BEFORE_SEAT_RE = re.compile(
    rf"(查杀|金水)(?:牌|结果)?(?:是|给|发给|了)?{_SEAT_REFERENCE}"
)
_REPORTED_ROLE_CLAIM_RE = re.compile(
    rf"(?:据|听)?{_SEAT_REFERENCE}[^，。！？；;,.!?\n]{{0,8}}?"
    r"(?:说|表示|认为|觉得|声称|宣称|判断|认定|提到|强调|坚持|发言称|的结论|的观点)"
)
_REPORTED_ROLE_PRONOUN_RE = re.compile(
    r"(?:他|她|对方|有人|前置位|后置位)(?:说|表示|认为|觉得|声称|宣称|判断|认定|提到)"
)
_ROLE_ASSERTION_SEGMENT_SPLIT_RE = re.compile(
    r"[，。！？；;,.!?\n]+|(?=但(?:是)?|不过|然而|而我|可我)"
)
_SENTENCE_ENDINGS = frozenset("。！？!?；;")
_SAFE_SPEECH_FALLBACK = "本轮暂不追加判断。"


@dataclass(frozen=True)
class SpeechMissionV1:
    schema_version: int
    kind: SpeechMissionKind
    instruction: str
    reason_code: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "instruction": self.instruction,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, order=True)
class PropositionSignatureV1:
    subject: str
    predicate: str
    object: str
    polarity: Literal["positive", "negative"]
    start: int
    end: int

    def semantic_key(self) -> tuple[str, str, str, str]:
        return (self.subject, self.predicate, self.object, self.polarity)

    def to_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "polarity": self.polarity,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class SpeechQualityIssueV1:
    code: str
    severity: SpeechQualitySeverity
    score: float
    evidence_spans: tuple[tuple[int, int], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "score": round(self.score, 4),
            "evidence_spans": [list(span) for span in self.evidence_spans],
        }


@dataclass(frozen=True)
class SpeechQualityReportV1:
    schema_version: int
    mission_kind: SpeechMissionKind
    mission_completed: bool
    novelty_score: float
    lexical_similarity: float
    new_proposition_count: int
    proposition_signatures: tuple[PropositionSignatureV1, ...]
    issues: tuple[SpeechQualityIssueV1, ...]

    @property
    def requires_rewrite(self) -> bool:
        return any(issue.severity == "rewrite" for issue in self.issues)

    @property
    def hard_failure_codes(self) -> list[str]:
        return [issue.code for issue in self.issues if issue.severity == "rewrite"]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mission_kind": self.mission_kind,
            "mission_completed": self.mission_completed,
            "novelty_score": round(self.novelty_score, 4),
            "lexical_similarity": round(self.lexical_similarity, 4),
            "new_proposition_count": self.new_proposition_count,
            "proposition_signatures": [
                signature.to_dict() for signature in self.proposition_signatures
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "requires_rewrite": self.requires_rewrite,
        }


def assign_speech_mission(
    *,
    round_number: int,
    stage: str,
    speaker: str,
    speech_order: list[str] | tuple[str, ...],
    prior_messages: list[str] | tuple[str, ...] = (),
    personality_id: str = "balanced",
    has_public_evidence: bool = True,
) -> SpeechMissionV1:
    agreement_target = _consecutive_unsupported_agreement_target(prior_messages)
    if agreement_target is not None:
        kind: SpeechMissionKind = "devil_advocate"
        reason_code = "consecutive_agreement_without_evidence"
    else:
        try:
            position = list(speech_order).index(speaker)
        except ValueError:
            position = len(prior_messages)
        digest = hashlib.sha256(
            f"{round_number}:{stage}:{personality_id}".encode()
        ).digest()
        offset = digest[0] % len(SPEECH_MISSION_KINDS)
        kind = SPEECH_MISSION_KINDS[(offset + position) % len(SPEECH_MISSION_KINDS)]
        reason_code = "round_robin"
        if not has_public_evidence and kind in {
            "fact_checker",
            "vote_analyst",
            "contradiction_hunter",
        }:
            kind = "consolidator"
            reason_code = "limited_public_evidence"
    return SpeechMissionV1(
        schema_version=1,
        kind=kind,
        instruction=_MISSION_INSTRUCTIONS[kind],
        reason_code=reason_code,
    )


def speech_mission_from_dict(data: object) -> SpeechMissionV1:
    payload = data if isinstance(data, dict) else {}
    raw_kind = str(payload.get("kind") or "consolidator")
    kind: SpeechMissionKind = (
        raw_kind if raw_kind in SPEECH_MISSION_KINDS else "consolidator"  # type: ignore[assignment]
    )
    return SpeechMissionV1(
        schema_version=1,
        kind=kind,
        instruction=str(payload.get("instruction") or _MISSION_INSTRUCTIONS[kind]),
        reason_code=str(payload.get("reason_code") or "legacy_default"),
    )


def proposition_signatures(
    text: str,
    *,
    actor: str = "speaker",
) -> tuple[PropositionSignatureV1, ...]:
    signatures: list[PropositionSignatureV1] = []
    for match in _PLAYER_VOTE_PATTERN.finditer(text):
        signatures.append(
            PropositionSignatureV1(
                subject=f"seat:{int(match.group(1))}",
                predicate="vote",
                object=f"seat:{int(match.group(2))}",
                polarity="negative" if _span_is_negated(text, match.start()) else "positive",
                start=match.start(),
                end=match.end(),
            )
        )
    for match in _IDENTITY_PATTERN.finditer(text):
        signatures.append(
            PropositionSignatureV1(
                subject=f"seat:{int(match.group(1))}",
                predicate="identity",
                object=match.group(3),
                polarity="negative" if match.group(2) in {"不是", "不像"} else "positive",
                start=match.start(),
                end=match.end(),
            )
        )
    for match in _ACTOR_TARGET_PATTERN.finditer(text):
        signatures.append(
            PropositionSignatureV1(
                subject=actor,
                predicate=_target_predicate(match.group(0)),
                object=f"seat:{int(match.group(1))}",
                polarity="negative" if _span_is_negated(text, match.start()) else "positive",
                start=match.start(),
                end=match.end(),
            )
        )
    unique: dict[tuple[str, str, str, str], PropositionSignatureV1] = {}
    for signature in signatures:
        unique.setdefault(signature.semantic_key(), signature)
    return tuple(sorted(unique.values(), key=lambda item: (item.start, item.end)))


def evaluate_speech_quality(
    *,
    text: str,
    mission: SpeechMissionV1,
    prior_texts: list[str] | tuple[str, ...] = (),
    personality: str = "",
    actor: str = "speaker",
) -> SpeechQualityReportV1:
    prior = [str(item) for item in prior_texts if str(item).strip()]
    signatures = proposition_signatures(text, actor=actor)
    prior_signature_keys = {
        signature.semantic_key()
        for prior_text in prior
        for signature in proposition_signatures(prior_text, actor=actor)
    }
    new_signatures = [
        signature
        for signature in signatures
        if signature.semantic_key() not in prior_signature_keys
    ]
    similarity = _max_fourgram_jaccard(text, prior)
    mission_completed = _mission_completed(text, mission.kind)
    novelty_score = min(
        1.0,
        max(1.0 - similarity, min(1.0, len(new_signatures) / 2 + 0.25)),
    )
    issues: list[SpeechQualityIssueV1] = []
    legacy_warnings = dialogue_quality_warnings(
        text=text,
        prior_texts=prior,
        personality=personality,
    )
    whole_text_span = ((0, len(text)),) if text else ()

    if "repeated_debate_phrase" in legacy_warnings:
        issues.append(
            SpeechQualityIssueV1(
                code="repeated_debate_phrase",
                severity="rewrite" if not new_signatures else "warning",
                score=similarity,
                evidence_spans=whole_text_span,
            )
        )
    if not new_signatures and similarity >= LOW_NOVELTY_THRESHOLD:
        issues.append(
            SpeechQualityIssueV1(
                code="low_proposition_novelty",
                severity="rewrite" if not mission_completed else "warning",
                score=1.0 - novelty_score,
                evidence_spans=whole_text_span,
            )
        )
    if (
        mission.kind in {"devil_advocate", "fact_checker"}
        and _is_unsupported_agreement(text)
        and not new_signatures
    ):
        issues.append(
            SpeechQualityIssueV1(
                code="group_agreement_without_evidence",
                severity="rewrite",
                score=1.0,
                evidence_spans=whole_text_span,
            )
        )
    catchphrase_coverage = _catchphrase_coverage(text, personality)
    if "catchphrase_overuse" in legacy_warnings:
        issues.append(
            SpeechQualityIssueV1(
                code=(
                    "catchphrase_dominates_speech"
                    if catchphrase_coverage >= 0.35
                    else "catchphrase_overuse"
                ),
                severity="rewrite" if catchphrase_coverage >= 0.35 else "warning",
                score=catchphrase_coverage,
                evidence_spans=whole_text_span,
            )
        )
    if not mission_completed:
        issues.append(
            SpeechQualityIssueV1(
                code="mission_not_completed",
                severity="warning",
                score=0.0,
            )
        )

    return SpeechQualityReportV1(
        schema_version=1,
        mission_kind=mission.kind,
        mission_completed=mission_completed,
        novelty_score=novelty_score,
        lexical_similarity=similarity,
        new_proposition_count=len(new_signatures),
        proposition_signatures=signatures,
        issues=tuple(_deduplicate_quality_issues(issues)),
    )


def contradictory_role_targets(text: str) -> set[str]:
    """Return public seat numbers assigned both good and wolf-aligned labels."""

    labels_by_target: dict[str, set[str]] = {}

    def add_label(target: str, term: str) -> None:
        label = "good" if term in {"金水", "好人"} else "wolf"
        labels_by_target.setdefault(str(int(target)), set()).add(label)

    for segment in _ROLE_ASSERTION_SEGMENT_SPLIT_RE.split(text):
        clause = segment.strip()
        if not clause or _is_reported_role_claim(clause):
            continue
        for match in _ROLE_TERM_AFTER_SEAT_RE.finditer(clause):
            add_label(match.group(1), match.group(2))
        for match in _ROLE_TERM_BEFORE_SEAT_RE.finditer(clause):
            add_label(match.group(2), match.group(1))

        targets = {
            str(int(match.group(1)))
            for match in re.finditer(_SEAT_REFERENCE, clause)
        }
        if len(targets) != 1:
            continue
        target = next(iter(targets))
        for term in _ROLE_TERM_RE.findall(clause):
            add_label(target, term)

    return {
        target
        for target, labels in labels_by_target.items()
        if labels == {"good", "wolf"}
    }


def _is_reported_role_claim(clause: str) -> bool:
    return bool(
        _REPORTED_ROLE_CLAIM_RE.search(clause)
        or _REPORTED_ROLE_PRONOUN_RE.search(clause)
    )


def speech_character_limit(action: str) -> int | None:
    return PUBLIC_SPEECH_CHARACTER_LIMITS.get(action)


def speech_length_violation(action: str, text: str) -> str | None:
    limit = speech_character_limit(action)
    if limit is None or _speech_character_count(text) <= limit:
        return None
    return "speech_too_long"


def truncate_speech_to_complete_sentence(
    text: str,
    *,
    max_chars: int,
    fallback: str = _SAFE_SPEECH_FALLBACK,
) -> str:
    normalized = text.strip()
    if max_chars <= 0:
        return ""
    if _speech_character_count(normalized) <= max_chars:
        return normalized

    prefix = _prefix_with_character_budget(normalized, max_chars)
    boundary = max(
        (index for index, character in enumerate(prefix) if character in _SENTENCE_ENDINGS),
        default=-1,
    )
    if boundary >= 0:
        return prefix[: boundary + 1].strip()

    safe_fallback = fallback.strip() or _SAFE_SPEECH_FALLBACK
    if _speech_character_count(safe_fallback) <= max_chars:
        return safe_fallback
    return _prefix_with_character_budget(_SAFE_SPEECH_FALLBACK, max_chars).strip()


def normalize_dialogue_text(text: str) -> str:
    return PUNCTUATION_RE.sub("", text.strip())


def _speech_character_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _prefix_with_character_budget(text: str, max_chars: int) -> str:
    accepted: list[str] = []
    used = 0
    for character in text:
        if not character.isspace():
            if used >= max_chars:
                break
            used += 1
        accepted.append(character)
    return "".join(accepted)


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
    first_seen: dict[str, int] = {}
    for text in texts:
        seen_for_text: set[str] = set()
        for normalized in _phrase_candidate_fragments(text):
            max_chars = min(8, len(normalized))
            for size in range(min_chars, max_chars + 1):
                for index in range(0, len(normalized) - size + 1):
                    phrase = normalized[index : index + size]
                    if _is_weak_phrase(phrase):
                        continue
                    seen_for_text.add(phrase)
                    first_seen.setdefault(phrase, len(first_seen))
        counts.update(seen_for_text)

    phrases: list[str] = []
    ranked = sorted(counts.items(), key=lambda item: (-item[1], len(item[0]), first_seen[item[0]]))
    for phrase, count in ranked:
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
    normalized_catchphrases: list[str] = []
    for phrase in catchphrases_from_personality(personality):
        normalized_phrase = normalize_dialogue_text(phrase)
        if normalized_phrase:
            normalized_catchphrases.append(normalized_phrase)
    normalized_prior = [
        normalize_dialogue_text(str(item)) for item in prior_texts if str(item).strip()
    ]
    for phrase in normalized_catchphrases:
        current_count = normalized.count(phrase)
        if current_count == 0:
            continue
        prior_count = sum(prior_text.count(phrase) for prior_text in normalized_prior)
        if prior_count > 0 or current_count + prior_count > 1:
            warnings.append("catchphrase_overuse")
            break

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
    if speaker in active_players:
        position = active_players.index(speaker) + 1
    else:
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
    return legacy_lineup_warnings(
        evaluate_lineup_quality(configs, player_count=len(configs))
    )


def lineup_quality_warnings_from_players(players: list[dict[str, Any]]) -> list[dict[str, str]]:
    configs: list[PlayerConfig] = []
    for index, player in enumerate(players, start=1):
        if not isinstance(player, dict):
            continue
        data = dict(player)
        if data.get("seat") is None:
            data["seat"] = index
        configs.append(player_config_from_dict(data))
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


def _phrase_candidate_fragments(text: str) -> list[str]:
    normalized = normalize_dialogue_text(text)
    without_player_refs = PLAYER_REFERENCE_IN_TEXT_RE.sub(" ", normalized)
    return [fragment for fragment in without_player_refs.split() if fragment]


def _is_weak_phrase(phrase: str) -> bool:
    return (
        len(set(phrase)) <= 1
        or phrase.isdigit()
        or PLAYER_REFERENCE_RE.fullmatch(phrase) is not None
        or _is_common_game_anchor(phrase)
    )


def _is_common_game_anchor(phrase: str) -> bool:
    return any(phrase in anchor or anchor in phrase for anchor in COMMON_GAME_ANCHORS)


def _consecutive_unsupported_agreement_target(
    prior_messages: list[str] | tuple[str, ...],
) -> str | None:
    if len(prior_messages) < 2:
        return None
    targets: list[str] = []
    for message in prior_messages[-2:]:
        if not _is_unsupported_agreement(message):
            return None
        references = PLAYER_REFERENCE_IN_TEXT_RE.findall(message)
        if not references:
            return None
        target_match = re.search(_SEAT_REFERENCE, references[-1])
        if target_match is None:
            return None
        targets.append(target_match.group(1))
    return targets[0] if targets[0] == targets[1] else None


def _is_unsupported_agreement(text: str) -> bool:
    normalized = normalize_dialogue_text(text)
    if any(marker in normalized for marker in _DISAGREEMENT_MARKERS):
        return False
    if not any(marker in normalized for marker in _AGREEMENT_MARKERS):
        return False
    evidence_markers = ("因为", "票型", "发言", "查验", "改票", "矛盾", "事实", "记录")
    return not any(marker in normalized for marker in evidence_markers)


def _span_is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 4) : start]
    return any(marker in prefix for marker in ("不", "别", "不能", "不要", "未"))


def _target_predicate(fragment: str) -> str:
    if any(marker in fragment for marker in ("投", "票给", "放逐", "出")):
        return "vote"
    if any(marker in fragment for marker in ("保", "信", "站边")):
        return "support"
    return "suspect"


def _max_fourgram_jaccard(text: str, prior_texts: list[str]) -> float:
    current = _ngrams(normalize_dialogue_text(text), 4)
    if not current:
        return 0.0
    maximum = 0.0
    for prior_text in prior_texts:
        previous = _ngrams(normalize_dialogue_text(prior_text), 4)
        union = current | previous
        if union:
            maximum = max(maximum, len(current & previous) / len(union))
    return maximum


def _mission_completed(text: str, kind: SpeechMissionKind) -> bool:
    normalized = normalize_dialogue_text(text)
    return any(marker in normalized for marker in _MISSION_COMPLETION_MARKERS[kind])


def _catchphrase_coverage(text: str, personality: str) -> float:
    normalized = normalize_dialogue_text(text)
    if not normalized:
        return 0.0
    covered = 0
    for phrase in catchphrases_from_personality(personality):
        normalized_phrase = normalize_dialogue_text(phrase)
        if normalized_phrase:
            covered += normalized.count(normalized_phrase) * len(normalized_phrase)
    return min(1.0, covered / len(normalized))


def _deduplicate_quality_issues(
    issues: list[SpeechQualityIssueV1],
) -> list[SpeechQualityIssueV1]:
    deduplicated: dict[str, SpeechQualityIssueV1] = {}
    for issue in issues:
        existing = deduplicated.get(issue.code)
        if existing is None or (
            existing.severity == "warning" and issue.severity == "rewrite"
        ):
            deduplicated[issue.code] = issue
    return list(deduplicated.values())
