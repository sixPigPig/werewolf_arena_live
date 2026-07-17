import pytest

from app.werewolf.checkpoint import game_state_from_dict
from app.werewolf.public_facts import (
    PublicFact,
    compressed_public_fact_records,
    compressed_public_facts,
    fact_prompt_coverage,
    public_fact_dicts_from_value,
    public_fact_from_dict,
)


def test_compressed_public_facts_keeps_key_claims_and_recent_events() -> None:
    facts = [
        PublicFact(round_number=1, category="claim", text="7号玩家警上自称预言家，报3号玩家为好人。"),
        PublicFact(round_number=2, category="claim", text="7号玩家警上声明6号玩家为好人。"),
        PublicFact(round_number=3, category="death", text="7号玩家夜晚出局，将警徽交给3号玩家。"),
        PublicFact(round_number=4, category="vote", text="第4轮票型：1号玩家->6号玩家；6号玩家->1号玩家。"),
    ]

    lines = compressed_public_facts(facts, max_lines=3)

    assert "7号玩家警上声明6号玩家为好人。" in lines
    assert "第4轮票型" in "\n".join(lines)
    assert len(lines) == 3


def test_public_fact_v1_payload_loads_with_compatible_defaults() -> None:
    fact = public_fact_from_dict(
        {
            "round_number": 1,
            "category": "claim",
            "text": "5号玩家警长PK发言中自称预言家。",
        }
    )

    assert fact.schema_version == 1
    assert fact.fact_id == ""
    assert fact.stage is None
    assert fact.actor is None
    assert fact.effective_retention == "important"
    assert fact.effective_trust_class == "legacy_unclassified"


def test_new_public_facts_classify_claims_separately_from_engine_facts() -> None:
    claim = PublicFact(round_number=1, category="claim", text="5号自称预言家。")
    death = PublicFact(round_number=1, category="death", text="5号被放逐。")

    assert claim.effective_trust_class == "player_claim"
    assert death.effective_trust_class == "engine_fact"
    assert claim.to_dict()["trust_class"] == "player_claim"
    assert death.to_dict()["trust_class"] == "engine_fact"


def test_public_fact_explicit_trust_class_round_trips() -> None:
    fact = public_fact_from_dict(
        {
            "round_number": 2,
            "category": "claim",
            "trust_class": "player_claim",
            "text": "8号声称自己是猎人。",
            "source_event_id": "event-42",
        }
    )

    assert fact.effective_trust_class == "player_claim"
    assert fact.source_event_id == "event-42"
    assert fact.to_dict()["trust_class"] == "player_claim"
    assert fact.to_dict()["source_event_id"] == "event-42"


def test_compressed_public_fact_records_preserve_semantic_metadata() -> None:
    records = compressed_public_fact_records(
        [
            PublicFact(
                round_number=3,
                category="death",
                text="第3轮，5号玩家被放逐。",
                fact_id="fact-5-exiled",
                stage="vote_exile",
                actor="5号玩家",
                source_opportunity_id="opportunity-5-exiled",
                source_event_id="event-5-exiled",
            ),
            PublicFact(
                round_number=3,
                category="claim",
                text="5号遗言声称8号是狼人。",
                fact_id="fact-5-claim",
            ),
        ]
    )

    assert records == [
        {
            "round_number": 3,
            "category": "death",
            "trust_class": "engine_fact",
            "text": "第3轮，5号玩家被放逐。",
            "fact_id": "fact-5-exiled",
            "stage": "vote_exile",
            "actor": "5号玩家",
            "source_opportunity_id": "opportunity-5-exiled",
            "source_event_id": "event-5-exiled",
        },
        {
            "round_number": 3,
            "category": "claim",
            "trust_class": "player_claim",
            "text": "5号遗言声称8号是狼人。",
            "fact_id": "fact-5-claim",
            "stage": None,
            "actor": None,
            "source_opportunity_id": None,
            "source_event_id": None,
        },
    ]


def test_fact_prompt_coverage_accepts_structured_records() -> None:
    fact = PublicFact(
        round_number=1,
        category="vote",
        text="第1轮票型已经公开。",
        fact_id="fact-vote-1",
        retention="critical",
    )

    coverage = fact_prompt_coverage(
        [fact],
        compressed_public_fact_records([fact]),
    )

    assert coverage["included_critical_count"] == 1
    assert coverage["missing_critical_count"] == 0


@pytest.mark.parametrize("category", ["private_observation", "strategy_note"])
def test_private_channels_cannot_be_constructed_as_public_facts(category: str) -> None:
    with pytest.raises(ValueError, match="private category"):
        PublicFact(round_number=1, category=category, text="不应进入公开事实。")


@pytest.mark.parametrize(
    "unsafe_fact",
    [
        {
            "round_number": 1,
            "category": "private_observation",
            "trust_class": "engine_fact",
            "text": "SENTINEL_PRIVATE_OBSERVATION",
        },
        {
            "round_number": 1,
            "category": "future_private_category",
            "trust_class": "engine_fact",
            "text": "SENTINEL_UNKNOWN_CATEGORY",
        },
        {
            "round_number": 1,
            "category": "claim",
            "trust_class": "future_trust_class",
            "text": "SENTINEL_UNKNOWN_TRUST",
        },
        {
            "round_number": 1,
            "category": "claim",
            "trust_class": "player_claim",
            "text": "SENTINEL_PRIVATE_DETAILS",
            "details": {"source": {"reasoning": "private chain of thought"}},
        },
        {
            "round_number": 1,
            "category": ["claim"],
            "trust_class": "player_claim",
            "text": "SENTINEL_NON_STRING_CATEGORY",
        },
    ],
)
def test_unsafe_stored_public_fact_fails_closed_without_raising(
    unsafe_fact: dict[str, object],
) -> None:
    restored = public_fact_from_dict(unsafe_fact)

    assert restored.text == ""
    assert public_fact_dicts_from_value([unsafe_fact]) == []


def test_public_projection_strips_unknown_details_but_keeps_public_text() -> None:
    stored = {
        "round_number": 1,
        "category": "event",
        "trust_class": "legacy_unclassified",
        "text": "已经公开的历史记录。",
        "details": {"secret": "SENTINEL_UNKNOWN_PRIVATE_FIELD"},
    }

    assert public_fact_from_dict(stored).details == stored["details"]
    projected = public_fact_dicts_from_value([stored])
    assert projected[0]["text"] == stored["text"]
    assert projected[0]["details"] == {}
    assert "SENTINEL" not in str(projected)


def test_legacy_public_fact_string_remains_unclassified() -> None:
    projected = public_fact_dicts_from_value(["历史公开记录。"])

    assert projected[0]["category"] == "event"
    assert projected[0]["trust_class"] == "legacy_unclassified"
    assert projected[0]["text"] == "历史公开记录。"


def test_checkpoint_restore_drops_unsafe_public_facts() -> None:
    state = game_state_from_dict(
        {
            "session_id": "session-public-facts",
            "players": [],
            "public_facts": [
                {
                    "round_number": 1,
                    "category": "claim",
                    "trust_class": "player_claim",
                    "text": "5号玩家声称自己是预言家。",
                },
                {
                    "round_number": 1,
                    "category": "strategy_note",
                    "trust_class": "player_claim",
                    "text": "SENTINEL_PRIVATE_STRATEGY",
                },
                {
                    "round_number": 1,
                    "category": "future_category",
                    "trust_class": "engine_fact",
                    "text": "SENTINEL_UNKNOWN_CATEGORY",
                },
            ],
        }
    )

    assert [fact["text"] for fact in state.public_facts] == [
        "5号玩家声称自己是预言家。"
    ]
    assert "SENTINEL" not in str(state.to_dict())


def test_player_claim_cannot_be_upgraded_to_engine_fact() -> None:
    fact = public_fact_from_dict(
        {
            "round_number": 1,
            "category": "claim",
            "trust_class": "engine_fact",
            "text": "5号玩家声称自己是预言家。",
        }
    )

    assert fact.effective_trust_class == "player_claim"
    assert fact.to_dict()["trust_class"] == "player_claim"


def test_critical_fact_is_not_displaced_by_recent_speech() -> None:
    critical_text = "第1轮警长PK发言：5号玩家自称预言家，报6号玩家为好人。"
    facts = [
        PublicFact(
            round_number=1,
            category="claim",
            text=critical_text,
            fact_id="r1:sheriff_pk_speech:5:0",
            stage="sheriff_pk_speech",
            actor="5号玩家",
            retention="critical",
        ),
        *[
            PublicFact(
                round_number=4,
                category="speech",
                text=f"近期普通发言 {index}",
                fact_id=f"r4:debate:{index}",
                retention="recent",
            )
            for index in range(20)
        ],
    ]

    lines = compressed_public_facts(facts, max_lines=3)

    assert critical_text in lines
    assert lines[-2:] == ["近期普通发言 18", "近期普通发言 19"]


def test_public_fact_details_reject_private_keys_recursively() -> None:
    with pytest.raises(ValueError, match="private key: reasoning"):
        PublicFact(
            round_number=1,
            category="claim",
            text="公开发言",
            details={"source": {"reasoning": "私密推理"}},
        )


@pytest.mark.parametrize("private_key", ["model_memory", "strategy_note"])
def test_public_fact_details_reject_all_private_prompt_channels(
    private_key: str,
) -> None:
    with pytest.raises(ValueError, match=f"private key: {private_key}"):
        PublicFact(
            round_number=1,
            category="claim",
            text="公开发言",
            details={private_key: "不应公开"},
        )
