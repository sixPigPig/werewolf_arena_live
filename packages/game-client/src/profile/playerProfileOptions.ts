export const PERSONALITY_OPTIONS = [
  { id: "balanced", label: "均衡" },
  { id: "aggressive", label: "进攻" },
  { id: "cautious", label: "谨慎" },
  { id: "deceptive", label: "欺骗" },
  { id: "analytical", label: "分析" },
] as const;

export const APPEARANCE_OPTIONS = [
  { id: "default", label: "默认", className: "profile-appearance-default" },
  { id: "crimson", label: "绯红", className: "profile-appearance-crimson" },
  { id: "moonlit", label: "冷月", className: "profile-appearance-moonlit" },
  { id: "ember", label: "余烬", className: "profile-appearance-ember" },
  { id: "verdant", label: "幽林", className: "profile-appearance-verdant" },
] as const;

const DEFAULT_PERSONALITY = PERSONALITY_OPTIONS[0];
const DEFAULT_APPEARANCE = APPEARANCE_OPTIONS[0];

export function personalityLabel(id?: string) {
  return (
    PERSONALITY_OPTIONS.find((option) => option.id === id)?.label ??
    DEFAULT_PERSONALITY.label
  );
}

export function appearanceLabel(id?: string) {
  return (
    APPEARANCE_OPTIONS.find((option) => option.id === id)?.label ??
    DEFAULT_APPEARANCE.label
  );
}

export function appearanceClassName(id?: string) {
  return (
    APPEARANCE_OPTIONS.find((option) => option.id === id)?.className ??
    DEFAULT_APPEARANCE.className
  );
}
