from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any

from app.v2.model_context_contract import DISCOURSE_LEDGER_SCHEMA_VERSION


_SENTENCE = re.compile(r"[^。！？!?]+[。！？!?]?")
_SEAT_REFERENCE = re.compile(r"(?<!\d)(?:seat_)?(2[0-9]|1[0-9]|[1-9])号?")
_ADDRESSED_SEAT = re.compile(
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号(?:玩家)?(?:你|请|先|能不能|为什么|怎么|到底)?"
)
_PAST_NIGHT = re.compile(r"(?:昨晚|昨夜|首夜|第一晚|第一夜)")
_FUTURE_NIGHT = re.compile(r"(?:今晚|今夜|明晚|明夜|下一晚|下晚|警徽流)")
_INVESTIGATION = re.compile(r"(?:查验|验|摸)")
_FIRST_PARTY_FUTURE_INVESTIGATION = re.compile(
    r"(?:"
    r"(?:今晚|今夜|明晚|明夜|下一晚|下晚)[^。！？!?]{0,16}"
    r"我(?:会|准备|打算|要)?[^。！？!?]{0,28}"
    r"(?:查验|去验|验(?:警上|警下|最|发言|2[0-9]号|1[0-9]号|[1-9]号))"
    r"|"
    r"我(?:会|准备|打算|要)[^。！？!?]{0,28}"
    r"(?:查验|去验|验(?:警上|警下|最|发言|2[0-9]号|1[0-9]号|[1-9]号))"
    r")"
)
_INVESTIGATION_TARGET = re.compile(
    r"(?:查验|验|摸|首验)(?:的?是|了)?(?:警上|警下)?(?:的)?"
    r"(?P<seat>2[0-9]|1[0-9]|[1-9])号"
)
_ROLE_CLAIM = re.compile(
    r"(?:我是|我跳|我拍|我底牌是|底牌)(?:一张|真)?"
    r"(?P<role>预言家|女巫|猎人|白痴|守卫|村民|好人|狼人)"
)
_SELF_PAST_INVESTIGATION = re.compile(
    r"(?:我[^。！？]{0,8}(?:昨晚|昨夜|首夜|第一晚|第一夜)|"
    r"(?:昨晚|昨夜|首夜|第一晚|第一夜)[^。！？]{0,8}我)"
    r"[^。！？]{0,24}(?:查验|验|摸)"
)
_DIRECT_QUESTION = re.compile(
    r"(?:我(?:现在|想|要)?问|请.{0,12}回答|"
    r"你.{0,18}(?:谁|什么|怎么|为什么|能不能|是否|哪|几号|号码))"
)
_SINGULAR_ADDRESSEE_CONTINUATION = re.compile(r"^\s*你(?!们)")
_OTHER_QUESTION_REPORT = re.compile(r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号.{0,12}(?:问|追问)")
_SECONDARY_REPORT = re.compile(
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号.{0,18}"
    r"(?:说|表示|问|追问|回答|回应|只说|提过|报了|报过|声称|点过|认为)"
)
_SECONDARY_ACTION_ACCOUNT = re.compile(
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号[^。！？!?]{0,80}"
    r"(?:昨晚|昨夜|首夜|第一晚|第一夜)[^。！？!?]{0,24}(?:查验|验|摸)"
)
_VOTE_TARGET = re.compile(
    r"(?:投|票给|归票(?:给)?|今天出|先出)"
    r"(?P<seat>2[0-9]|1[0-9]|[1-9])号"
)
_ASSESSMENT_TERMS = (
    "怀疑",
    "认下",
    "保",
    "站边",
    "打",
    "像狼",
    "好人",
    "金水",
    "查杀",
)
_RESPONSE_REPORT_TERMS = (
    "问",
    "追问",
    "回答",
    "回应",
    "只说",
    "没给",
    "没有给",
)
_ROLE_KEYS = {
    "预言家": "seer",
    "女巫": "witch",
    "猎人": "hunter",
    "白痴": "idiot",
    "守卫": "guard",
    "村民": "villager",
    "好人": "good",
    "狼人": "werewolf",
}


def build_public_discourse_ledger(
    statements: Iterable[dict[str, Any]],
    *,
    current_round_no: int,
    actor_ref: str | None = None,
) -> dict[str, Any]:
    del actor_ref
    utterances = _normalize_utterances(statements)
    claims: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    fully_interpreted_sources: set[str] = set()

    for utterance in utterances:
        source_id = str(utterance["source_event_id"])
        last_addressed_to: str | None = None
        sentences = _sentences(str(utterance["speech"]))
        utterance_claims_seer = any(
            match.group("role") == "预言家"
            for match in _ROLE_CLAIM.finditer(str(utterance["speech"]))
        )
        all_sentences_interpreted = bool(sentences)
        for sentence_index, sentence in enumerate(sentences, start=1):
            question, last_addressed_to = _extract_question(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                last_addressed_to=last_addressed_to,
            )
            if question is not None:
                questions.append(question)

            sentence_claims = _extract_claims(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                utterance_claims_seer=utterance_claims_seer,
            )
            if sentence_claims:
                claims.extend(sentence_claims)
            if question is None and not sentence_claims:
                all_sentences_interpreted = False
        if all_sentences_interpreted:
            fully_interpreted_sources.add(source_id)

    resolved_questions, relations = _resolve_questions(
        questions,
        utterances=utterances,
    )

    return {
        "ledger_schema_version": DISCOURSE_LEDGER_SCHEMA_VERSION,
        "source_rules": {
            "judge_facts": "authoritative",
            "player_claims": "unverified_even_when_repeated",
            "first_party_source_priority": "higher_than_secondary_paraphrase",
            "statement_order": ("record_seq 升序；record_seq 缺失时沿用公开历史输入顺序"),
            "response_rule": (
                "只有被提问者在问题之后产生的公开发言才能回答该问题；"
                "record_seq 更小的发言绝不能回答 record_seq 更大的问题"
            ),
            "open_question_rule": (
                "status=open 表示尚无符合时间和说话人条件的后续回答，不得把问题之前的发言描述成回答"
            ),
            "causality_rule": ("后发生的发言不能成为先发生行动的原因；必须区分当时信息与事后评价"),
        },
        "current_round_no": current_round_no,
        "statements": [_public_utterance(utterance) for utterance in utterances],
        "claims": claims,
        "questions": resolved_questions,
        "relations": relations,
        "unparsed_statement_refs": [
            str(utterance["source_event_id"])
            for utterance in utterances
            if utterance["source_event_id"] not in fully_interpreted_sources
        ],
    }


def _normalize_utterances(
    statements: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    utterances: list[dict[str, Any]] = []
    for input_index, statement in enumerate(statements, start=1):
        source_event_id = statement.get("source_event_id")
        speaker_ref = statement.get("speaker_ref")
        speech = statement.get("speech")
        occurred_in = statement.get("occurred_in")
        if (
            not isinstance(source_event_id, str)
            or not source_event_id
            or not isinstance(speaker_ref, str)
            or not isinstance(speech, str)
            or not speech.strip()
            or not isinstance(occurred_in, dict)
        ):
            continue
        round_no = occurred_in.get("round_no")
        if not isinstance(round_no, int) or isinstance(round_no, bool) or round_no < 1:
            round_no = 1
        record_seq = statement.get("uttered_record_seq")
        utterance = {
            "statement_id": f"statement_{source_event_id}",
            "source_event_id": source_event_id,
            "turn_index": input_index,
            "round_no": round_no,
            "occurred_in": dict(occurred_in),
            "stage": statement.get("stage"),
            "speaker_ref": speaker_ref,
            "source_kind": "speaker_statement",
            "speech": speech.strip(),
        }
        if isinstance(record_seq, int) and not isinstance(record_seq, bool):
            utterance["record_seq"] = record_seq
        utterances.append(utterance)
    if utterances and all("record_seq" in utterance for utterance in utterances):
        utterances.sort(key=lambda utterance: int(utterance["record_seq"]))
    for turn_index, utterance in enumerate(utterances, start=1):
        utterance["turn_index"] = turn_index
    return utterances


def _public_utterance(utterance: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in utterance.items() if key not in {"round_no"}}


def _sentences(speech: str) -> list[str]:
    return [
        match.group(0).strip() for match in _SENTENCE.finditer(speech) if match.group(0).strip()
    ]


def _extract_question(
    utterance: dict[str, Any],
    *,
    sentence: str,
    sentence_index: int,
    last_addressed_to: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    speaker_ref = str(utterance["speaker_ref"])
    addressed_to = _addressed_to(
        sentence,
        speaker_ref=speaker_ref,
    )
    if addressed_to is not None:
        last_addressed_to = addressed_to

    directly_asked = "？" in sentence or "?" in sentence or _DIRECT_QUESTION.search(sentence)
    reported_question = _OTHER_QUESTION_REPORT.search(sentence)
    if not directly_asked or (
        reported_question is not None
        and f"seat_{reported_question.group('seat')}" != speaker_ref
        and "我问" not in sentence
        and "我追问" not in sentence
    ):
        return None, last_addressed_to

    target_ref = addressed_to
    if (
        target_ref is None
        and last_addressed_to is not None
        and _SINGULAR_ADDRESSEE_CONTINUATION.search(sentence) is not None
    ):
        target_ref = last_addressed_to
    source_id = str(utterance["source_event_id"])
    question = {
        "question_id": f"question_{source_id}_{sentence_index}",
        "source_event_id": source_id,
        "source_sentence_id": f"sentence_{source_id}_{sentence_index}",
        "sentence_index": sentence_index,
        "asked_turn_index": utterance["turn_index"],
        "asked_by": speaker_ref,
        "addressed_to": target_ref,
        "asked_in": utterance["occurred_in"],
        "stage": utterance["stage"],
        "topic": _question_topic(sentence),
        "exact_quote": sentence,
        "status": "open" if target_ref is not None else "unresolved_target",
        "confirmation_status": "speaker_asked_publicly",
    }
    if "record_seq" in utterance:
        question["asked_record_seq"] = utterance["record_seq"]
    return question, last_addressed_to


def _addressed_to(sentence: str, *, speaker_ref: str) -> str | None:
    preferred: list[str] = []
    explicit: list[str] = []
    for match in _ADDRESSED_SEAT.finditer(sentence):
        ref = f"seat_{match.group('seat')}"
        if ref == speaker_ref:
            continue
        prefix = sentence[: match.start()].rstrip()
        suffix = sentence[match.end() : match.end() + 3]
        if "你" in match.group(0) or suffix.startswith("你"):
            preferred.append(ref)
        elif match.start() <= 1 or prefix.endswith(("问", "请", "请问", "追问")):
            explicit.append(ref)
    if preferred:
        return preferred[0]
    return explicit[0] if explicit else None


def _question_topic(sentence: str) -> str:
    if _INVESTIGATION.search(sentence):
        if any(term in sentence for term in ("为什么", "理由", "心路")):
            return "investigation_reason"
        if any(term in sentence for term in ("谁", "几号", "号码", "具体", "锁", "方向")):
            return "future_investigation_target"
        return "investigation_plan"
    if "警徽流" in sentence:
        return "sheriff_plan"
    if any(term in sentence for term in ("投", "票", "归票", "出谁")):
        return "vote_stance"
    return "general"


def _extract_claims(
    utterance: dict[str, Any],
    *,
    sentence: str,
    sentence_index: int,
    utterance_claims_seer: bool,
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    speaker_ref = str(utterance["speaker_ref"])

    reported_speaker_ref = _secondary_reported_speaker(
        sentence,
        speaker_ref=speaker_ref,
    )
    if reported_speaker_ref is not None:
        claims.append(
            _claim(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                claim_type="secondary_paraphrase",
                source_kind="secondary_unverified_paraphrase",
                attributes={
                    "reported_speaker_ref": reported_speaker_ref,
                    "temporal_relation_status": "unverified",
                    **(
                        {"asserted_relation_type": "reported_response"}
                        if any(term in sentence for term in _RESPONSE_REPORT_TERMS)
                        else {}
                    ),
                },
            )
        )

    role_match = _ROLE_CLAIM.search(sentence)
    if role_match is not None:
        claims.append(
            _claim(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                claim_type="role_claim",
                attributes={"claimed_role": _ROLE_KEYS[role_match.group("role")]},
            )
        )

    if _is_first_party_investigation(
        sentence,
        speaker_ref=speaker_ref,
        utterance_claims_seer=utterance_claims_seer,
    ):
        attributes: dict[str, Any] = {
            "claimed_action_in": {
                "period": "night",
                "round_no": _claimed_night_round(
                    sentence,
                    occurred_in=utterance["occurred_in"],
                ),
            }
        }
        target_match = _INVESTIGATION_TARGET.search(sentence)
        if target_match is not None:
            attributes["target_ref"] = f"seat_{target_match.group('seat')}"
        if "查杀" in sentence or "狼人" in sentence:
            attributes["claimed_result"] = "werewolves"
        elif "金水" in sentence or "好人" in sentence:
            attributes["claimed_result"] = "villagers"
        claims.append(
            _claim(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                claim_type="investigation_claim",
                attributes=attributes,
            )
        )

    if (
        _FUTURE_NIGHT.search(sentence) is not None
        and _INVESTIGATION.search(sentence) is not None
        and _FIRST_PARTY_FUTURE_INVESTIGATION.search(sentence) is not None
        and "？" not in sentence
        and "?" not in sentence
        and _DIRECT_QUESTION.search(sentence) is None
    ):
        target_match = _INVESTIGATION_TARGET.search(sentence)
        claims.append(
            _claim(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                claim_type="future_investigation_plan",
                attributes={
                    "specificity": (
                        "specific_target" if target_match is not None else "direction_only"
                    ),
                    **(
                        {"target_ref": f"seat_{target_match.group('seat')}"}
                        if target_match is not None
                        else {}
                    ),
                },
            )
        )

    vote_match = _VOTE_TARGET.search(sentence)
    if vote_match is not None and "我" in sentence:
        prefix = sentence[max(0, vote_match.start() - 3) : vote_match.start()]
        claims.append(
            _claim(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                claim_type="vote_stance",
                attributes={
                    "target_ref": f"seat_{vote_match.group('seat')}",
                    "stance": "against" if "不" in prefix else "support_vote",
                },
            )
        )

    mentioned_refs = _mentioned_player_refs(sentence) - {speaker_ref}
    if mentioned_refs and any(term in sentence for term in _ASSESSMENT_TERMS):
        claims.append(
            _claim(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                claim_type="player_assessment",
                attributes={"subject_refs": sorted(mentioned_refs, key=_seat_sort_key)},
            )
        )

    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        identity = (str(claim["claim_type"]), str(claim["exact_quote"]))
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(claim)
    return deduplicated


def _claim(
    utterance: dict[str, Any],
    *,
    sentence: str,
    sentence_index: int,
    claim_type: str,
    attributes: dict[str, Any],
    source_kind: str = "speaker_first_party_claim",
) -> dict[str, Any]:
    source_id = str(utterance["source_event_id"])
    claim = {
        "claim_id": f"claim_{source_id}_{sentence_index}_{claim_type}",
        "claim_type": claim_type,
        "source_event_id": source_id,
        "source_sentence_id": f"sentence_{source_id}_{sentence_index}",
        "sentence_index": sentence_index,
        "source_kind": source_kind,
        "speaker_ref": utterance["speaker_ref"],
        "uttered_turn_index": utterance["turn_index"],
        "occurred_in": utterance["occurred_in"],
        "stage": utterance["stage"],
        "exact_quote": sentence,
        "mentioned_player_refs": sorted(
            _mentioned_player_refs(sentence),
            key=_seat_sort_key,
        ),
        "confirmation_status": "unverified",
        **attributes,
    }
    if "record_seq" in utterance:
        claim["uttered_record_seq"] = utterance["record_seq"]
    return claim


def _is_first_party_investigation(
    sentence: str,
    *,
    speaker_ref: str,
    utterance_claims_seer: bool,
) -> bool:
    if _PAST_NIGHT.search(sentence) is None or _INVESTIGATION.search(sentence) is None:
        return False
    if _secondary_reported_speaker(sentence, speaker_ref=speaker_ref) is not None:
        return False
    normalized = sentence.replace(" ", "")
    speaker_label = (
        f"{speaker_ref.removeprefix('seat_')}号" if speaker_ref.startswith("seat_") else ""
    )
    speaker_leads_seer_claim = (
        bool(speaker_label) and normalized.startswith(speaker_label) and "预言家" in normalized
    )
    return (
        utterance_claims_seer
        or speaker_leads_seer_claim
        or _SELF_PAST_INVESTIGATION.search(normalized) is not None
    )


def _secondary_reported_speaker(
    sentence: str,
    *,
    speaker_ref: str,
) -> str | None:
    for pattern in (_SECONDARY_REPORT, _SECONDARY_ACTION_ACCOUNT):
        match = pattern.search(sentence)
        if match is None:
            continue
        ref = f"seat_{match.group('seat')}"
        if ref != speaker_ref:
            return ref
    return None


def _claimed_night_round(
    sentence: str,
    *,
    occurred_in: dict[str, Any],
) -> int:
    if any(marker in sentence for marker in ("首夜", "第一晚", "第一夜")):
        return 1
    round_no = occurred_in.get("round_no")
    return round_no if isinstance(round_no, int) and round_no > 0 else 1


def _resolve_questions(
    questions: list[dict[str, Any]],
    *,
    utterances: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resolved_questions: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    for raw_question in questions:
        question = dict(raw_question)
        target_ref = question.get("addressed_to")
        if not isinstance(target_ref, str):
            resolved_questions.append(question)
            continue
        for utterance in utterances:
            if (
                not _utterance_follows_question(utterance, question=question)
                or utterance["speaker_ref"] != target_ref
                or utterance["round_no"] != question["asked_in"].get("round_no")
                or not _matches_question_topic(
                    str(utterance["speech"]),
                    topic=str(question["topic"]),
                )
            ):
                continue
            question["status"] = "answered"
            question["answer_source_event_id"] = utterance["source_event_id"]
            question["answer_turn_index"] = utterance["turn_index"]
            if "record_seq" in utterance:
                question["answer_record_seq"] = utterance["record_seq"]
            relation = {
                "relation_id": (
                    f"relation_{utterance['source_event_id']}_{question['question_id']}"
                ),
                "relation_type": "answers_question",
                "from_source_event_id": utterance["source_event_id"],
                "from_speaker_ref": utterance["speaker_ref"],
                "from_turn_index": utterance["turn_index"],
                "to_question_id": question["question_id"],
                "to_source_event_id": question["source_event_id"],
                "to_turn_index": question["asked_turn_index"],
                "temporal_order_valid": True,
                "confirmation_status": "deterministic_speaker_time_and_topic_match",
            }
            if "record_seq" in utterance:
                relation["from_record_seq"] = utterance["record_seq"]
            if "asked_record_seq" in question:
                relation["to_record_seq"] = question["asked_record_seq"]
            relations.append(relation)
            break
        resolved_questions.append(question)
    return resolved_questions, relations


def _utterance_follows_question(
    utterance: dict[str, Any],
    *,
    question: dict[str, Any],
) -> bool:
    uttered_record_seq = utterance.get("record_seq")
    asked_record_seq = question.get("asked_record_seq")
    if (
        isinstance(uttered_record_seq, int)
        and not isinstance(uttered_record_seq, bool)
        and isinstance(asked_record_seq, int)
        and not isinstance(asked_record_seq, bool)
    ):
        return uttered_record_seq > asked_record_seq
    return int(utterance["turn_index"]) > int(question["asked_turn_index"])


def _matches_question_topic(speech: str, *, topic: str) -> bool:
    if topic == "future_investigation_target":
        return _INVESTIGATION.search(speech) is not None and (
            _INVESTIGATION_TARGET.search(speech) is not None
            or any(term in speech for term in ("警上", "警下", "最拧巴", "具体目标"))
        )
    if topic == "investigation_reason":
        return _INVESTIGATION.search(speech) is not None and any(
            term in speech for term in ("原因", "理由", "因为", "为什么选")
        )
    if topic in {"investigation_plan", "sheriff_plan"}:
        return _INVESTIGATION.search(speech) is not None or "警徽流" in speech
    if topic == "vote_stance":
        return False
    return False


def _mentioned_player_refs(speech: str) -> set[str]:
    return {f"seat_{match.group(1)}" for match in _SEAT_REFERENCE.finditer(speech)}


def _seat_sort_key(ref: str) -> tuple[int, str]:
    if ref.startswith("seat_") and ref[5:].isdigit():
        return int(ref[5:]), ref
    return 10_000, ref
