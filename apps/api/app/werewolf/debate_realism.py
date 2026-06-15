from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.werewolf.player_configs import PlayerConfig, player_config_from_dict

PUNCTUATION_RE = re.compile(r"[\s，。！？、；：,.!?;:\"'《》（）()【】\[\]{}<>-]+")
CATCHPHRASE_LINE_RE = re.compile(r"^常用表达:\s*(.+)$", re.MULTILINE)
CATCHPHRASE_SPLIT_RE = re.compile(r"[；;、,，\n]+")
LOW_NOVELTY_THRESHOLD = 0.45


def normalize_dialogue_text(text: str) -> str:
    return PUNCTUATION_RE.sub("", text.strip())


def catchphrases_from_personality(personality: str) -> list[str]:
    match = CATCHPHRASE_LINE_RE.search(personality or "")
    if not match:
        return []
    phrases: list[str] = []
    seen: set[str] = set()
    for item in CATCHPHRASE_SPLIT_RE.split(match.group(1)):
        phrase = item.strip()
        if not phrase or phrase in seen:
            continue
        phrases.append(phrase)
        seen.add(phrase)
    return phrases


def repeated_phrase_candidates(
    texts: list[str],
    *,
    min_chars: int = 4,
    min_count: int = 2,
    limit: int = 8,
) -> list[str]:
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for text in texts:
        normalized = normalize_dialogue_text(text)
        seen_for_text: set[str] = set()
        max_chars = min(8, len(normalized))
        for size in range(min_chars, max_chars + 1):
            for index in range(0, len(normalized) - size + 1):
                phrase = normalized[index : index + size]
                if _is_weak_phrase(phrase):
                    continue
                seen_for_text.add(phrase)
                first_seen.setdefault(phrase, len(first_seen))
        counts.update(seen_for_text)

    phrases: list[str] = []
    ranked = sorted(counts.items(), key=lambda item: (-item[1], len(item[0]), first_seen[item[0]]))
    for phrase, count in ranked:
        if count < min_count:
            continue
        if any(phrase in existing or existing in phrase for existing in phrases):
            continue
        phrases.append(phrase)
        if len(phrases) >= limit:
            break
    return phrases


def dialogue_quality_warnings(
    *,
    text: str,
    prior_texts: list[str] | tuple[str, ...] = (),
    personality: str = "",
) -> list[str]:
    warnings: list[str] = []
    normalized = normalize_dialogue_text(text)
    normalized_catchphrases: list[str] = []
    for phrase in catchphrases_from_personality(personality):
        normalized_phrase = normalize_dialogue_text(phrase)
        if normalized_phrase:
            normalized_catchphrases.append(normalized_phrase)
    if any(phrase in normalized for phrase in normalized_catchphrases):
        warnings.append("catchphrase_overuse")

    prior = [str(item) for item in prior_texts if str(item).strip()]
    if prior:
        repeated = repeated_phrase_candidates([*prior, text], min_chars=4, min_count=2)
        if any(phrase in normalized for phrase in repeated):
            warnings.append("repeated_debate_phrase")
        overlap = _fourgram_overlap_ratio(normalized, prior)
        if overlap >= LOW_NOVELTY_THRESHOLD:
            warnings.append("low_novelty_debate")

    return warnings


def debate_guidance_for_turn(
    *,
    speaker: str,
    active_players: list[str],
    prior_messages: list[str],
    personality: str,
) -> list[str]:
    total = max(1, len(active_players))
    if speaker in active_players:
        position = active_players.index(speaker) + 1
    else:
        position = min(total, len(prior_messages) + 1)
    lines = [f"你是本轮第 {position}/{total} 位发言。"]
    if position == 1:
        lines.append("开一个新信息点：优先提出夜死、票型、身份声明或发言顺序中的一个可验证疑点。")
    elif position == total:
        lines.append("你是末置位：必须收束分歧，明确票口，并点名回应至少一名玩家。")
    elif position >= max(1, total - 1):
        lines.append("你是后置位：不要复述前置位结论，补一个反证、追问或票型解释。")
    else:
        lines.append("你是中置位：选择一个前置位观点进行赞同或反驳，并给出新的理由。")

    forbidden = repeated_phrase_candidates(prior_messages, min_chars=4, min_count=2, limit=5)
    catchphrases = catchphrases_from_personality(personality)
    avoid = list(dict.fromkeys([*forbidden, *catchphrases]))[:6]
    if avoid:
        lines.append(f"避免复用这些已出现或个人口癖表达：{'、'.join(avoid)}。")
    lines.append("发言必须新增一个未被前置位完整说过的事实、反问或投票解释。")
    return lines


def lineup_quality_warnings(configs: list[PlayerConfig]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    personality_counts = Counter(config.personality_id for config in configs if config.personality_id)
    catchphrase_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    for config in configs:
        catchphrase_counts.update(catchphrases_from_personality(config.personality))
        tag_counts.update(config.tags)

    for personality_id, count in personality_counts.most_common(1):
        if count >= 4:
            warnings.append(
                {
                    "code": "homogeneous_personality_lineup",
                    "detail": f"{count} players share personality_id {personality_id}.",
                }
            )
    for phrase, count in catchphrase_counts.most_common(1):
        if count >= 4:
            warnings.append(
                {
                    "code": "shared_catchphrase_lineup",
                    "detail": f"{count} players share catchphrase {phrase}.",
                }
            )
    for tag, count in tag_counts.most_common(1):
        if count >= 4:
            warnings.append(
                {
                    "code": "shared_tag_lineup",
                    "detail": f"{count} players share tag {tag}.",
                }
            )
    return warnings


def lineup_quality_warnings_from_players(players: list[dict[str, Any]]) -> list[dict[str, str]]:
    configs: list[PlayerConfig] = []
    for index, player in enumerate(players, start=1):
        if not isinstance(player, dict):
            continue
        data = dict(player)
        if data.get("seat") is None:
            data["seat"] = index
        configs.append(player_config_from_dict(data))
    return lineup_quality_warnings(configs)


def _fourgram_overlap_ratio(text: str, prior_texts: list[str]) -> float:
    own = _ngrams(text, 4)
    if len(own) < 8:
        return 0.0
    prior: set[str] = set()
    for prior_text in prior_texts:
        prior.update(_ngrams(normalize_dialogue_text(prior_text), 4))
    if not prior:
        return 0.0
    return len(own & prior) / len(own)


def _ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return set()
    return {text[index : index + size] for index in range(0, len(text) - size + 1)}


def _is_weak_phrase(phrase: str) -> bool:
    return len(set(phrase)) <= 1 or phrase.isdigit()
