from app.werewolf.public_facts import PublicFact, compressed_public_facts


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
