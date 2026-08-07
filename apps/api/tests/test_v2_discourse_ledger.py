from __future__ import annotations

from app.v2.discourse_ledger import build_public_discourse_ledger
from app.v2.discourse_model_view import build_discourse_model_view


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


def _game_vote_reason_statements() -> list[dict[str, object]]:
    return [
        _statement(
            1226,
            speaker_ref="seat_8",
            stage="day_debate_speech",
            speech="10号，你当时为什么急着归12不归11？",
        ),
        _statement(
            1248,
            speaker_ref="seat_3",
            stage="day_debate_speech",
            speech=(
                "1号在警徽流里要验，5号警徽票投1扎眼，10号我等会听你解释为什么急着归12不压一轮。"
            ),
        ),
        _statement(
            1259,
            speaker_ref="seat_2",
            stage="day_debate_speech",
            speech="10号你等会必须解释为什么急着归12、不多压一轮。",
        ),
        _statement(
            1270,
            speaker_ref="seat_1",
            stage="day_debate_speech",
            speech="先回3号：9号警徽流留我，是因为没验过、想后置位补信息，不是查杀。",
        ),
        _statement(
            1281,
            speaker_ref="seat_10",
            stage="day_debate_speech",
            speech=(
                "我先把话说明白。昨天归12，是根据当时信息判断："
                "11、12发言几乎同模板，12又急着抗推5号，我作为警长必须给方向。"
            ),
        ),
    ]


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


def test_model_view_distinguishes_prior_explanation_from_awaiting_reply_turn() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                437,
                speaker_ref="seat_5",
                speech=(
                    "5号是真预言家，第一晚首验1号没什么特殊心路，就是随便选的。"
                    "警徽流先留8号排警下坑，再留警上的9号多攒信息。"
                ),
            ),
            _statement(
                471,
                speaker_ref="seat_9",
                speech="5号你首验为什么选1号？5号你警徽流为什么留9号？",
            ),
            _statement(
                771,
                speaker_ref="seat_9",
                stage="day_debate_speech",
                speech="5号到现在一个字都没解释。",
            ),
        ],
        current_round_no=1,
        actor_ref="seat_8",
    )

    model_view, metadata = build_discourse_model_view(
        ledger,
        actor_ref="seat_8",
        task={
            "action_type": "day_debate_speech",
            "speech_order": [
                "seat_4",
                "seat_3",
                "seat_2",
                "seat_1",
                "seat_12",
                "seat_11",
                "seat_10",
                "seat_9",
                "seat_8",
                "seat_7",
                "seat_6",
                "seat_5",
            ],
        },
        candidate_refs=[],
        latest_vote_result_ref=None,
    )

    open_questions = [
        question for question in model_view["questions"] if question["status"] == "open"
    ]
    assert len(open_questions) == 2
    assert {question["topic"] for question in open_questions} == {
        "investigation_reason",
        "sheriff_plan",
    }
    assert all(
        question["status_semantics"] == "no_response_after_question" for question in open_questions
    )
    assert all(
        question["reply_opportunity"] == "awaiting_scheduled_turn" for question in open_questions
    )
    assert all(question["prior_relevant_statement_refs"] == ["437"] for question in open_questions)
    assert model_view["focus"]["first_party_relevant_statement_refs"] == ["437"]
    assert {
        context["reply_opportunity"] for context in model_view["focus"]["open_question_contexts"]
    } == {"awaiting_scheduled_turn"}
    assert metadata["awaiting_scheduled_turn_question_count"] == 2
    assert metadata["prior_relevant_statement_question_count"] == 2
    assert "不表示被提问者此前从未解释" in model_view["source_rules"]["open_question_rule"]
    assert "不得描述成拒绝回应" in model_view["source_rules"]["turn_opportunity_rule"]


def test_ledger_does_not_reuse_seat_8_for_seat_6_self_or_table_questions() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                448,
                speaker_ref="seat_6",
                stage="day_debate_speech",
                speech=(
                    "8号大概率会跳预言家或者跳女巫来搅浑水，你们要心里有数。"
                    "我为什么要这个警徽？"
                    "因为我手握查杀，必须有1.5票的归票权确保8号今天出局。"
                    "后续如果有人对跳预言家，你们看他给的是什么结果——"
                    "如果他也说查杀8号，那就是蹭我的力度；"
                    "如果他给的是金水或者查杀别人，那就是狼人悍跳。"
                ),
            )
        ],
        current_round_no=1,
        actor_ref="seat_8",
    )

    assert [
        (question["exact_quote"], question["addressed_to"], question["status"])
        for question in ledger["questions"]
    ] == [
        ("我为什么要这个警徽？", None, "unresolved_target"),
        (
            "后续如果有人对跳预言家，你们看他给的是什么结果——"
            "如果他也说查杀8号，那就是蹭我的力度；"
            "如果他给的是金水或者查杀别人，那就是狼人悍跳。",
            None,
            "unresolved_target",
        ),
    ]


def test_ledger_reuses_explicit_addressee_only_for_singular_you_continuation() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                449,
                speaker_ref="seat_6",
                stage="day_debate_speech",
                speech=(
                    "8号先别回避。"
                    "你今晚具体验谁？"
                    "我为什么要相信你？"
                    "大家该怎么看？"
                    "你们觉得呢？"
                    "如果有人对跳怎么办？"
                ),
            )
        ],
        current_round_no=1,
        actor_ref="seat_8",
    )

    assert [
        (question["exact_quote"], question["addressed_to"], question["status"])
        for question in ledger["questions"]
    ] == [
        ("你今晚具体验谁？", "seat_8", "open"),
        ("我为什么要相信你？", None, "unresolved_target"),
        ("大家该怎么看？", None, "unresolved_target"),
        ("你们觉得呢？", None, "unresolved_target"),
        ("如果有人对跳怎么办？", None, "unresolved_target"),
    ]


def test_ledger_v3_uses_nearest_question_target_without_changing_frozen_v2() -> None:
    statement = _statement(
        326,
        speaker_ref="seat_8",
        speech=(
            "1号聊得挺稳，说要盯带节奏；6号嘛，说预言家聊不清警徽就替好人接住，"
            "但我想问一句，你凭什么替好人接？你有判断狼人的专属渠道吗？"
        ),
    )

    frozen_v2 = build_public_discourse_ledger(
        [statement],
        current_round_no=1,
        ledger_schema_version=2,
    )
    current_v3 = build_public_discourse_ledger(
        [statement],
        current_round_no=1,
        ledger_schema_version=3,
    )

    assert [question["addressed_to"] for question in frozen_v2["questions"]] == [
        "seat_1",
        "seat_1",
    ]
    assert [question["addressed_to"] for question in current_v3["questions"]] == [
        "seat_6",
        "seat_6",
    ]
    assert [question["exact_quote"] for question in current_v3["questions"]] == [
        "1号聊得挺稳，说要盯带节奏；6号嘛，说预言家聊不清警徽就替好人接住，"
        "但我想问一句，你凭什么替好人接？",
        "你有判断狼人的专属渠道吗？",
    ]


def test_ledger_v3_resolves_game_vote_reason_questions_only_with_target_answer() -> None:
    ledger = build_public_discourse_ledger(
        _game_vote_reason_statements(),
        current_round_no=1,
        ledger_schema_version=3,
    )

    assert [question["question_id"] for question in ledger["questions"]] == [
        "question_1226_1",
        "question_1248_1",
        "question_1259_1",
    ]
    assert {
        (
            question["addressed_to"],
            question["topic"],
            question["status"],
            question.get("answer_source_event_id"),
        )
        for question in ledger["questions"]
    } == {("seat_10", "vote_reason", "answered", "1281")}
    assert len(ledger["relations"]) == 3
    assert {relation["from_source_event_id"] for relation in ledger["relations"]} == {"1281"}
    assert all(relation["from_source_event_id"] != "1270" for relation in ledger["relations"])


def test_ledger_v4_projects_prior_investigation_report_without_backdating_answer() -> None:
    statements = [
        _statement(
            460,
            speaker_ref="seat_5",
            speech="5号预言家，首夜验了1号，是狼人查杀。警徽流暂时不想死留。",
        ),
        _statement(
            732,
            speaker_ref="seat_8",
            stage="day_debate_speech",
            speech="现在天亮了，5号昨晚验了谁、什么结果，该报了吧？",
        ),
    ]

    ledger = build_public_discourse_ledger(
        statements,
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert len(ledger["questions"]) == 1
    question = ledger["questions"][0]
    assert question["addressed_to"] == "seat_5"
    assert question["address_resolution"] == "resolved"
    assert question["topic"] == "past_investigation_result"
    assert question["status"] == "open"
    assert "answer_source_event_id" not in question
    assert ledger["relations"] == []

    model_view, metadata = build_discourse_model_view(
        ledger,
        actor_ref="seat_8",
        task={
            "action_type": "day_debate_speech",
            "speech_order": ["seat_8", "seat_7", "seat_6", "seat_5"],
        },
        candidate_refs=[],
        latest_vote_result_ref=None,
        model_view_schema_version=4,
    )

    projected = model_view["questions"][0]
    assert projected["status"] == "open"
    assert projected["prior_relevant_statement_refs"] == ["460"]
    assert projected["prior_coverage"] == "already_publicly_reported"
    assert metadata["prior_coverage_question_count"] == 1
    assert "此前报告不是对后来问题的回答" in model_view["source_rules"][
        "prior_coverage_rule"
    ]

    frozen_view, frozen_metadata = build_discourse_model_view(
        ledger,
        actor_ref="seat_8",
        task={"action_type": "day_debate_speech"},
        candidate_refs=[],
        latest_vote_result_ref=None,
        model_view_schema_version=3,
    )
    assert "address_resolution" not in frozen_view["questions"][0]
    assert "prior_coverage" not in frozen_view["questions"][0]
    assert "prior_coverage_rule" not in frozen_view["source_rules"]
    assert "prior_coverage_question_count" not in frozen_metadata


def test_ledger_v4_keeps_v3_question_shape_and_semantics_frozen() -> None:
    statement = _statement(
        732,
        speaker_ref="seat_8",
        stage="day_debate_speech",
        speech="现在天亮了，5号昨晚验了谁、什么结果，该报了吧？",
    )

    frozen_v3 = build_public_discourse_ledger(
        [statement],
        current_round_no=1,
        ledger_schema_version=3,
    )
    current_v4 = build_public_discourse_ledger(
        [statement],
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert frozen_v3["questions"][0]["addressed_to"] is None
    assert frozen_v3["questions"][0]["topic"] == "future_investigation_target"
    assert frozen_v3["questions"][0]["status"] == "unresolved_target"
    assert "address_resolution" not in frozen_v3["questions"][0]
    assert "question_address_rule" not in frozen_v3["source_rules"]
    assert current_v4["questions"][0]["addressed_to"] == "seat_5"
    assert current_v4["questions"][0]["topic"] == "past_investigation_result"
    assert current_v4["questions"][0]["status"] == "open"
    assert current_v4["questions"][0]["address_resolution"] == "resolved"
    assert "address_resolution 单独表示" in current_v4["source_rules"][
        "question_address_rule"
    ]


def test_ledger_v4_separates_question_status_from_address_resolution() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                733,
                speaker_ref="seat_8",
                stage="day_debate_speech",
                speech="大家觉得昨晚验了谁、结果是什么？",
            )
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    question = ledger["questions"][0]
    assert question["status"] == "open"
    assert question["addressed_to"] is None
    assert question["address_resolution"] == "unresolved"


def test_ledger_v4_splits_semicolon_enumeration_into_distinct_question_topics() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                770,
                speaker_ref="seat_6",
                stage="day_debate_speech",
                speech=(
                    "5号我问你两点：第一，报一下昨晚验了谁、什么结果；"
                    "第二，警徽流怎么留？"
                ),
            )
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert [question["topic"] for question in ledger["questions"]] == [
        "past_investigation_result",
        "sheriff_plan",
    ]
    assert [question["addressed_to"] for question in ledger["questions"]] == [
        "seat_5",
        "seat_5",
    ]
    assert all(
        question["address_resolution"] == "resolved" for question in ledger["questions"]
    )


def test_ledger_v4_splits_multiple_chinese_enumerated_issues_without_semicolon() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                771,
                speaker_ref="seat_6",
                stage="day_debate_speech",
                speech=(
                    "5号我问你两点：第一，报一下昨晚验了谁、什么结果，"
                    "第二，今晚准备验谁，第三，警徽流怎么留？"
                ),
            )
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert [question["topic"] for question in ledger["questions"]] == [
        "past_investigation_result",
        "future_investigation_plan",
        "sheriff_plan",
    ]
    assert all(question["addressed_to"] == "seat_5" for question in ledger["questions"])


def test_ledger_v4_does_not_treat_bare_interrogative_word_as_a_question() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                772,
                speaker_ref="seat_6",
                stage="day_debate_speech",
                speech="我现在还不知道谁是狼，5号也不知道谁是狼，继续听后面的发言。",
            )
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert ledger["questions"] == []


def test_ledger_v4_does_not_treat_future_first_check_as_past_result() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                773,
                speaker_ref="seat_6",
                stage="day_debate_speech",
                speech="5号你今晚首验谁？",
            )
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert ledger["questions"][0]["topic"] == "future_investigation_plan"


def test_ledger_v4_keeps_past_investigation_reason_distinct_from_result() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                774,
                speaker_ref="seat_6",
                stage="day_debate_speech",
                speech="5号你首夜为什么验1号？",
            )
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert ledger["questions"][0]["topic"] == "investigation_reason"


def test_ledger_never_promotes_attributed_reports_to_current_speaker_claims() -> None:
    statements = [
        _statement(
            800,
            speaker_ref="seat_8",
            speech="5号说我是预言家。",
        ),
        _statement(
            801,
            speaker_ref="seat_8",
            speech="5号说今晚我会验9号。",
        ),
        _statement(
            802,
            speaker_ref="seat_8",
            speech="我是预言家。昨晚5号验1号查杀，我不认。",
        ),
    ]

    ledger = build_public_discourse_ledger(
        statements,
        current_round_no=1,
        ledger_schema_version=4,
    )
    claims_by_source = {
        source_id: [
            claim for claim in ledger["claims"] if claim["source_event_id"] == source_id
        ]
        for source_id in ("800", "801", "802")
    }

    assert {claim["claim_type"] for claim in claims_by_source["800"]} == {
        "secondary_paraphrase"
    }
    assert {claim["claim_type"] for claim in claims_by_source["801"]} == {
        "secondary_paraphrase"
    }
    assert {claim["claim_type"] for claim in claims_by_source["802"]} == {
        "role_claim",
        "secondary_paraphrase",
        "player_assessment",
    }
    assert all(
        claim["claim_type"] != "investigation_claim" for claim in claims_by_source["802"]
    )


def test_ledger_v2_preserves_legacy_claim_projection_for_frozen_v7() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(800, speaker_ref="seat_8", speech="5号说我是预言家。"),
            _statement(801, speaker_ref="seat_8", speech="5号说今晚我会验9号。"),
            _statement(
                802,
                speaker_ref="seat_8",
                speech="我是预言家。昨晚5号验1号查杀，我不认。",
            ),
            _statement(803, speaker_ref="seat_8", speech="今晚我不会验9号。"),
        ],
        current_round_no=1,
        ledger_schema_version=2,
    )

    claims_by_source = {
        source_id: [
            claim["claim_type"]
            for claim in ledger["claims"]
            if claim["source_event_id"] == source_id
        ]
        for source_id in ("800", "801", "802", "803")
    }
    assert claims_by_source == {
        "800": ["secondary_paraphrase", "role_claim"],
        "801": ["secondary_paraphrase", "future_investigation_plan"],
        "802": ["role_claim", "investigation_claim", "player_assessment"],
        "803": ["future_investigation_plan"],
    }
    model_view, _ = build_discourse_model_view(
        ledger,
        actor_ref="seat_8",
        task={"action_type": "day_debate_speech"},
        candidate_refs=[],
        latest_vote_result_ref=None,
        model_view_schema_version=2,
    )
    assert [
        [annotation["claim_type"] for annotation in statement["annotations"]]
        for statement in model_view["timeline"]
    ] == list(claims_by_source.values())


def test_ledger_omits_hypothetical_and_negated_first_party_claims() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(810, speaker_ref="seat_8", speech="如果我是预言家，我会先听发言。"),
            _statement(811, speaker_ref="seat_8", speech="别说我是预言家，这话不成立。"),
            _statement(812, speaker_ref="seat_8", speech="如果今晚我验9号，只是假设。"),
            _statement(813, speaker_ref="seat_8", speech="今晚我不会验9号。"),
            _statement(814, speaker_ref="seat_8", speech="今晚我没打算验9号。"),
            _statement(815, speaker_ref="seat_8", speech="今晚我不要验9号。"),
            _statement(
                816,
                speaker_ref="seat_8",
                speech="我是预言家。昨晚我没有验9号。",
            ),
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    claims_by_source = {
        source_id: [
            claim for claim in ledger["claims"] if claim["source_event_id"] == source_id
        ]
        for source_id in {str(value) for value in range(810, 817)}
    }
    assert all(
        claim["claim_type"] != "role_claim"
        for source_id in ("810", "811")
        for claim in claims_by_source[source_id]
    )
    assert all(
        claim["claim_type"] != "future_investigation_plan"
        for source_id in ("812", "813", "814", "815")
        for claim in claims_by_source[source_id]
    )
    assert all(
        claim["claim_type"] != "investigation_claim"
        for claim in claims_by_source["816"]
    )


def test_ledger_uses_final_non_negated_investigation_result() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                820,
                speaker_ref="seat_5",
                speech="我是预言家，昨晚验1号，不是狼人，是好人。",
            ),
            _statement(
                821,
                speaker_ref="seat_5",
                speech="我是预言家，昨晚验2号，不是查杀，是金水。",
            ),
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    investigations = [
        claim for claim in ledger["claims"] if claim["claim_type"] == "investigation_claim"
    ]
    assert [(claim["target_ref"], claim["claimed_result"]) for claim in investigations] == [
        ("seat_1", "villagers"),
        ("seat_2", "villagers"),
    ]


def test_ledger_v4_treats_completed_investigation_wording_as_past_report() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(830, speaker_ref="seat_6", speech="5号你验了谁？"),
            _statement(831, speaker_ref="seat_6", speech="5号你验人结果是什么？"),
            _statement(832, speaker_ref="seat_6", speech="5号你首验谁？"),
            _statement(833, speaker_ref="seat_6", speech="5号你今晚首验谁？"),
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert [question["topic"] for question in ledger["questions"]] == [
        "past_investigation_result",
        "past_investigation_result",
        "past_investigation_result",
        "future_investigation_plan",
    ]


def test_model_view_prior_coverage_requires_first_party_investigation_claim() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                840,
                speaker_ref="seat_5",
                speech="我是预言家，昨晚我没有验1号。",
            ),
            _statement(
                841,
                speaker_ref="seat_8",
                stage="day_debate_speech",
                speech="5号你昨晚验了谁、什么结果？",
            ),
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    model_view, metadata = build_discourse_model_view(
        ledger,
        actor_ref="seat_8",
        task={"action_type": "day_debate_speech"},
        candidate_refs=[],
        latest_vote_result_ref=None,
        model_view_schema_version=4,
    )

    question = model_view["questions"][0]
    assert "prior_relevant_statement_refs" not in question
    assert "prior_coverage" not in question
    assert metadata["prior_coverage_question_count"] == 0


def test_ledger_v4_rejects_quoted_and_generic_role_attribution() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(850, speaker_ref="seat_8", speech="按5号原话，我是预言家。"),
            _statement(851, speaker_ref="seat_8", speech="引用5号：我是预言家。"),
            _statement(852, speaker_ref="seat_8", speech="5号的原话是“我是预言家”。"),
            _statement(853, speaker_ref="seat_8", speech="复述5号：我是预言家。"),
            _statement(854, speaker_ref="seat_8", speech="有人说我是预言家。"),
            _statement(855, speaker_ref="seat_8", speech="他说我是预言家。"),
            _statement(856, speaker_ref="seat_8", speech="别人认为我是预言家。"),
            _statement(
                857,
                speaker_ref="seat_8",
                speech="我是预言家。昨晚别人验了1号是查杀，我不认。",
            ),
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    for source_id in {str(value) for value in range(850, 857)}:
        assert all(
            claim["claim_type"] != "role_claim"
            for claim in ledger["claims"]
            if claim["source_event_id"] == source_id
        )
    assert all(
        claim["claim_type"] != "investigation_claim"
        for claim in ledger["claims"]
        if claim["source_event_id"] == "857"
    )
    for source_id in ("850", "851", "852", "853"):
        assert any(
            claim["claim_type"] == "secondary_paraphrase"
            for claim in ledger["claims"]
            if claim["source_event_id"] == source_id
        )


def test_ledger_v4_does_not_confuse_vote_target_with_question_addressee() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(860, speaker_ref="seat_8", speech="我票给5号，为什么他这么狼？"),
            _statement(861, speaker_ref="seat_8", speech="我给5号投票，理由是什么？"),
            _statement(862, speaker_ref="seat_8", speech="给5号一个问题：你昨晚验谁？"),
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert [question["addressed_to"] for question in ledger["questions"]] == [
        None,
        None,
        "seat_5",
    ]
    assert [question["address_resolution"] for question in ledger["questions"]] == [
        "unresolved",
        "unresolved",
        "resolved",
    ]


def test_ledger_v4_limits_investigation_result_to_target_clause() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                870,
                speaker_ref="seat_5",
                speech="我是预言家。昨晚验1号金水，2号更像狼人。",
            ),
            _statement(
                871,
                speaker_ref="seat_5",
                speech="我是预言家。我昨晚验1号金水，但他发言像狼人。",
            ),
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    investigations = [
        claim for claim in ledger["claims"] if claim["claim_type"] == "investigation_claim"
    ]
    assert [claim["target_ref"] for claim in investigations] == ["seat_1", "seat_1"]
    assert [claim["claimed_result"] for claim in investigations] == [
        "villagers",
        "villagers",
    ]


def test_model_view_prior_coverage_matches_requested_fields_and_night() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                880,
                speaker_ref="seat_5",
                round_no=1,
                speech="我是预言家，首夜验1号金水。",
            ),
            _statement(
                881,
                speaker_ref="seat_5",
                round_no=2,
                speech="我是预言家，昨晚验2号查杀。",
            ),
            _statement(
                882,
                speaker_ref="seat_8",
                round_no=2,
                speech="5号你首夜验了谁、什么结果？",
            ),
            _statement(
                883,
                speaker_ref="seat_8",
                round_no=2,
                speech="5号你昨晚验了谁、什么结果？",
            ),
        ],
        current_round_no=2,
        ledger_schema_version=4,
    )

    model_view, _ = build_discourse_model_view(
        ledger,
        actor_ref="seat_8",
        task={"action_type": "day_debate_speech"},
        candidate_refs=[],
        latest_vote_result_ref=None,
        model_view_schema_version=4,
    )

    first_night, second_night = model_view["questions"]
    assert first_night["requested_fields"] == ["target_ref", "claimed_result"]
    assert first_night["referenced_night_no"] == 1
    assert first_night["prior_relevant_statement_refs"] == ["880"]
    assert first_night["prior_coverage"] == "already_publicly_reported"
    assert second_night["referenced_night_no"] == 2
    assert second_night["prior_relevant_statement_refs"] == ["881"]
    assert second_night["prior_coverage"] == "already_publicly_reported"


def test_model_view_prior_coverage_does_not_overstate_partial_report() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                890,
                speaker_ref="seat_5",
                speech="我是预言家，首夜验了1号。",
            ),
            _statement(
                891,
                speaker_ref="seat_8",
                speech="5号你首夜验人结果是什么？",
            ),
            _statement(
                892,
                speaker_ref="seat_8",
                speech="5号你首夜验了谁？",
            ),
            _statement(
                893,
                speaker_ref="seat_8",
                speech="5号你首夜验了谁、什么结果？",
            ),
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    model_view, _ = build_discourse_model_view(
        ledger,
        actor_ref="seat_8",
        task={"action_type": "day_debate_speech"},
        candidate_refs=[],
        latest_vote_result_ref=None,
        model_view_schema_version=4,
    )

    result_question, target_question, both_question = model_view["questions"]
    assert result_question["requested_fields"] == ["claimed_result"]
    assert "prior_coverage" not in result_question
    assert target_question["requested_fields"] == ["target_ref"]
    assert target_question["prior_coverage"] == "already_publicly_reported"
    assert both_question["requested_fields"] == ["target_ref", "claimed_result"]
    assert "prior_coverage" not in both_question


def test_ledger_v4_answer_requires_all_requested_fields_and_matching_night() -> None:
    question = _statement(
        900,
        speaker_ref="seat_8",
        round_no=2,
        speech="5号你首夜验了谁、什么结果？",
    )
    responses = {
        "target_only": "我首夜验了1号。",
        "result_only": "我首夜验人结果是金水。",
        "wrong_night": "我昨晚验了1号金水。",
        "complete": "我首夜验了1号金水。",
    }

    statuses: dict[str, str] = {}
    for index, (case, speech) in enumerate(responses.items(), start=901):
        ledger = build_public_discourse_ledger(
            [
                question,
                _statement(
                    index,
                    speaker_ref="seat_5",
                    round_no=2,
                    speech=speech,
                ),
            ],
            current_round_no=2,
            ledger_schema_version=4,
        )
        statuses[case] = ledger["questions"][0]["status"]
        if case == "complete":
            assert len(ledger["relations"]) == 1
        else:
            assert ledger["relations"] == []

    assert statuses == {
        "target_only": "open",
        "result_only": "open",
        "wrong_night": "open",
        "complete": "answered",
    }


def test_ledger_v4_does_not_turn_report_wording_into_an_implicit_question() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(910, speaker_ref="seat_8", speech="5号昨晚验了谁都没说。"),
            _statement(911, speaker_ref="seat_8", speech="5号昨晚验了谁没有公布。"),
            _statement(912, speaker_ref="seat_8", speech="5号昨晚验谁不重要。"),
            _statement(913, speaker_ref="seat_8", speech="5号昨晚验了谁我不知道。"),
        ],
        current_round_no=1,
        ledger_schema_version=4,
    )

    assert ledger["questions"] == []


def test_ledger_v4_treats_first_investigation_as_night_one_in_claim_and_answer() -> None:
    statements = [
        _statement(
            920,
            speaker_ref="seat_8",
            round_no=2,
            speech="5号你的首验是谁、什么结果？",
        ),
        _statement(
            921,
            speaker_ref="seat_5",
            round_no=2,
            speech="我的首验是1号金水。",
        ),
    ]
    ledger = build_public_discourse_ledger(
        statements,
        current_round_no=2,
        ledger_schema_version=4,
    )

    question = ledger["questions"][0]
    assert question["topic"] == "past_investigation_result"
    assert question["referenced_night_no"] == 1
    assert question["requested_fields"] == ["target_ref", "claimed_result"]
    assert question["status"] == "answered"
    investigation = next(
        claim for claim in ledger["claims"] if claim["claim_type"] == "investigation_claim"
    )
    assert investigation["speaker_ref"] == "seat_5"
    assert investigation["claimed_action_in"] == {"period": "night", "round_no": 1}
    assert investigation["target_ref"] == "seat_1"
    assert investigation["claimed_result"] == "villagers"
    assert len(ledger["relations"]) == 1

    frozen_v3 = build_public_discourse_ledger(
        statements,
        current_round_no=2,
        ledger_schema_version=3,
    )
    assert all(
        claim["claim_type"] != "investigation_claim" for claim in frozen_v3["claims"]
    )
    assert "referenced_night_no" not in frozen_v3["questions"][0]


def test_ledger_v4_treats_plain_first_investigation_as_direct_but_not_attribution() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                930,
                speaker_ref="seat_8",
                round_no=2,
                speech="首验1号金水。",
            ),
            _statement(
                931,
                speaker_ref="seat_8",
                round_no=2,
                speech="5号首验1号金水。",
            ),
            _statement(
                932,
                speaker_ref="seat_8",
                round_no=2,
                speech="按5号原话，首验1号金水。",
            ),
        ],
        current_round_no=2,
        ledger_schema_version=4,
    )

    investigations = [
        claim for claim in ledger["claims"] if claim["claim_type"] == "investigation_claim"
    ]
    assert len(investigations) == 1
    assert investigations[0]["source_event_id"] == "930"
    assert investigations[0]["speaker_ref"] == "seat_8"
    assert investigations[0]["claimed_action_in"] == {"period": "night", "round_no": 1}
    assert investigations[0]["target_ref"] == "seat_1"
    assert investigations[0]["claimed_result"] == "villagers"
    assert any(
        claim["source_event_id"] == "932"
        and claim["claim_type"] == "secondary_paraphrase"
        and claim["reported_speaker_ref"] == "seat_5"
        for claim in ledger["claims"]
    )

    frozen_v3 = build_public_discourse_ledger(
        [_statement(930, speaker_ref="seat_8", round_no=2, speech="首验1号金水。")],
        current_round_no=2,
        ledger_schema_version=3,
    )
    assert all(
        claim["claim_type"] != "investigation_claim" for claim in frozen_v3["claims"]
    )


def test_ledger_v2_preserves_frozen_vote_question_projection() -> None:
    ledger = build_public_discourse_ledger(
        _game_vote_reason_statements(),
        current_round_no=1,
        ledger_schema_version=2,
    )

    questions = {question["source_event_id"]: question for question in ledger["questions"]}
    assert questions["1248"]["addressed_to"] == "seat_1"
    assert questions["1248"]["topic"] == "investigation_reason"
    assert questions["1248"]["answer_source_event_id"] == "1270"


def test_discourse_model_view_treats_day_debate_as_public_speech() -> None:
    ledger = build_public_discourse_ledger(
        [
            _statement(
                450,
                speaker_ref="seat_6",
                stage="day_debate_speech",
                speech="6号今天先听大家发言。",
            )
        ],
        current_round_no=1,
        actor_ref="seat_8",
    )

    model_view, _ = build_discourse_model_view(
        ledger,
        actor_ref="seat_8",
        task={"action_type": "day_debate_speech"},
        candidate_refs=[],
        latest_vote_result_ref=None,
    )

    assert model_view["focus"]["profile"] == "public_speech"


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
