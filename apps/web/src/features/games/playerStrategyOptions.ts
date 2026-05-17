export const STRATEGY_OPTIONS = [
  { id: "balanced", label: "均衡观察", description: "稳健观察，按证据推进。" },
  { id: "logic_leader", label: "逻辑带队", description: "主动整理票型和矛盾链。" },
  { id: "shadow_wolf", label: "阴影潜伏", description: "低调隐藏动机，避免过早成为焦点。" },
  { id: "social_reader", label: "社交阅读", description: "重视情绪变化、关系线和姿态。" },
  { id: "pressure_attacker", label: "强压进攻", description: "用快速提问和压力制造信息。" },
  { id: "cautious_observer", label: "谨慎观察", description: "先收集信息，再明确判断。" },
] as const;

export const TENDENCY_LABELS = {
  risk_tolerance: "冒险倾向",
  bluffing_tendency: "伪装倾向",
  trust_tendency: "信任倾向",
  leadership_tendency: "领导倾向",
  talkativeness: "发言活跃",
} as const;

export type StrategyProfileId = (typeof STRATEGY_OPTIONS)[number]["id"];
export type TendencyField = keyof typeof TENDENCY_LABELS;
