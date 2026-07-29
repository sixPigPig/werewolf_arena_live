from __future__ import annotations

from app.v2.discourse_ledger import build_public_discourse_ledger


def _statement(
    source_event_id: int,
    *,
    speaker_ref: str,
    speech: str,
    round_no: int = 1,
    stage: str = "sheriff_campaign_speech",
) -> dict[str, object]:
    return {
        "source_event_id": str(source_event_id),
        "uttered_record_seq": source_event_id,
        "occurred_in": {"period": "day", "round_no": round_no},
        "stage": stage,
        "speaker_ref": speaker_ref,
        "speech": speech,
    }


def test_ledger_keeps_prior_plan_separate_from_later_open_question() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                389,
                speaker_ref="seat_8",
                speech=(
                    "8号玩家上警竞选警长，我跳预言家。"
                    "昨晚首验6号，法官给我的结果是好人。"
                    "警徽流我先留一个方向：今晚我会优先验警上发言里最拧巴的牌。"
                    "具体等大家发完言我再锁定。"
                ),
            ),
            _statement(
                406,
                speaker_ref="seat_9",
                speech="8号你今晚第一验锁谁，你现在能不能给我一个明确方向？",
            ),
            _statement(
                423,
                speaker_ref="seat_10",
                speech=("9号问你的问题，你确实没有给明确方向，只说优先验警上最拧巴的牌。"),
            ),
        ],
        current_round_no=1,
        actor_ref="seat_9",
    )

    assert [item["record_seq"] for item in ledger["statements"]] == [389, 406, 423]
    future_plans = [
        claim for claim in ledger["claims"] if claim["claim_type"] == "future_investigation_plan"
    ]
    assert [(claim["speaker_ref"], claim["uttered_record_seq"]) for claim in future_plans] == [
        ("seat_8", 389)
    ]
    assert future_plans[0]["exact_quote"] == (
        "警徽流我先留一个方向：今晚我会优先验警上发言里最拧巴的牌。"
    )
    assert ledger["questions"] == [
        {
            "question_id": "question_406_1",
            "source_event_id": "406",
            "source_sentence_id": "sentence_406_1",
            "sentence_index": 1,
            "asked_turn_index": 2,
            "asked_by": "seat_9",
            "addressed_to": "seat_8",
            "asked_in": {"period": "day", "round_no": 1},
            "stage": "sheriff_campaign_speech",
            "topic": "future_investigation_target",
            "exact_quote": "8号你今晚第一验锁谁，你现在能不能给我一个明确方向？",
            "status": "open",
            "confirmation_status": "speaker_asked_publicly",
            "asked_record_seq": 406,
        }
    ]
    assert ledger["relations"] == []
    paraphrase = next(
        claim for claim in ledger["claims"] if claim["claim_type"] == "secondary_paraphrase"
    )
    assert paraphrase["source_event_id"] == "423"
    assert paraphrase["source_kind"] == "secondary_unverified_paraphrase"
    assert paraphrase["asserted_relation_type"] == "reported_response"
    assert paraphrase["temporal_relation_status"] == "unverified"


def test_ledger_only_closes_question_with_later_target_speech() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                389,
                speaker_ref="seat_8",
                speech="今晚优先验警上发言里最拧巴的牌。",
            ),
            _statement(
                406,
                speaker_ref="seat_9",
                speech="8号你今晚具体验谁？",
            ),
            _statement(
                423,
                speaker_ref="seat_10",
                speech="9号问过8号具体验谁。",
            ),
            _statement(
                440,
                speaker_ref="seat_8",
                speech="回应9号的问题，今晚我会验2号。",
            ),
        ],
        current_round_no=1,
        actor_ref="seat_9",
    )

    question = ledger["questions"][0]
    assert question["status"] == "answered"
    assert question["asked_record_seq"] == 406
    assert question["answer_record_seq"] == 440
    assert ledger["relations"] == [
        {
            "relation_id": "relation_440_question_406_1",
            "relation_type": "answers_question",
            "from_source_event_id": "440",
            "from_speaker_ref": "seat_8",
            "from_turn_index": 4,
            "to_question_id": "question_406_1",
            "to_source_event_id": "406",
            "to_turn_index": 2,
            "temporal_order_valid": True,
            "confirmation_status": "deterministic_speaker_time_and_topic_match",
            "from_record_seq": 440,
            "to_record_seq": 406,
        }
    ]


def test_ledger_orders_source_events_before_building_temporal_relations() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                406,
                speaker_ref="seat_9",
                speech="8号你今晚具体验谁？",
            ),
            _statement(
                389,
                speaker_ref="seat_8",
                speech="今晚我会验发言最拧巴的牌。",
            ),
        ],
        current_round_no=1,
        actor_ref="seat_9",
    )

    assert [statement["record_seq"] for statement in ledger["statements"]] == [389, 406]
    assert ledger["questions"][0]["status"] == "open"
    assert ledger["relations"] == []


def test_ledger_rejects_older_record_seq_when_some_events_lack_sequence() -> None:
    unsequenced = _statement(
        420,
        speaker_ref="seat_1",
        speech="1号先继续听。",
    )
    unsequenced.pop("uttered_record_seq")
    ledger = build_public_discourse_ledger(
        [
            _statement(
                406,
                speaker_ref="seat_9",
                speech="8号你今晚具体验谁？",
            ),
            _statement(
                389,
                speaker_ref="seat_8",
                speech="今晚我会验2号。",
            ),
            unsequenced,
        ],
        current_round_no=1,
        actor_ref="seat_9",
    )

    assert ledger["questions"][0]["status"] == "open"
    assert ledger["relations"] == []


def test_ledger_keeps_prior_questions_without_cross_round_answers() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                406,
                speaker_ref="seat_9",
                round_no=1,
                speech="8号你今晚具体验谁？",
            ),
            _statement(
                500,
                speaker_ref="seat_8",
                round_no=2,
                speech="今晚我会验2号。",
            ),
        ],
        current_round_no=2,
        actor_ref="seat_8",
    )

    assert len(ledger["questions"]) == 1
    assert ledger["questions"][0]["status"] == "open"
    assert ledger["questions"][0]["asked_in"]["round_no"] == 1
    assert ledger["relations"] == []


def test_ledger_preserves_first_party_investigation_before_later_motive_claims() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                400,
                speaker_ref="seat_6",
                speech="6号上警，我先听后置位怎么说。",
            ),
            _statement(
                417,
                speaker_ref="seat_8",
                speech=(
                    "8号底牌预言家，昨晚验6号，查杀。现在回头看6号刚才的发言，我认为他在带节奏。"
                ),
            ),
            _statement(
                597,
                speaker_ref="seat_9",
                stage="day_debate_speech",
                speech="8号因为6号发言带节奏，所以昨晚验了6号。",
            ),
        ],
        current_round_no=1,
        actor_ref="seat_12",
    )

    investigation = next(
        claim for claim in ledger["claims"] if claim["claim_type"] == "investigation_claim"
    )
    assert investigation["source_event_id"] == "417"
    assert investigation["uttered_record_seq"] == 417
    assert investigation["claimed_action_in"] == {"period": "night", "round_no": 1}
    assert investigation["target_ref"] == "seat_6"
    assert investigation["claimed_result"] == "werewolves"
    later_account = next(
        claim
        for claim in ledger["claims"]
        if claim["source_event_id"] == "597" and claim["claim_type"] == "secondary_paraphrase"
    )
    assert later_account["source_kind"] == "secondary_unverified_paraphrase"


def test_ledger_does_not_promote_ambiguous_investigation_reference_to_first_party() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                430,
                speaker_ref="seat_5",
                speech="昨晚验6号这个说法不可信，我还要继续听。",
            )
        ],
        current_round_no=1,
        actor_ref="seat_5",
    )

    assert all(claim["claim_type"] != "investigation_claim" for claim in ledger["claims"])


def test_ledger_keeps_all_prior_speech_and_marks_unparsed_sources() -> None:
    prior = _statement(
        100,
        speaker_ref="seat_3",
        round_no=1,
        speech="这是一段无法可靠归类、但仍需保留的完整原话。",
    )
    current = _statement(
        200,
        speaker_ref="seat_4",
        round_no=2,
        speech="4号今天先听大家发言。",
    )

    first = build_public_discourse_ledger(
        [prior, current],
        current_round_no=2,
        actor_ref="seat_4",
    )
    second = build_public_discourse_ledger(
        [prior, current],
        current_round_no=2,
        actor_ref="seat_4",
    )

    assert first == second
    assert first["ledger_schema_version"] == 2
    assert first["statements"][0]["source_event_id"] == "100"
    assert first["statements"][0]["speech"] == prior["speech"]
    assert first["unparsed_statement_refs"] == ["100", "200"]
