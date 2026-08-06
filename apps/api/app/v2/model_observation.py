from __future__ import annotations

import re
from typing import Any


_NEGATION_OR_REJECTION = re.compile(
    r"(?:没有|不存在|不是|并非|不可能|不能|不该|不成立|不符合|错误|矛盾|别盘|不能盘)"
)
_DOUBLE_WOLF_MARKER = re.compile(r"(?:双狼|两狼|两匹狼|两头狼|两张狼牌|两张狼人牌)")
_WOLF_TEAMMATE_MARKER = re.compile(r"狼队友")
_EXPLICIT_WOLF_PAIR = re.compile(
    r"(?:狼(?:就)?是\s*)"
    r"(?P<first>[1-9]|1[0-9]|2[0-4])号?"
    r"\s*(?:、|和|与|跟)\s*"
    r"(?P<second>[1-9]|1[0-9]|2[0-4])号?"
)
_SEAT_NUMBER = r"(?:2[0-4]|1[0-9]|[1-9])"
_VOTER_SEPARATOR = r"(?:、|，|,|和|与|跟|及)"
_EXPLICIT_VOTER_LIST = (
    rf"{_SEAT_NUMBER}号"
    rf"(?:\s*{_VOTER_SEPARATOR}\s*{_SEAT_NUMBER}号)*"
)
_VOTER_LIST = rf"(?<![\d号])(?:{_EXPLICIT_VOTER_LIST}|{_SEAT_NUMBER})(?!\d)"
_VOTE_PHASE_MARKER = r"(?:警上|警下|第一轮|第二轮|本轮|这轮|刚才|刚刚)?"
_VOTE_CLAIM_PATTERNS = (
    re.compile(
        rf"(?P<voters>{_VOTER_LIST})"
        rf"\s*{_VOTE_PHASE_MARKER}"
        r"\s*(?:都|也|还|一起|一致)?\s*"
        r"(?:跟|随)我\s*(?:出|投)\s*(?:了)?\s*"
        rf"(?P<target>{_SEAT_NUMBER}|你)号?"
    ),
    re.compile(
        rf"(?P<voters>{_VOTER_LIST})"
        rf"\s*{_VOTE_PHASE_MARKER}"
        rf"\s*(?:都|也|还|一起|分别|一致)?\s*"
        rf"给\s*(?P<target>{_SEAT_NUMBER}|你)号?\s*"
        r"(?:投(?:了)?票|上(?:了)?票)"
    ),
    re.compile(
        rf"(?P<voters>{_VOTER_LIST})"
        rf"\s*{_VOTE_PHASE_MARKER}"
        rf"\s*(?:都|也|还|一起|分别|一致)?\s*"
        r"(?:把\s*(?:手里|手中|自己的)?\s*票\s*)?"
        rf"(?:投给|投了|投)\s*(?:了)?\s*(?P<target>{_SEAT_NUMBER}|你)号?"
        r"(?:\s*(?:一票|这票))?"
    ),
    re.compile(
        rf"(?P<voters>{_VOTER_LIST})\s*(?:的)?票"
        rf"\s*(?:都|也)?\s*(?:投给|给了|在|归)\s*(?P<target>{_SEAT_NUMBER}|你)号?"
    ),
    re.compile(
        rf"(?P<voters>{_VOTER_LIST})"
        rf"\s*{_VOTE_PHASE_MARKER}"
        r"\s*(?:都|也|还|一起|分别|一致)?\s*"
        rf"给\s*(?P<target>{_SEAT_NUMBER}|你)号?"
        r"(?=\s*(?:[，,。！？!?；;]|$))"
    ),
)
_VOTE_CLAIM_REJECTION = re.compile(
    r"(?:没有|没给|没投|并未|未曾|不是|不可能|不成立|不对|有误|"
    r"错误|说错|记错|假的|造谣|谣言|才怪|不认为|别再说|"
    r"可能性(?:很|太)?低)"
)
_VOTE_CLAIM_UNCERTAINTY = re.compile(
    r"(?:如果|假如|要是|万一|可能|也许|或许|是否|是不是|难道|"
    r"请问|想问|想确认|确认一下|应该|应当|可以|最好|建议|希望|请|"
    r"下一轮|下轮|待会|等会|一会|稍后|接下来|下一票|重投)"
)
_VOTE_CLAIM_ATTRIBUTION = re.compile(
    rf"(?:(?:{_SEAT_NUMBER}号|你|他|她|有人)"
    r"(?:刚才|之前|明确)?(?:说|声称|认为|提到|讲|表示)"
    r"|(?:按照|按).{0,10}(?:说法|逻辑))[：,:，]?\s*$"
)
_VOTE_CLAIM_QUESTION_SUFFIX = re.compile(r"^\s*(?:(?:了|对|是)?(?:吗|么|呢)|[？?])")
_DIRECT_ADDRESSEE = re.compile(
    rf"(?:回应|回复|回答|反驳|质疑|问|对|跟)\s*(?P<seat>{_SEAT_NUMBER})号"
    rf"|(?P<seat_before_you>{_SEAT_NUMBER})号\s*[，,:：]?\s*你"
    rf"|(?:聊|说说|谈谈|再看|回到)\s*(?P<topic_seat>{_SEAT_NUMBER})号"
)
_SILENCE_MARKER = re.compile(
    r"(?:"
    r"一个字(?:都|也)?(?:没|不)(?:解释|回答|回应|说|开口)"
    r"|(?:到现在|一直|始终|从头到尾)[^。！？!?；;]{0,16}"
    r"(?:没|没有|不|未)(?:正面)?(?:解释|回答|回应|答|开口)"
    r"|(?:没|没有|不|未)(?:正面)?(?:解释|回答|回应|答过)"
    r"|(?:拒绝|不肯)(?:解释|回答|回应|开口)"
    r")"
)
_SILENCE_TARGET_BEFORE = re.compile(
    rf"(?P<seat>{_SEAT_NUMBER})号[^。！？!?；;]{{0,64}}"
    rf"{_SILENCE_MARKER.pattern}"
)
_SILENCE_NON_ACCUSATION = re.compile(
    r"(?:尚未轮到|还没轮到|没有轮到|没轮到|等(?:下|会|一会|到).{0,12}"
    r"(?:解释|回答|回应|开口)|希望.{0,12}(?:解释|回答|回应)|"
    r"不能说|不该说|别说|不认为|不同意|并非|并不是|错误信息|说法不对)"
)
_SILENCE_ATTRIBUTION = re.compile(
    rf"(?:{_SEAT_NUMBER}号|有人|他|她)[^。！？!?；;]{{0,16}}"
    r"(?:说|声称|认为|提到|表示)[^。！？!?；;]{0,16}$"
)
_INVESTIGATION_REASON_MARKER = re.compile(
    r"(?:验人逻辑|为什么.{0,12}(?:验|查验)|"
    r"(?:我)?(?:验|查验|选(?:择)?(?:了)?(?:他|她|\d{1,2}号)?)"
    r"[^。！？!?；;]{0,48}(?:因为|基于|看了|听了|看过|听过))"
)
_LATER_PUBLIC_INFORMATION_MARKER = re.compile(r"(?:发言|警上|上警|刚才|前面|前几位|态度|站边|逻辑)")
_INVESTIGATION_CAUSALITY_REJECTION = re.compile(
    r"(?:不是|并非|不能|不可能|绝不是).{0,12}(?:因为|基于)|"
    r"(?:发言|警上|上警|刚才|前面).{0,12}(?:无关|没关系)"
)
_PUBLIC_CAUSALITY_REJECTION = re.compile(r"(?:不是|并非|并不是|不算|不能算|不属于|无关|没关系)")
_PUBLIC_CAUSALITY_HYPOTHESIS = re.compile(r"(?:如果|假如|要是|若是|倘若|万一)")
_PUBLIC_CAUSALITY_ATTRIBUTION = re.compile(
    rf"(?:{_SEAT_NUMBER}号|他|她|有人)[^。！？!?；;]{{0,16}}"
    r"(?:说|声称|认为|提到|讲|表示)"
)
_PUBLIC_REACTION_CLAIM_PATTERNS = (
    re.compile(
        rf"(?P<reaction>{_SEAT_NUMBER})号[^。！？!?；;]{{0,24}}"
        rf"在(?P<trigger>{_SEAT_NUMBER})号[^。！？!?；;]{{0,16}}(?:之前|以前)"
        r"[^。！？!?；;]{0,24}(?:反咬|咬死|咬|攻击|打|要出|冲)"
        r"[^。！？!?；;]{0,12}(?P=trigger)号"
        r"[^。！？!?；;]{0,64}(?:像|是|属于|算)"
        r"[^。！？!?；;]{0,16}被[^。！？!?；;]{0,8}查杀"
        r"[^。！？!?；;]{0,6}(?:后|之后)"
        r"[^。！？!?；;]{0,12}(?:应激|反应|回应|反咬)"
    ),
    re.compile(
        rf"(?P<reaction>{_SEAT_NUMBER})号"
        rf"(?:(?!{_SEAT_NUMBER}号)[^。！？!?；;]){{0,80}}?"
        r"(?:回头猛打|猛打|反咬|攻击|咬死|咬|踩|打|回应|要出|冲)"
        rf"[^。！？!?；;]{{0,12}}(?P<trigger>{_SEAT_NUMBER})号"
        r"[^。！？!?；;]{0,64}(?:像|是|属于|算)"
        r"[^。！？!?；;]{0,16}"
        r"(?:被[^。！？!?；;]{0,8}查杀|听到[^。！？!?；;]{0,8}(?:报验|查杀)|报验)"
        r"[^。！？!?；;]{0,6}(?:后|之后)"
        r"[^。！？!?；;]{0,12}(?:应激|反应|回应|反咬)"
    ),
    re.compile(
        rf"(?P<reaction>{_SEAT_NUMBER})号[^。！？!?；;]{{0,24}}"
        rf"(?:被|听到)(?P<trigger>{_SEAT_NUMBER})号"
        r"[^。！？!?；;]{0,16}(?:查杀|报验)"
        r"[^。！？!?；;]{0,6}(?:后|之后)"
        r"[^。！？!?；;]{0,12}(?:应激|反应|回应|反咬)"
    ),
)
_EXILE_TARGET = re.compile(rf"(?:出|推|放逐|冲)(?:掉|走)?\s*(?P<seat>{_SEAT_NUMBER})号")
_WRONG_EXILE_WITCH_SUBJECT = re.compile(
    r"(?:出|推|放逐)错(?:了)?[^。！？!?；;]{0,16}"
    r"(?:你|他|她)(?:就算|要是|如果|即使)?(?:是|为)?(?:真)?女巫"
)
_FUTURE_POISON_USE = re.compile(
    r"(?:晚上|夜里|当夜)[^。！？!?；;]{0,24}"
    r"(?:出毒|毒(?:我|他|她|人|谁|掉|死|[1-9]|1[0-9]|2[0-4]))"
    r"|(?:还能|可以|能|直接|随便|想)[^。！？!?；;]{0,12}"
    r"毒(?:我|他|她|人|谁|掉|死|[1-9]|1[0-9]|2[0-4])"
)
_POISON_RESOURCE = re.compile(r"(?:毒药|有毒|留毒)")
_NO_LOSS_FROM_POISON = re.compile(
    r"(?:不亏|亏不了|不算(?:血)?亏|不耽误(?:好人)?轮次|不影响(?:好人)?轮次)"
)
_POST_ELIMINATION_ABILITY_REJECTION = re.compile(
    r"(?:不能|无法|没法|不可能|不能再|没机会|来不及|用不了)"
    r"[^。！？!?；;]{0,12}(?:毒|毒药)"
    r"|(?:毒|毒药)[^。！？!?；;]{0,12}"
    r"(?:不能|无法|没法|不可能|用不了)"
)


def observe_model_speech(
    speech: str | None,
    *,
    hard_rules: dict[str, Any],
    model_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return passive diagnostics without changing or rejecting model output."""

    try:
        if not isinstance(speech, str) or not speech.strip():
            return []
        return _observe_model_speech(
            speech,
            hard_rules=hard_rules,
            model_context=model_context,
        )
    except Exception as exc:  # Observability must never become an action gate.
        return [
            {
                "code": "model_observation_failed",
                "severity": "warning",
                "confidence": "unknown",
                "detector_version": 1,
                "error_type": type(exc).__name__,
                "effect": "observed_only",
            }
        ]


def _observe_model_speech(
    speech: str,
    *,
    hard_rules: dict[str, Any],
    model_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    cardinality_observation = _observe_wolf_cardinality(
        speech,
        werewolf_count=hard_rules.get("werewolf_count"),
    )
    if cardinality_observation is not None:
        observations.append(cardinality_observation)
    vote_observation = _observe_public_vote_facts(
        speech,
        model_context=model_context,
    )
    if vote_observation is not None:
        observations.append(vote_observation)
    ability_lifecycle_observation = _observe_post_elimination_ability(
        speech,
        hard_rules=hard_rules,
    )
    if ability_lifecycle_observation is not None:
        observations.append(ability_lifecycle_observation)
    investigation_observation = _observe_private_action_causality(
        speech,
        model_context=model_context,
    )
    if investigation_observation is not None:
        observations.append(investigation_observation)
    public_causality_observation = _observe_public_statement_causality(
        speech,
        model_context=model_context,
    )
    if public_causality_observation is not None:
        observations.append(public_causality_observation)
    observations.extend(
        _observe_response_opportunity(
            speech,
            model_context=model_context,
        )
    )
    return observations


def _observe_post_elimination_ability(
    speech: str,
    *,
    hard_rules: dict[str, Any],
) -> dict[str, Any] | None:
    lifecycle = hard_rules.get("ability_lifecycle")
    if not isinstance(lifecycle, dict):
        return None
    if lifecycle.get("active_abilities_require_alive") is not True:
        return None
    if lifecycle.get("eliminated_players_can_act_in_later_windows") is not False:
        return None
    if _POST_ELIMINATION_ABILITY_REJECTION.search(speech) is not None:
        return None

    target_seats = tuple(
        dict.fromkeys(match.group("seat") for match in _EXILE_TARGET.finditer(speech))
    )
    if not target_seats:
        return None

    signals: list[dict[str, str]] = []
    for seat in target_seats:
        explicit_subject = re.search(
            rf"{seat}号\s*(?:你\s*)?"
            r"(?:就算|要是|如果|即使)?\s*(?:是|为)?\s*(?:真)?女巫",
            speech,
        )
        subject = explicit_subject
        if subject is None and len(target_seats) == 1:
            subject = _WRONG_EXILE_WITCH_SUBJECT.search(speech)
        if subject is None:
            continue
        consequence = speech[subject.end() : subject.end() + 160]
        future_use = _FUTURE_POISON_USE.search(consequence)
        resource_justifies_exile = (
            _POISON_RESOURCE.search(consequence) is not None
            and _NO_LOSS_FROM_POISON.search(consequence) is not None
        )
        if future_use is None and not resource_justifies_exile:
            continue
        signals.append(
            {
                "target_ref": f"seat_{seat}",
                "ability_id": "witch.poison",
                "contradiction": "eliminated_player_later_active_ability",
                "evidence": _evidence(
                    speech,
                    start=subject.start(),
                    end=(
                        subject.end()
                        + (future_use.end() if future_use is not None else len(consequence))
                    ),
                ),
            }
        )

    if not signals:
        return None
    return {
        "code": "post_elimination_ability_contradiction",
        "severity": "warning",
        "confidence": "high",
        "detector_version": 1,
        "authority": "judge_fact",
        "signals": signals,
        "effect": "observed_only",
    }


def _observe_private_action_causality(
    speech: str,
    *,
    model_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(model_context, dict):
        return None
    known_events = model_context.get("known_events")
    events = known_events.get("events") if isinstance(known_events, dict) else None
    if not isinstance(events, list):
        return None

    investigations: list[dict[str, Any]] = []
    public_statements: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("kind") == "player_statement":
            public_statements.append(event)
            continue
        if event.get("visibility") != "actor_private":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        target_ref: str | None = None
        if event.get("kind") == "private_ability_action_committed":
            if data.get("ability_id") != "seer.investigate":
                continue
            decision = data.get("decision")
            result = data.get("result")
            if isinstance(decision, dict):
                target_ref = _normalized_seat_ref(decision.get("target_player_id"))
            if target_ref is None and isinstance(result, dict):
                target_ref = _normalized_seat_ref(result.get("target_player_id"))
        elif event.get("kind") == "investigation_alignment":
            target_ref = _normalized_seat_ref(data.get("target_player_id"))
        if target_ref is None:
            continue
        known_at_seq = _integer_source_value(event.get("known_at_seq"))
        if known_at_seq is None:
            continue
        investigations.append(
            {
                "event_ref": _scalar_source_value(event.get("event_ref")),
                "known_at_seq": known_at_seq,
                "target_ref": target_ref,
            }
        )

    signals: list[dict[str, Any]] = []
    for sentence_match in re.finditer(r"[^。！？!?；;]+[。！？!?；;]?", speech):
        sentence = sentence_match.group(0)
        if (
            _INVESTIGATION_REASON_MARKER.search(sentence) is None
            or _LATER_PUBLIC_INFORMATION_MARKER.search(sentence) is None
            or _INVESTIGATION_CAUSALITY_REJECTION.search(sentence) is not None
        ):
            continue
        for investigation in investigations:
            target_ref = str(investigation["target_ref"])
            target_number = target_ref.removeprefix("seat_")
            if re.search(rf"(?<!\d){re.escape(target_number)}号", sentence) is None:
                continue
            later_statement = next(
                (
                    event
                    for event in public_statements
                    if _normalized_seat_ref(event.get("speaker_ref")) == target_ref
                    and (
                        statement_seq := _integer_source_value(
                            event.get("known_at_seq", event.get("record_seq"))
                        )
                    )
                    is not None
                    and statement_seq > investigation["known_at_seq"]
                ),
                None,
            )
            if later_statement is None:
                continue
            signals.append(
                {
                    "ability_id": "seer.investigate",
                    "target_ref": target_ref,
                    "private_event_ref": investigation["event_ref"],
                    "private_action_known_at_seq": investigation["known_at_seq"],
                    "later_public_event_ref": _scalar_source_value(
                        later_statement.get("event_ref")
                    ),
                    "later_public_known_at_seq": _integer_source_value(
                        later_statement.get(
                            "known_at_seq",
                            later_statement.get("record_seq"),
                        )
                    ),
                    "evidence": sentence.strip(),
                }
            )

    if not signals:
        return None
    return {
        "code": "private_action_causality_contradiction",
        "severity": "warning",
        "confidence": "high",
        "detector_version": 1,
        "authority": "judge_fact",
        "signals": _deduplicate_causality_signals(signals),
        "effect": "observed_only",
    }


def _deduplicate_causality_signals(
    signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for signal in signals:
        identity = (
            signal.get("target_ref"),
            signal.get("private_action_known_at_seq"),
            signal.get("later_public_event_ref"),
            signal.get("evidence"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(signal)
    return deduplicated


def _observe_public_statement_causality(
    speech: str,
    *,
    model_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    claims = _public_statement_causality_claims(speech)
    if not claims or not isinstance(model_context, dict):
        return None
    known_events = model_context.get("known_events")
    events = known_events.get("events") if isinstance(known_events, dict) else None
    if not isinstance(events, list):
        return None

    statements: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("kind") != "player_statement":
            continue
        if event.get("visibility") not in (None, "public"):
            continue
        speaker_ref = _normalized_seat_ref(event.get("speaker_ref"))
        known_at_seq = _integer_source_value(event.get("known_at_seq", event.get("record_seq")))
        source_record_seq = _integer_source_value(event.get("record_seq"))
        event_ref = _scalar_source_value(event.get("event_ref"))
        statement = event.get("speech")
        if (
            speaker_ref is None
            or known_at_seq is None
            or event_ref is None
            or not isinstance(statement, str)
        ):
            continue
        statements.append(
            {
                "speaker_ref": speaker_ref,
                "known_at_seq": known_at_seq,
                "source_record_seq": source_record_seq,
                "event_ref": event_ref,
                "speech": statement,
            }
        )

    signals: list[dict[str, Any]] = []
    for claim in claims:
        reaction_ref = claim["reaction_ref"]
        trigger_speaker_ref = claim["trigger_speaker_ref"]
        reaction_events = [
            event
            for event in statements
            if event["speaker_ref"] == reaction_ref
            and _statement_reacts_to(
                event["speech"],
                target_ref=trigger_speaker_ref,
            )
        ]
        trigger_events = [
            event
            for event in statements
            if event["speaker_ref"] == trigger_speaker_ref
            and _statement_reports_check_result(
                event["speech"],
                target_ref=reaction_ref,
            )
        ]
        if not reaction_events or not trigger_events:
            continue
        earliest_trigger_seq = min(event["known_at_seq"] for event in trigger_events)
        earliest_trigger_events = [
            event for event in trigger_events if event["known_at_seq"] == earliest_trigger_seq
        ]
        if len(earliest_trigger_events) != 1:
            continue
        trigger_event = earliest_trigger_events[0]
        # A report that already existed before a qualifying response makes the
        # claimed causality possible; a later repeated report must not replace
        # that original trigger and create a latest/latest false positive.
        if any(event["known_at_seq"] >= trigger_event["known_at_seq"] for event in reaction_events):
            continue
        if len(reaction_events) != 1:
            continue
        reaction_event = reaction_events[0]
        signal = {
            "reaction_actor_ref": reaction_ref,
            "trigger_actor_ref": trigger_speaker_ref,
            "reaction_event_ref": reaction_event["event_ref"],
            "trigger_event_ref": trigger_event["event_ref"],
            "reaction_known_at_seq": reaction_event["known_at_seq"],
            "trigger_known_at_seq": trigger_event["known_at_seq"],
            "evidence": "claimed_reaction_precedes_claimed_trigger",
        }
        if reaction_event["source_record_seq"] is not None:
            signal["reaction_source_record_seq"] = reaction_event["source_record_seq"]
        if trigger_event["source_record_seq"] is not None:
            signal["trigger_source_record_seq"] = trigger_event["source_record_seq"]
        signals.append(signal)

    signals = _deduplicate_public_causality_signals(signals)
    if not signals:
        return None
    return {
        "code": "public_event_causality_contradiction",
        "severity": "warning",
        "confidence": "high",
        "detector_version": 1,
        "authority": "event_chronology",
        "signals": signals,
        "effect": "observed_only",
    }


def _public_statement_causality_claims(speech: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for sentence_match in re.finditer(r"[^。！？!?；;]+[。！？!?；;]?", speech):
        sentence = sentence_match.group(0)
        if (
            not sentence.strip()
            or _PUBLIC_CAUSALITY_REJECTION.search(sentence) is not None
            or _PUBLIC_CAUSALITY_HYPOTHESIS.search(sentence) is not None
        ):
            continue
        for pattern in _PUBLIC_REACTION_CLAIM_PATTERNS:
            for match in _overlapping_pattern_matches(pattern, sentence):
                attribution_prefix = sentence[max(0, match.start() - 40) : match.start()]
                if _PUBLIC_CAUSALITY_ATTRIBUTION.search(attribution_prefix) is not None:
                    continue
                reaction_ref = f"seat_{match.group('reaction')}"
                trigger_speaker_ref = f"seat_{match.group('trigger')}"
                if reaction_ref == trigger_speaker_ref:
                    continue
                evidence = sentence.strip()
                identity = (reaction_ref, trigger_speaker_ref, evidence)
                if identity in seen:
                    continue
                seen.add(identity)
                claims.append(
                    {
                        "reaction_ref": reaction_ref,
                        "trigger_speaker_ref": trigger_speaker_ref,
                        "evidence": evidence,
                    }
                )
    return claims


def _overlapping_pattern_matches(
    pattern: re.Pattern[str],
    value: str,
) -> list[re.Match[str]]:
    return [
        match for start in range(len(value)) if (match := pattern.match(value, start)) is not None
    ]


def _statement_reports_check_result(speech: str, *, target_ref: str) -> bool:
    target_number = target_ref.removeprefix("seat_")
    if re.search(r"(?:验|查验|报验|查杀)", speech) is None:
        return False
    patterns = (
        rf"(?:验|查验)(?:了|过)?\s*{re.escape(target_number)}号"
        rf"[^。！？!?；;]{{0,16}}(?:查杀|(?:是|为|就是)?狼)",
        rf"(?:报|给)\s*{re.escape(target_number)}号\s*(?:查杀|(?:是|为)?狼)",
        rf"(?:报|公布)\s*查杀\s*{re.escape(target_number)}号",
    )
    return any(re.search(pattern, speech) is not None for pattern in patterns)


def _statement_reacts_to(speech: str, *, target_ref: str) -> bool:
    target_number = re.escape(target_ref.removeprefix("seat_"))
    patterns = (
        rf"(?:回头猛打|猛打|反咬|攻击|咬死|咬|踩|打|回应|反驳|质疑|要出|出|冲)"
        rf"[^。！？!?；;]{{0,12}}{target_number}号",
        rf"{target_number}号[^。！？!?；;]{{0,16}}(?:是|为|像)"
        r"[^。！？!?；;]{0,10}(?:狼|悍跳)",
    )
    return any(re.search(pattern, speech) is not None for pattern in patterns)


def _deduplicate_public_causality_signals(
    signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for signal in signals:
        identity = (
            signal.get("reaction_event_ref"),
            signal.get("trigger_event_ref"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(signal)
    return deduplicated


def _observe_wolf_cardinality(
    speech: str,
    *,
    werewolf_count: Any,
) -> dict[str, Any] | None:
    if werewolf_count != 1:
        return None

    signals: list[dict[str, Any]] = []
    for signal, confidence, pattern in (
        ("double_wolf_marker", "high", _DOUBLE_WOLF_MARKER),
        ("wolf_teammate_marker", "medium", _WOLF_TEAMMATE_MARKER),
        ("explicit_wolf_pair", "high", _EXPLICIT_WOLF_PAIR),
    ):
        for match in pattern.finditer(speech):
            if _is_rejected_claim(speech, start=match.start(), end=match.end()):
                continue
            signals.append(
                {
                    "signal": signal,
                    "confidence": confidence,
                    "evidence": _evidence(speech, start=match.start(), end=match.end()),
                }
            )
            break

    if not signals:
        return None
    confidence = "high" if any(item["confidence"] == "high" for item in signals) else "medium"
    return {
        "code": "wolf_cardinality_contradiction",
        "severity": "warning",
        "confidence": confidence,
        "detector_version": 1,
        "configured_werewolf_count": 1,
        "signals": signals,
        "effect": "observed_only",
    }


def _observe_public_vote_facts(
    speech: str,
    *,
    model_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    vote_facts = _authoritative_vote_facts(model_context)
    if not vote_facts:
        return None

    conflicts: list[dict[str, Any]] = []
    for claim in _vote_claims(speech, model_context=model_context):
        claimed_target_ref = claim["claimed_target_ref"]
        for voter_ref in claim["claimed_voter_refs"]:
            facts_for_voter = [fact for fact in vote_facts if fact.get("voter_ref") == voter_ref]
            if not facts_for_voter:
                continue
            if any(fact.get("target_ref") == claimed_target_ref for fact in facts_for_voter):
                continue
            authoritative_fact = max(
                facts_for_voter,
                key=lambda item: (
                    _sequence_sort_key(item.get("record_seq")),
                    item.get("_source_order", 0),
                ),
            )
            conflict: dict[str, Any] = {
                "voter_ref": voter_ref,
                "claimed_target_ref": claimed_target_ref,
                "authoritative_target_ref": authoritative_fact.get("target_ref"),
                "evidence": claim["evidence"],
            }
            for key in ("source_event_id", "record_seq", "action_type"):
                value = authoritative_fact.get(key)
                if value is not None:
                    conflict[key] = value
            conflicts.append(conflict)

    if not conflicts:
        return None
    return {
        "code": "public_vote_fact_contradiction",
        "severity": "warning",
        "confidence": "high",
        "detector_version": 1,
        "authority": "judge_fact",
        "conflicts": conflicts,
        "effect": "observed_only",
    }


def _authoritative_vote_facts(
    model_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(model_context, dict):
        return []

    timeline = model_context.get("public_timeline")
    timeline_events: list[Any]
    if isinstance(timeline, dict):
        events = timeline.get("events")
        timeline_events = events if isinstance(events, list) else []
    else:
        timeline_events = timeline if isinstance(timeline, list) else []

    public_state = model_context.get("public_state")
    judge_facts = public_state.get("judge_facts") if isinstance(public_state, dict) else None
    candidates = [
        *timeline_events,
        *(judge_facts if isinstance(judge_facts, list) else []),
    ]
    facts: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for source_order, raw_item in enumerate(candidates):
        if not isinstance(raw_item, dict) or raw_item.get("kind") != "day_vote":
            continue
        authority = raw_item.get("authority")
        if authority not in (None, "judge", "judge_fact", "authoritative"):
            continue
        voter_ref = _normalized_seat_ref(raw_item.get("voter_ref", raw_item.get("voter_player_id")))
        target_ref = _normalized_seat_ref(
            raw_item.get("target_ref", raw_item.get("target_player_id"))
        )
        if voter_ref is None:
            continue
        source_event_id = _scalar_source_value(raw_item.get("source_event_id"))
        record_seq = _integer_source_value(raw_item.get("record_seq"))
        action_type = _string_source_value(raw_item.get("action_type"))
        dedupe_key = (
            source_event_id,
            record_seq,
            voter_ref,
            target_ref,
            action_type,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        facts.append(
            {
                "voter_ref": voter_ref,
                "target_ref": target_ref,
                "source_event_id": source_event_id,
                "record_seq": record_seq,
                "action_type": action_type,
                "_source_order": source_order,
            }
        )
    return facts


def _vote_claims(
    speech: str,
    *,
    model_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, ...], str, int, int]] = set()
    prior_addressee: str | None = None
    for sentence_match in re.finditer(r"[^。！？!?；;]+[。！？!?；;]?", speech):
        sentence = sentence_match.group(0)
        if not sentence.strip():
            continue
        for pattern in _VOTE_CLAIM_PATTERNS:
            for match in pattern.finditer(sentence):
                if _is_uncertain_or_rejected_vote_claim(
                    sentence,
                    start=match.start(),
                    end=match.end(),
                ):
                    continue
                voter_refs = tuple(
                    dict.fromkeys(
                        f"seat_{number}"
                        for number in re.findall(_SEAT_NUMBER, match.group("voters"))
                    )
                )
                if not voter_refs:
                    continue
                target = match.group("target")
                target_ref = (
                    _second_person_target(
                        speech,
                        sentence_start=sentence_match.start(),
                        absolute_start=sentence_match.start() + match.start(),
                        prior_addressee=prior_addressee,
                        model_context=model_context,
                    )
                    if target == "你"
                    else f"seat_{target}"
                )
                if target_ref is None:
                    continue
                absolute_start = sentence_match.start() + match.start()
                absolute_end = sentence_match.start() + match.end()
                dedupe_key = (voter_refs, target_ref, absolute_start, absolute_end)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                claims.append(
                    {
                        "claimed_voter_refs": list(voter_refs),
                        "claimed_target_ref": target_ref,
                        "evidence": _evidence(
                            speech,
                            start=absolute_start,
                            end=absolute_end,
                        ),
                    }
                )
        direct_matches = list(_DIRECT_ADDRESSEE.finditer(sentence))
        if direct_matches:
            prior_addressee = f"seat_{_matched_addressee(direct_matches[-1])}"
    return claims


def _observe_response_opportunity(
    speech: str,
    *,
    model_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    accusations = _silence_accusations(speech)
    if not accusations or not isinstance(model_context, dict):
        return []

    task = model_context.get("task")
    progress = task.get("speech_progress") if isinstance(task, dict) else None
    remaining_refs = (
        {ref for ref in progress.get("remaining_speaker_refs", []) if isinstance(ref, str)}
        if isinstance(progress, dict)
        else set()
    )
    question_contexts = _open_question_contexts(model_context)

    premature_signals: list[dict[str, Any]] = []
    prior_explanation_signals: list[dict[str, Any]] = []
    for accusation in accusations:
        target_ref = accusation["target_ref"]
        target_questions = [
            question for question in question_contexts if question.get("addressed_to") == target_ref
        ]
        awaiting_turn = target_ref in remaining_refs or any(
            question.get("reply_opportunity") == "awaiting_scheduled_turn"
            for question in target_questions
        )
        question_refs = [
            str(question["question_id"])
            for question in target_questions
            if isinstance(question.get("question_id"), str)
        ]
        if awaiting_turn:
            premature_signals.append(
                {
                    "target_ref": target_ref,
                    "reply_opportunity": "awaiting_scheduled_turn",
                    "question_refs": question_refs,
                    "evidence": accusation["evidence"],
                }
            )
        prior_ref_field = (
            "prior_relevant_event_refs"
            if _uses_projected_v9_discourse(model_context)
            else "prior_relevant_statement_refs"
        )
        prior_refs = list(
            dict.fromkeys(
                ref
                for question in target_questions
                for ref in question.get(prior_ref_field, [])
                if isinstance(ref, str)
            )
        )
        if prior_refs:
            prior_explanation_signals.append(
                {
                    "target_ref": target_ref,
                    prior_ref_field: prior_refs,
                    "question_refs": question_refs,
                    "evidence": accusation["evidence"],
                }
            )

    observations: list[dict[str, Any]] = []
    if premature_signals:
        observations.append(
            {
                "code": "premature_silence_accusation",
                "severity": "warning",
                "confidence": "high",
                "detector_version": 1,
                "signals": _deduplicate_signals(premature_signals),
                "effect": "observed_only",
            }
        )
    if prior_explanation_signals:
        observations.append(
            {
                "code": "prior_explanation_denial",
                "severity": "warning",
                "confidence": "medium",
                "detector_version": 1,
                "signals": _deduplicate_signals(prior_explanation_signals),
                "effect": "observed_only",
            }
        )
    return observations


def _silence_accusations(speech: str) -> list[dict[str, str]]:
    accusations: list[dict[str, str]] = []
    prior_addressee: str | None = None
    seen: set[tuple[str, str]] = set()
    for sentence_match in re.finditer(r"[^。！？!?；;]+[。！？!?；;]?", speech):
        sentence = sentence_match.group(0)
        if not sentence.strip():
            continue
        direct_matches = list(_DIRECT_ADDRESSEE.finditer(sentence))
        direct_target = f"seat_{_matched_addressee(direct_matches[-1])}" if direct_matches else None
        target_match = _SILENCE_TARGET_BEFORE.search(sentence)
        marker_match = _SILENCE_MARKER.search(sentence)
        marker_prefix = sentence[: marker_match.start()] if marker_match is not None else ""
        if (
            marker_match is not None
            and _SILENCE_NON_ACCUSATION.search(sentence) is None
            and _SILENCE_ATTRIBUTION.search(marker_prefix) is None
        ):
            target_ref = (
                f"seat_{target_match.group('seat')}"
                if target_match is not None
                else direct_target or prior_addressee
            )
            if target_ref is not None and not _is_rejected_claim(
                sentence,
                start=marker_match.start(),
                end=marker_match.end(),
            ):
                absolute_start = sentence_match.start() + marker_match.start()
                absolute_end = sentence_match.start() + marker_match.end()
                evidence = _evidence(speech, start=absolute_start, end=absolute_end)
                identity = (target_ref, evidence)
                if identity not in seen:
                    seen.add(identity)
                    accusations.append(
                        {
                            "target_ref": target_ref,
                            "evidence": evidence,
                        }
                    )
        if direct_target is not None:
            prior_addressee = direct_target
    return accusations


def _open_question_contexts(
    model_context: dict[str, Any],
) -> list[dict[str, Any]]:
    if _uses_projected_v9_discourse(model_context):
        known_events = model_context["known_events"]
        events = known_events.get("events")
        questions = known_events.get("questions")
        relations = known_events.get("relations")
        if not isinstance(events, list) or not isinstance(questions, list):
            return []
        relations = relations if isinstance(relations, list) else []
        event_refs = {
            event["event_ref"]
            for event in events
            if isinstance(event, dict) and isinstance(event.get("event_ref"), str)
        }
        answered_question_ids = {
            relation["to_question_id"]
            for relation in relations
            if isinstance(relation, dict)
            and relation.get("type") == "answers_question"
            and relation.get("temporal_order_valid") is True
            and isinstance(relation.get("to_question_id"), str)
            and isinstance(relation.get("from_event_ref"), str)
            and relation["from_event_ref"] in event_refs
        }
        projected_questions: list[dict[str, Any]] = []
        for question in questions:
            if (
                not isinstance(question, dict)
                or question.get("status") != "open"
                or not isinstance(question.get("addressed_to"), str)
                or not isinstance(question.get("question_id"), str)
                or question["question_id"] in answered_question_ids
                or not isinstance(question.get("source_event_ref"), str)
                or question["source_event_ref"] not in event_refs
            ):
                continue
            item = dict(question)
            prior_refs = item.get("prior_relevant_event_refs")
            if isinstance(prior_refs, list):
                item["prior_relevant_event_refs"] = [
                    ref for ref in prior_refs if isinstance(ref, str) and ref in event_refs
                ]
            else:
                item.pop("prior_relevant_event_refs", None)
            projected_questions.append(item)
        return projected_questions

    history = model_context.get("history")
    if not isinstance(history, dict):
        return []
    questions = history.get("questions")
    if not isinstance(questions, list):
        return []
    return [
        question
        for question in questions
        if isinstance(question, dict)
        and question.get("status") == "open"
        and isinstance(question.get("addressed_to"), str)
    ]


def _uses_projected_v9_discourse(model_context: dict[str, Any]) -> bool:
    known_events = model_context.get("known_events")
    return isinstance(known_events, dict) and known_events.get("schema_version") == 3


def _deduplicate_signals(
    signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for signal in signals:
        identity = (
            signal.get("target_ref"),
            signal.get("reply_opportunity"),
            tuple(signal.get("prior_relevant_statement_refs", [])),
            tuple(signal.get("prior_relevant_event_refs", [])),
            signal.get("evidence"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(signal)
    return deduplicated


def _is_uncertain_or_rejected_vote_claim(
    sentence: str,
    *,
    start: int,
    end: int,
) -> bool:
    before = sentence[max(0, start - 10) : start]
    attribution_prefix = sentence[max(0, start - 32) : start]
    claim = sentence[start:end]
    after = sentence[end : min(len(sentence), end + 12)]
    return (
        _VOTE_CLAIM_REJECTION.search(before + claim + after) is not None
        or _VOTE_CLAIM_UNCERTAINTY.search(before + claim) is not None
        or _VOTE_CLAIM_ATTRIBUTION.search(attribution_prefix) is not None
        or _VOTE_CLAIM_QUESTION_SUFFIX.search(after) is not None
    )


def _second_person_target(
    speech: str,
    *,
    sentence_start: int,
    absolute_start: int,
    prior_addressee: str | None,
    model_context: dict[str, Any] | None,
) -> str | None:
    prefix = speech[max(sentence_start, absolute_start - 80) : absolute_start]
    direct_matches = list(_DIRECT_ADDRESSEE.finditer(prefix))
    if direct_matches:
        return f"seat_{_matched_addressee(direct_matches[-1])}"
    if prior_addressee is not None:
        return prior_addressee

    if not isinstance(model_context, dict):
        return None
    history = model_context.get("history")
    if not isinstance(history, dict):
        return None
    focus = history.get("focus")
    questions = history.get("questions")
    if not isinstance(focus, dict) or not isinstance(questions, list):
        return None
    open_refs = focus.get("open_question_refs")
    if not isinstance(open_refs, list):
        return None
    open_ref_set = {item for item in open_refs if isinstance(item, str)}
    askers = {
        normalized_asker
        for question in questions
        if isinstance(question, dict)
        and question.get("question_id") in open_ref_set
        and (normalized_asker := _normalized_seat_ref(question.get("asked_by"))) is not None
    }
    return next(iter(askers)) if len(askers) == 1 else None


def _matched_addressee(match: re.Match[str]) -> str:
    return next(value for value in match.groupdict().values() if value is not None)


def _normalized_seat_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"seat_(?P<number>[1-9]|1[0-9]|2[0-4])", value)
    if match is not None:
        return f"seat_{match.group('number')}"
    match = re.fullmatch(r"(?P<number>[1-9]|1[0-9]|2[0-4])号?", value)
    if match is not None:
        return f"seat_{match.group('number')}"
    return None


def _sequence_sort_key(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _scalar_source_value(value: Any) -> str | int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (str, int)) else None


def _integer_source_value(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string_source_value(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _is_rejected_claim(speech: str, *, start: int, end: int) -> bool:
    before = speech[max(0, start - 8) : start]
    after = speech[end : min(len(speech), end + 18)]
    return (
        _NEGATION_OR_REJECTION.search(before) is not None
        or _NEGATION_OR_REJECTION.search(after) is not None
    )


def _evidence(speech: str, *, start: int, end: int) -> str:
    return speech[max(0, start - 24) : min(len(speech), end + 24)].strip()


__all__ = ["observe_model_speech"]
