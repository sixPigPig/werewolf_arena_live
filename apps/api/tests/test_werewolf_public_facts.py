import pytest

from app.werewolf.public_facts import (
    PublicFact,
    compressed_public_facts,
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
