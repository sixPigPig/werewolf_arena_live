from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any

from app.v2.model_context_contract import DISCOURSE_LEDGER_SCHEMA_VERSION


_SENTENCE = re.compile(r"[^。！？!?]+[。！？!?]?")
_SENTENCE_V4 = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")
_ENUMERATED_ITEM = re.compile(r"第[一二三四五六七八九十]+[、，,:：]")
_SEAT_REFERENCE = re.compile(r"(?<!\d)(?:seat_)?(2[0-9]|1[0-9]|[1-9])号?")
_ADDRESSED_SEAT = re.compile(
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号(?:玩家)?(?:你|请|先|能不能|为什么|怎么|到底)?"
)
_PAST_NIGHT = re.compile(r"(?:昨晚|昨夜|首夜|第一晚|第一夜)")
_FUTURE_NIGHT = re.compile(r"(?:今晚|今夜|明晚|明夜|下一晚|下晚|警徽流)")
_PAST_INVESTIGATION_REFERENCE = re.compile(r"(?:昨晚|昨夜|首夜|第一晚|第一夜)")
_IMPLICIT_PAST_INVESTIGATION_REFERENCE = re.compile(
    r"(?:查验了|验了|摸了|查验过|验过|摸过|首验|验人结果|查验结果)"
)
_INVESTIGATION = re.compile(r"(?:查验|验|摸)")
_INVESTIGATION_RESULT = re.compile(r"(?:查杀|金水|狼人|好人)")
_NEGATED_RESULT_PREFIX = re.compile(
    r"(?:并非|并不是|不是|不算|不像|非)[^，,。！？!?；;]{0,3}$"
)
_RESULT_CLAUSE_TRANSITION = re.compile(r"(?:但|不过|然而|可是|回头看|至于)")
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
_V4_SELF_FIRST_INVESTIGATION = re.compile(r"(?:我的?首验|我首验)")
_V4_DIRECT_FIRST_INVESTIGATION = re.compile(
    r"^\s*首验(?:的?是|了)?(?:警上|警下)?(?:的)?"
    r"(?:2[0-9]|1[0-9]|[1-9])号"
)
_DIRECT_QUESTION = re.compile(
    r"(?:我(?:现在|想|要)?问|请.{0,12}回答|"
    r"你.{0,18}(?:谁|什么|怎么|为什么|能不能|是否|哪|几号|号码))"
)
_DIRECT_SINGULAR_QUESTION = re.compile(
    r"你(?!们)[^。！？!?]{0,18}(?:谁|什么|怎么|为什么|为何|能不能|是否|哪|几号|号码)"
)
_SINGULAR_ADDRESSEE_CONTINUATION = re.compile(r"^\s*你(?!们)")
_ENUMERATED_ADDRESSEE_CONTINUATION = re.compile(
    r"^\s*第[一二三四五六七八九十]+[、，,:：]"
)
_V4_EXPLICIT_QUESTION_TARGET = re.compile(
    r"(?:"
    r"(?:问|追问|请问|请)\s*(?P<seat>2[0-9]|1[0-9]|[1-9])号(?:玩家)?"
    r"|给\s*(?P<given_seat>2[0-9]|1[0-9]|[1-9])号(?:玩家)?"
    r"(?:一|两|几)?个?(?:问题|提问)"
    r")"
)
_V4_PAST_INVESTIGATION_TARGET = re.compile(
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号(?:玩家)?"
    r"[^。！？!?；;]{0,10}(?:昨晚|昨夜|首夜|第一晚|第一夜)"
    r"[^。！？!?；;]{0,20}(?:查验|验|摸)"
)
_V4_IMPLICIT_QUESTION_CUE = re.compile(
    r"(?:"
    r"(?:查验|验|摸|首验)[^。！？!?；;]{0,12}(?:谁|什么结果|为什么|为何|哪(?:个|张|一)?|几号|号码)"
    r"|(?:什么结果|结果是什么)"
    r"|警徽流[^。！？!?；;]{0,10}怎么留"
    r")"
)
_OTHER_QUESTION_REPORT = re.compile(r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号.{0,12}(?:问|追问)")
_OTHER_QUESTION_REPORT_V4 = re.compile(
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号.{0,12}(?:追问|问(?!题))"
)
_SECONDARY_REPORT = re.compile(
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号.{0,18}"
    r"(?:说|表示|问|追问|回答|回应|只说|提过|报了|报过|声称|点过|认为)"
)
_SECONDARY_ACTION_ACCOUNT = re.compile(
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号[^。！？!?]{0,80}"
    r"(?:昨晚|昨夜|首夜|第一晚|第一夜)[^。！？!?]{0,24}(?:查验|验|摸)"
)
_SECONDARY_ACTION_ACCOUNT_PAST_FIRST = re.compile(
    r"(?:昨晚|昨夜|首夜|第一晚|第一夜)[^。！？!?；;]{0,8}"
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号(?:玩家)?\s*"
    r"(?:查验|验|摸)"
)
_SECONDARY_QUOTED_ATTRIBUTION_PREFIX = re.compile(
    r"(?:按|引用|复述)\s*(?P<seat>2[0-9]|1[0-9]|[1-9])号(?:玩家)?"
    r"(?:的)?(?:原话|说法)?"
)
_SECONDARY_QUOTED_ATTRIBUTION_LEADING = re.compile(
    r"(?<!\d)(?P<seat>2[0-9]|1[0-9]|[1-9])号(?:玩家)?的?"
    r"(?:原话|说法|表述)(?:是|为)?"
)
_GENERIC_ATTRIBUTION = re.compile(
    r"(?:"
    r"(?:有人|别人|他|她|大家|某人)[^。！？!?；;]{0,8}"
    r"(?:说|认为|声称|称|表示|原话(?:是)?)"
    r"|(?:按|引用|复述)\s*(?:他|她|别人|某人|有人|大家)(?:的)?(?:原话|说法)?"
    r"|(?:引用|复述|原话(?:是)?)[：:]"
    r")"
)
_GENERIC_SECONDARY_ACTION = re.compile(
    r"(?:昨晚|昨夜|首夜|第一晚|第一夜)[^。！？!?；;]{0,10}"
    r"(?:别人|他|她|有人|某人|大家)[^。！？!?；;]{0,5}(?:查验|验|摸)"
)
_ATTRIBUTION_BREAK = re.compile(r"(?:[。！？!?；;]|但|不过|然而|可是|实际(?:上)?|而我|至于我)")
_NONASSERTIVE_PREFIX = re.compile(
    r"(?:如果|假如|假设|要是|别说|并非|并不是|不是|不代表|不等于)"
    r"[^。！？!?；;]{0,32}$"
)
_CONDITIONAL_MARKER = re.compile(r"(?:如果|假如|假设|要是)")
_NEGATED_FUTURE_INVESTIGATION = re.compile(
    r"我[^。！？!?；;]{0,6}(?:不|没|没有|未)"
    r"(?:会|准备|打算|要|想|能)?[^。！？!?；;]{0,4}(?:查验|去验|验|摸)"
)
_NEGATED_PAST_INVESTIGATION = re.compile(
    r"我[^。！？!?；;]{0,8}(?:没|没有|未|不曾)"
    r"[^。！？!?；;]{0,4}(?:查验|验|摸)"
)
_NEGATED_INVESTIGATION = re.compile(
    r"(?:没|没有|未|不曾|不是|并非)[^。！？!?；;]{0,5}(?:查验|验|摸)"
)
_VOTE_TARGET = re.compile(
    r"(?:投|票给|归票(?:给)?|今天出|先出)"
    r"(?P<seat>2[0-9]|1[0-9]|[1-9])号"
)
_VOTE_ACTION = re.compile(
    r"(?:投(?:给)?|票(?:投|给)?|归(?:票)?(?:给)?|出)\s*(?:了)?\s*"
    r"(?:2[0-9]|1[0-9]|[1-9])号?"
)
_VOTE_REASON_QUESTION = re.compile(r"(?:为什么|为何|解释|理由|依据|凭什么)")
_VOTE_REASON_ANSWER = re.compile(r"(?:因为|根据|出于|理由是|判断|考虑|所以|依据)")
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
    ledger_schema_version: int = DISCOURSE_LEDGER_SCHEMA_VERSION,
) -> dict[str, Any]:
    del actor_ref
    utterances = _normalize_utterances(statements)
    claims: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    fully_interpreted_sources: set[str] = set()

    for utterance in utterances:
        source_id = str(utterance["source_event_id"])
        last_addressed_to: str | None = None
        sentences = _sentences(
            str(utterance["speech"]),
            ledger_schema_version=ledger_schema_version,
        )
        utterance_claims_seer = (
            any(
                (
                    match := _first_party_role_match(
                        sentence,
                        speaker_ref=str(utterance["speaker_ref"]),
                    )
                )
                is not None
                and match.group("role") == "预言家"
                for sentence in sentences
            )
            if ledger_schema_version >= 4
            else any(
                match.group("role") == "预言家"
                for match in _ROLE_CLAIM.finditer(str(utterance["speech"]))
            )
        )
        all_sentences_interpreted = bool(sentences)
        for sentence_index, sentence in enumerate(sentences, start=1):
            question, last_addressed_to = _extract_question(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                last_addressed_to=last_addressed_to,
                ledger_schema_version=ledger_schema_version,
            )
            if question is not None:
                questions.append(question)

            sentence_claims = _extract_claims(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                utterance_claims_seer=utterance_claims_seer,
                ledger_schema_version=ledger_schema_version,
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
        ledger_schema_version=ledger_schema_version,
    )

    return {
        "ledger_schema_version": ledger_schema_version,
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
                "status=open 只表示尚无符合时间和说话人条件的后续回答；"
                "不表示被提问者此前从未解释，也不表示其拒绝回应；"
                "不得把问题之前的发言描述成对后来问题的回答"
            ),
            **(
                {
                    "question_address_rule": (
                        "status 只表示问题是否已被后续发言回答；"
                        "address_resolution 单独表示被提问者是否已解析"
                    )
                }
                if ledger_schema_version >= 4
                else {}
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


def _sentences(speech: str, *, ledger_schema_version: int) -> list[str]:
    pattern = _SENTENCE_V4 if ledger_schema_version >= 4 else _SENTENCE
    sentences = [
        match.group(0).strip() for match in pattern.finditer(speech) if match.group(0).strip()
    ]
    if ledger_schema_version < 4:
        return sentences
    return [part for sentence in sentences for part in _split_enumerated_items(sentence)]


def _split_enumerated_items(sentence: str) -> list[str]:
    matches = list(_ENUMERATED_ITEM.finditer(sentence))
    if len(matches) < 2:
        return [sentence]
    boundaries = [match.start() for match in matches[1:]]
    parts: list[str] = []
    start = 0
    for boundary in boundaries:
        part = sentence[start:boundary].strip()
        if part:
            parts.append(part)
        start = boundary
    tail = sentence[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _extract_question(
    utterance: dict[str, Any],
    *,
    sentence: str,
    sentence_index: int,
    last_addressed_to: str | None,
    ledger_schema_version: int,
) -> tuple[dict[str, Any] | None, str | None]:
    speaker_ref = str(utterance["speaker_ref"])
    if ledger_schema_version >= 4:
        addressed_to = _addressed_to_v4(sentence, speaker_ref=speaker_ref)
    elif ledger_schema_version >= 3:
        addressed_to = _addressed_to_v3(sentence, speaker_ref=speaker_ref)
    else:
        addressed_to = _addressed_to(sentence, speaker_ref=speaker_ref)
    if addressed_to is not None:
        last_addressed_to = addressed_to

    continuation_question = last_addressed_to is not None and (
        _SINGULAR_ADDRESSEE_CONTINUATION.search(sentence) is not None
        or _ENUMERATED_ADDRESSEE_CONTINUATION.search(sentence) is not None
    )
    explicit_v4_question_target = (
        ledger_schema_version >= 4
        and _V4_EXPLICIT_QUESTION_TARGET.search(sentence) is not None
    )
    directly_asked = (
        "？" in sentence
        or "?" in sentence
        or _DIRECT_QUESTION.search(sentence)
        or (
            ledger_schema_version >= 4
            and _V4_IMPLICIT_QUESTION_CUE.search(sentence) is not None
            and (explicit_v4_question_target or continuation_question)
        )
    )
    reported_question = (
        _OTHER_QUESTION_REPORT_V4.search(sentence)
        if ledger_schema_version >= 4
        else _OTHER_QUESTION_REPORT.search(sentence)
    )
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
        and (
            _SINGULAR_ADDRESSEE_CONTINUATION.search(sentence) is not None
            or (
                ledger_schema_version >= 4
                and _ENUMERATED_ADDRESSEE_CONTINUATION.search(sentence) is not None
            )
        )
    ):
        target_ref = last_addressed_to
    topic_source = (
        _question_focus(sentence, addressed_to=target_ref)
        if ledger_schema_version >= 3
        else sentence
    )
    topic = _question_topic(
        topic_source,
        vote_reason_enabled=ledger_schema_version >= 3,
        ledger_schema_version=ledger_schema_version,
    )
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
        "topic": topic,
        "exact_quote": sentence,
        "status": (
            "open"
            if ledger_schema_version >= 4 or target_ref is not None
            else "unresolved_target"
        ),
        "confirmation_status": "speaker_asked_publicly",
    }
    if ledger_schema_version >= 4:
        question["address_resolution"] = (
            "resolved" if target_ref is not None else "unresolved"
        )
        if topic == "past_investigation_result":
            question["requested_fields"] = _past_investigation_requested_fields(
                topic_source
            )
            referenced_night_no = _referenced_investigation_night_no(
                topic_source,
                asked_in=utterance["occurred_in"],
            )
            if referenced_night_no is not None:
                question["referenced_night_no"] = referenced_night_no
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


def _addressed_to_v3(sentence: str, *, speaker_ref: str) -> str | None:
    anchors = list(_DIRECT_SINGULAR_QUESTION.finditer(sentence))
    if anchors:
        anchor = anchors[-1].start()
        preceding = [
            f"seat_{match.group('seat')}"
            for match in _ADDRESSED_SEAT.finditer(sentence)
            if match.end() <= anchor and f"seat_{match.group('seat')}" != speaker_ref
        ]
        if preceding:
            return preceding[-1]
    return _addressed_to(sentence, speaker_ref=speaker_ref)


def _addressed_to_v4(sentence: str, *, speaker_ref: str) -> str | None:
    addressed_to = _addressed_to_v3(sentence, speaker_ref=speaker_ref)
    if addressed_to is not None:
        return addressed_to
    for pattern in (_V4_EXPLICIT_QUESTION_TARGET, _V4_PAST_INVESTIGATION_TARGET):
        for match in pattern.finditer(sentence):
            seat = match.groupdict().get("seat") or match.groupdict().get("given_seat")
            if seat is None:
                continue
            ref = f"seat_{seat}"
            if ref != speaker_ref:
                return ref
    return None


def _question_focus(sentence: str, *, addressed_to: str | None) -> str:
    if not isinstance(addressed_to, str) or not addressed_to.startswith("seat_"):
        return sentence
    seat = addressed_to.removeprefix("seat_")
    if not seat.isdigit():
        return sentence
    target_matches = [
        match for match in _ADDRESSED_SEAT.finditer(sentence) if match.group("seat") == seat
    ]
    if not target_matches:
        return sentence
    anchors = list(_DIRECT_SINGULAR_QUESTION.finditer(sentence))
    if anchors:
        anchor = anchors[-1].start()
        preceding = [match for match in target_matches if match.end() <= anchor]
        if preceding:
            return sentence[preceding[-1].start() :]
    return sentence[target_matches[0].start() :]


def _question_topic(
    sentence: str,
    *,
    vote_reason_enabled: bool = False,
    ledger_schema_version: int = 2,
) -> str:
    if (
        vote_reason_enabled
        and _VOTE_ACTION.search(sentence) is not None
        and _VOTE_REASON_QUESTION.search(sentence) is not None
    ):
        return "vote_reason"
    if ledger_schema_version >= 4:
        if (
            _has_past_investigation_reference(sentence)
            and _INVESTIGATION.search(sentence) is not None
        ):
            if any(term in sentence for term in ("为什么", "为何", "理由", "心路")):
                return "investigation_reason"
            return "past_investigation_result"
        if "警徽流" in sentence:
            return "sheriff_plan"
        if _INVESTIGATION.search(sentence):
            if any(term in sentence for term in ("为什么", "为何", "理由", "心路")):
                return "investigation_reason"
            return "future_investigation_plan"
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


def _has_past_investigation_reference(text: str) -> bool:
    if _PAST_INVESTIGATION_REFERENCE.search(text) is not None:
        return True
    return (
        _FUTURE_NIGHT.search(text) is None
        and _IMPLICIT_PAST_INVESTIGATION_REFERENCE.search(text) is not None
    )


def _past_investigation_requested_fields(text: str) -> list[str]:
    requested_fields: list[str] = []
    if any(term in text for term in ("谁", "哪张", "哪个", "哪一", "几号", "号码")):
        requested_fields.append("target_ref")
    if any(term in text for term in ("结果", "查杀", "金水", "狼人", "好人")):
        requested_fields.append("claimed_result")
    return requested_fields or ["target_ref", "claimed_result"]


def _referenced_investigation_night_no(
    text: str,
    *,
    asked_in: dict[str, Any],
) -> int | None:
    if any(marker in text for marker in ("首夜", "第一晚", "第一夜", "首验")):
        return 1
    if any(marker in text for marker in ("昨晚", "昨夜")):
        round_no = asked_in.get("round_no")
        if isinstance(round_no, int) and not isinstance(round_no, bool) and round_no > 0:
            return round_no
    return None


def _first_party_role_match(
    sentence: str,
    *,
    speaker_ref: str,
) -> re.Match[str] | None:
    for match in _ROLE_CLAIM.finditer(sentence):
        if _claim_is_nonassertive(sentence, claim_start=match.start()):
            continue
        if _claim_is_attributed(
            sentence,
            claim_start=match.start(),
            speaker_ref=speaker_ref,
        ):
            continue
        return match
    return None


def _first_party_future_investigation_match(
    sentence: str,
    *,
    speaker_ref: str,
) -> re.Match[str] | None:
    if (
        _FUTURE_NIGHT.search(sentence) is None
        or _INVESTIGATION.search(sentence) is None
        or "？" in sentence
        or "?" in sentence
        or _DIRECT_QUESTION.search(sentence) is not None
    ):
        return None
    for match in _FIRST_PARTY_FUTURE_INVESTIGATION.finditer(sentence):
        matched_text = match.group(0)
        if (
            _claim_is_nonassertive(sentence, claim_start=match.start())
            or _CONDITIONAL_MARKER.search(matched_text) is not None
            or _NEGATED_FUTURE_INVESTIGATION.search(matched_text) is not None
            or _claim_is_attributed(
                sentence,
                claim_start=match.start(),
                speaker_ref=speaker_ref,
            )
        ):
            continue
        return match
    return None


def _claim_is_nonassertive(sentence: str, *, claim_start: int) -> bool:
    clause_prefix = sentence[:claim_start]
    return _NONASSERTIVE_PREFIX.search(clause_prefix) is not None


def _claim_is_attributed(
    sentence: str,
    *,
    claim_start: int,
    speaker_ref: str,
) -> bool:
    for pattern in (
        _SECONDARY_REPORT,
        _SECONDARY_ACTION_ACCOUNT,
        _SECONDARY_ACTION_ACCOUNT_PAST_FIRST,
        _SECONDARY_QUOTED_ATTRIBUTION_PREFIX,
        _SECONDARY_QUOTED_ATTRIBUTION_LEADING,
    ):
        for report_match in pattern.finditer(sentence):
            if f"seat_{report_match.group('seat')}" == speaker_ref:
                continue
            if report_match.end() > claim_start:
                continue
            bridge = sentence[report_match.end() : claim_start]
            if _ATTRIBUTION_BREAK.search(bridge) is None:
                return True
    for report_match in _GENERIC_ATTRIBUTION.finditer(sentence):
        if report_match.end() > claim_start:
            continue
        bridge = sentence[report_match.end() : claim_start]
        if _ATTRIBUTION_BREAK.search(bridge) is None:
            return True
    return False


def _claimed_investigation_result(sentence: str) -> str | None:
    target_match = _INVESTIGATION_TARGET.search(sentence)
    action_match = target_match or _INVESTIGATION.search(sentence)
    if action_match is None:
        return None
    clause_end = len(sentence)
    for seat_match in _SEAT_REFERENCE.finditer(sentence, action_match.end()):
        clause_end = seat_match.start()
        break
    for transition in _RESULT_CLAUSE_TRANSITION.finditer(
        sentence,
        action_match.end(),
        clause_end,
    ):
        tail = sentence[transition.end() : clause_end].lstrip("，,：: ")
        if re.match(r"(?:是|为)?(?:查杀|金水|狼人|好人)", tail) is not None:
            continue
        clause_end = transition.start()
        break
    local_clause = sentence[action_match.start() : clause_end]
    claimed_result: str | None = None
    for match in _INVESTIGATION_RESULT.finditer(local_clause):
        prefix = local_clause[max(0, match.start() - 8) : match.start()]
        if _NEGATED_RESULT_PREFIX.search(prefix) is not None:
            continue
        claimed_result = (
            "werewolves" if match.group(0) in {"查杀", "狼人"} else "villagers"
        )
    return claimed_result


def _extract_claims(
    utterance: dict[str, Any],
    *,
    sentence: str,
    sentence_index: int,
    utterance_claims_seer: bool,
    ledger_schema_version: int,
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    speaker_ref = str(utterance["speaker_ref"])

    reported_speaker_ref = _secondary_reported_speaker(
        sentence,
        speaker_ref=speaker_ref,
        ledger_schema_version=ledger_schema_version,
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

    role_match = (
        _first_party_role_match(sentence, speaker_ref=speaker_ref)
        if ledger_schema_version >= 4
        else _ROLE_CLAIM.search(sentence)
    )
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
        ledger_schema_version=ledger_schema_version,
    ):
        attributes: dict[str, Any] = {
            "claimed_action_in": {
                "period": "night",
                "round_no": _claimed_night_round(
                    sentence,
                    occurred_in=utterance["occurred_in"],
                    ledger_schema_version=ledger_schema_version,
                ),
            }
        }
        target_match = _INVESTIGATION_TARGET.search(sentence)
        if target_match is not None:
            attributes["target_ref"] = f"seat_{target_match.group('seat')}"
        claimed_result = (
            _claimed_investigation_result(sentence)
            if ledger_schema_version >= 4
            else (
                "werewolves"
                if "查杀" in sentence or "狼人" in sentence
                else "villagers"
                if "金水" in sentence or "好人" in sentence
                else None
            )
        )
        if claimed_result is not None:
            attributes["claimed_result"] = claimed_result
        claims.append(
            _claim(
                utterance,
                sentence=sentence,
                sentence_index=sentence_index,
                claim_type="investigation_claim",
                attributes=attributes,
            )
        )

    future_match = (
        _first_party_future_investigation_match(
            sentence,
            speaker_ref=speaker_ref,
        )
        if ledger_schema_version >= 4
        else _FIRST_PARTY_FUTURE_INVESTIGATION.search(sentence)
        if (
            _FUTURE_NIGHT.search(sentence) is not None
            and _INVESTIGATION.search(sentence) is not None
            and "？" not in sentence
            and "?" not in sentence
            and _DIRECT_QUESTION.search(sentence) is None
        )
        else None
    )
    if future_match is not None:
        if ledger_schema_version >= 4:
            target_matches = list(_INVESTIGATION_TARGET.finditer(future_match.group(0)))
            target_match = target_matches[-1] if target_matches else None
        else:
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
    ledger_schema_version: int,
) -> bool:
    has_past_reference = (
        _has_past_investigation_reference(sentence)
        if ledger_schema_version >= 4
        else _PAST_NIGHT.search(sentence) is not None
    )
    if not has_past_reference or _INVESTIGATION.search(sentence) is None:
        return False
    if ledger_schema_version < 4:
        if (
            _secondary_reported_speaker(
                sentence,
                speaker_ref=speaker_ref,
                ledger_schema_version=ledger_schema_version,
            )
            is not None
        ):
            return False
        normalized = sentence.replace(" ", "")
        speaker_label = (
            f"{speaker_ref.removeprefix('seat_')}号"
            if speaker_ref.startswith("seat_")
            else ""
        )
        speaker_leads_seer_claim = (
            bool(speaker_label)
            and normalized.startswith(speaker_label)
            and "预言家" in normalized
        )
        return (
            utterance_claims_seer
            or speaker_leads_seer_claim
            or _SELF_PAST_INVESTIGATION.search(normalized) is not None
        )
    normalized = sentence.replace(" ", "")
    speaker_label = (
        f"{speaker_ref.removeprefix('seat_')}号" if speaker_ref.startswith("seat_") else ""
    )
    speaker_leads_seer_claim = (
        bool(speaker_label) and normalized.startswith(speaker_label) and "预言家" in normalized
    )
    explicit_self_claim = False
    self_matches = [
        *_SELF_PAST_INVESTIGATION.finditer(sentence),
        *_V4_SELF_FIRST_INVESTIGATION.finditer(sentence),
        *(
            _V4_DIRECT_FIRST_INVESTIGATION.finditer(sentence)
            if "？" not in sentence and "?" not in sentence
            else ()
        ),
    ]
    self_matches.sort(key=lambda match: match.start())
    for match in self_matches:
        context = sentence[max(0, match.start() - 12) : min(len(sentence), match.end() + 8)]
        if (
            _claim_is_nonassertive(sentence, claim_start=match.start())
            or _CONDITIONAL_MARKER.search(context) is not None
            or _NEGATED_PAST_INVESTIGATION.search(context) is not None
            or _NEGATED_INVESTIGATION.search(context) is not None
            or _claim_is_attributed(
                sentence,
                claim_start=match.start(),
                speaker_ref=speaker_ref,
            )
        ):
            continue
        explicit_self_claim = True
        break
    if (
        _secondary_reported_speaker(
            sentence,
            speaker_ref=speaker_ref,
            ledger_schema_version=ledger_schema_version,
        )
        is not None
    ):
        return explicit_self_claim
    if _GENERIC_SECONDARY_ACTION.search(sentence) is not None:
        return False
    if explicit_self_claim:
        return True
    return (
        (utterance_claims_seer or speaker_leads_seer_claim)
        and _CONDITIONAL_MARKER.search(sentence) is None
        and _NEGATED_INVESTIGATION.search(sentence) is None
    )


def _secondary_reported_speaker(
    sentence: str,
    *,
    speaker_ref: str,
    ledger_schema_version: int,
) -> str | None:
    patterns = [_SECONDARY_REPORT, _SECONDARY_ACTION_ACCOUNT]
    if ledger_schema_version >= 4:
        patterns.extend(
            (
                _SECONDARY_ACTION_ACCOUNT_PAST_FIRST,
                _SECONDARY_QUOTED_ATTRIBUTION_PREFIX,
                _SECONDARY_QUOTED_ATTRIBUTION_LEADING,
            )
        )
    for pattern in patterns:
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
    ledger_schema_version: int = 2,
) -> int:
    if any(marker in sentence for marker in ("首夜", "第一晚", "第一夜")) or (
        ledger_schema_version >= 4 and "首验" in sentence
    ):
        return 1
    round_no = occurred_in.get("round_no")
    return round_no if isinstance(round_no, int) and round_no > 0 else 1


def _resolve_questions(
    questions: list[dict[str, Any]],
    *,
    utterances: list[dict[str, Any]],
    ledger_schema_version: int,
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
                or not speech_matches_question_topic(
                    str(utterance["speech"]),
                    topic=str(question["topic"]),
                    ledger_schema_version=ledger_schema_version,
                )
                or (
                    ledger_schema_version >= 4
                    and not _v4_response_covers_question(
                        utterance,
                        question=question,
                    )
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


def _v4_response_covers_question(
    utterance: dict[str, Any],
    *,
    question: dict[str, Any],
) -> bool:
    if question.get("topic") != "past_investigation_result":
        return True
    speech = str(utterance.get("speech") or "")
    requested_fields = question.get("requested_fields")
    required = (
        [field for field in requested_fields if isinstance(field, str)]
        if isinstance(requested_fields, list)
        else ["target_ref", "claimed_result"]
    )
    if "target_ref" in required and _INVESTIGATION_TARGET.search(speech) is None:
        return False
    if "claimed_result" in required and _claimed_investigation_result(speech) is None:
        return False
    referenced_night_no = question.get("referenced_night_no")
    if isinstance(referenced_night_no, int):
        occurred_in = utterance.get("occurred_in")
        if not isinstance(occurred_in, dict):
            return False
        if (
            _claimed_night_round(
                speech,
                occurred_in=occurred_in,
                ledger_schema_version=4,
            )
            != referenced_night_no
        ):
            return False
    return True


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


def speech_matches_question_topic(
    speech: str,
    *,
    topic: str,
    ledger_schema_version: int = 3,
) -> bool:
    if ledger_schema_version >= 4 and topic == "past_investigation_result":
        return (
            _has_past_investigation_reference(speech)
            and _INVESTIGATION.search(speech) is not None
            and (
                _INVESTIGATION_TARGET.search(speech) is not None
                or _INVESTIGATION_RESULT.search(speech) is not None
            )
        )
    if ledger_schema_version >= 4 and topic == "future_investigation_plan":
        return (
            _FUTURE_NIGHT.search(speech) is not None
            and _INVESTIGATION.search(speech) is not None
        )
    if ledger_schema_version >= 4 and topic == "sheriff_plan":
        return "警徽流" in speech
    if topic == "future_investigation_target":
        return _INVESTIGATION.search(speech) is not None and (
            _INVESTIGATION_TARGET.search(speech) is not None
            or any(term in speech for term in ("警上", "警下", "最拧巴", "具体目标"))
        )
    if topic == "investigation_reason":
        return _INVESTIGATION.search(speech) is not None and any(
            term in speech for term in ("原因", "理由", "因为", "为什么选", "心路", "随机", "随便")
        )
    if topic in {"investigation_plan", "sheriff_plan"}:
        return _INVESTIGATION.search(speech) is not None or "警徽流" in speech
    if topic == "vote_reason":
        return (
            _VOTE_ACTION.search(speech) is not None
            and _VOTE_REASON_ANSWER.search(speech) is not None
        )
    if topic == "vote_stance":
        return False
    return False


def _mentioned_player_refs(speech: str) -> set[str]:
    return {f"seat_{match.group(1)}" for match in _SEAT_REFERENCE.finditer(speech)}


def _seat_sort_key(ref: str) -> tuple[int, str]:
    if ref.startswith("seat_") and ref[5:].isdigit():
        return int(ref[5:]), ref
    return 10_000, ref
