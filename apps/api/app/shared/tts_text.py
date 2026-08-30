from __future__ import annotations

import re

USED_STATIC_JUDGE_VOICE_ASSET_IDS = frozenset(
    {
        "badge_destroyed",
        "badge_owner_out",
        "dawn_peaceful",
        "dawn_start",
        "exile_vote_start",
        "exile_tie",
        "exile_pk_start",
        "exile_runoff_vote",
        "exile_runoff_tied",
        "exile_no_votes",
        "exile_no_result",
        "exile_no_runoff_voters",
        "game_intro",
        "game_resume",
        "game_over_third_party",
        "game_over_villagers",
        "game_over_wolves",
        "guard_choose",
        "guard_sleep",
        "guard_wake",
        "night_start",
        "seer_choose",
        "seer_sleep",
        "seer_wake",
        "sheriff_choose_badge_side",
        "sheriff_no_badge",
        "sheriff_raise_hands",
        "sheriff_vote",
        "sheriff_tie",
        "self_explosion_skip",
        "hunter_shot_choose",
        "hunter_shot_skipped",
        "hunter_shot_start",
        "idiot_stays",
        "werewolves_choose",
        "werewolves_sleep",
        "werewolves_wake",
        "witch_poison",
        "witch_save",
        "witch_sleep",
        "witch_wake",
    }
)
USED_STATIC_JUDGE_VOICE_ASSET_TEMPLATE_IDS = frozenset(
    {
        "badge_transfer",
        "exile_last_words",
        "exile_result",
        "hunter_shot_result",
        "idiot_reveal",
        "sheriff_result",
        "speech_prompt",
        "werewolf_self_explosion",
        "witch_death",
    }
)
SENTENCE_PATTERN = re.compile(r"[^，。！？；,.!?;]+[，。！？；,.!?;]?")


def is_static_judge_voice_asset_used(
    asset_id: str,
    *,
    template_id: str | None = None,
) -> bool:
    """Return whether live game narration can request this static asset."""
    return (
        asset_id in USED_STATIC_JUDGE_VOICE_ASSET_IDS
        or template_id in USED_STATIC_JUDGE_VOICE_ASSET_TEMPLATE_IDS
    )


def chunk_text_for_tts(text: str, *, max_chars: int = 24) -> list[str]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")

    normalized = " ".join(text.split()).strip()
    if not normalized:
        return []

    chunks: list[str] = []
    for phrase in SENTENCE_PATTERN.findall(normalized) or [normalized]:
        phrase = phrase.strip()
        if not phrase:
            continue
        if len(phrase) <= max_chars:
            chunks.append(phrase)
            continue
        for start in range(0, len(phrase), max_chars):
            chunks.append(phrase[start : start + max_chars])
    return chunks
