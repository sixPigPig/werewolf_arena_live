from __future__ import annotations

from app.werewolf.speech_delivery import (
    DELIVERY_MAPPING_VERSION,
    compile_context_texts,
    delivery_from_result,
    normalize_delivery,
)


def test_delivery_rejects_game_facts_but_keeps_valid_speech_style() -> None:
    delivery = delivery_from_result(
        {
            "say": "我先听完后置位再改判断。",
            "delivery": {
                "mood": "skeptical",
                "intensity": "high",
                "pace": "fast",
                "instruction": "质疑5号玩家是狼人，并强调昨夜刀口",
            },
        },
        base_instruction="克制、自然地表达",
    )

    assert delivery == {
        "schema_version": 1,
        "mood": "skeptical",
        "intensity": "high",
        "pace": "fast",
        "instruction": "克制、自然",
    }
    contexts = compile_context_texts(delivery)
    assert len(contexts) == 1
    assert "质疑" in contexts[0]
    assert "5号" not in contexts[0]
    assert "是狼人" not in contexts[0]
    assert "刀口" not in contexts[0]


def test_missing_or_invalid_delivery_uses_frozen_base_style() -> None:
    delivery = normalize_delivery(
        {
            "mood": "not-a-mood",
            "intensity": "not-an-intensity",
            "pace": "not-a-pace",
            "instruction": "",
        },
        base_mood="calm",
        base_intensity="low",
        base_pace="slow",
        base_instruction="低沉、停顿",
    )

    assert delivery == {
        "schema_version": 1,
        "mood": "calm",
        "intensity": "low",
        "pace": "slow",
        "instruction": "低沉、停顿",
    }
    assert DELIVERY_MAPPING_VERSION == "delivery-v1"


def test_free_text_instruction_is_compiled_to_allowlisted_cues_only() -> None:
    delivery = normalize_delivery(
        {
            "instruction": "请自然一点，先短句停顿，再坚定反问，不要像播音员。",
        }
    )

    assert delivery["instruction"] == "坚定、自然、停顿、反问、短句"
    context = compile_context_texts(delivery)[0]
    assert "请自然一点" not in context
    assert "播音员" not in context
    assert "坚定、自然、停顿、反问、短句" in context


def test_compile_context_texts_adds_only_supported_chinese_dialect() -> None:
    sichuan = compile_context_texts({}, dialect="sichuan")[0]
    unknown = compile_context_texts({}, dialect="cantonese")[0]

    assert "四川话" in sichuan
    assert "cantonese" not in unknown
    assert "方言" not in unknown
