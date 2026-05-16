from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlayerPreset:
    id: str
    label: str
    description: str


PERSONALITY_PRESETS: dict[str, PlayerPreset] = {
    "balanced": PlayerPreset(id="balanced", label="均衡", description="稳健、根据证据推进，不轻易极端站边。"),
    "aggressive": PlayerPreset(id="aggressive", label="进攻", description="进攻性强，主动施压、抓矛盾、推动投票。"),
    "cautious": PlayerPreset(id="cautious", label="谨慎", description="谨慎保守，优先收集信息，避免过早暴露关键判断。"),
    "deceptive": PlayerPreset(id="deceptive", label="欺骗", description="善于混淆视听，适合狼人策略，但不改变阵营目标。"),
    "analytical": PlayerPreset(id="analytical", label="分析", description="重视票型、发言顺序和行为一致性。"),
}

APPEARANCE_PRESETS: dict[str, PlayerPreset] = {
    "default": PlayerPreset(id="default", label="默认", description="当前按名字生成头像的兼容样式。"),
    "crimson": PlayerPreset(id="crimson", label="绯红", description="深红阵营感形象。"),
    "moonlit": PlayerPreset(id="moonlit", label="冷月", description="冷月银蓝形象。"),
    "ember": PlayerPreset(id="ember", label="余烬", description="琥珀火光形象。"),
    "verdant": PlayerPreset(id="verdant", label="幽林", description="暗绿色森林形象。"),
}


def default_personality_text(personality_id: str) -> str:
    return PERSONALITY_PRESETS[personality_id].description


def is_valid_personality(personality_id: str) -> bool:
    return personality_id in PERSONALITY_PRESETS


def is_valid_appearance(appearance_id: str) -> bool:
    return appearance_id in APPEARANCE_PRESETS
