import type {
  GameSessionStatus,
  LiveRunStatus,
} from "@/features/game-records/types";

export const GAME_STATUS_LABELS: Record<GameSessionStatus, string> = {
  complete: "已完成",
  partial: "部分记录",
};

export const RUN_STATUS_LABELS: Record<LiveRunStatus, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  canceled: "已取消",
};

const PERSONALITY_LABELS: Record<string, string> = {
  balanced: "均衡",
  aggressive: "进攻",
  cautious: "谨慎",
  deceptive: "迷惑",
  analytical: "分析",
};

const EVENT_TYPE_LABELS: Record<string, string> = {
  run_created: "运行已创建",
  run_started: "运行开始",
  game_started: "对局开始",
  round_started: "轮次开始",
  phase_started: "阶段开始",
  action_requested: "请求玩家动作",
  model_request_started: "模型请求开始",
  model_thinking_tick: "模型思考中",
  model_response_delta: "模型响应片段",
  model_response_received: "模型响应完成",
  model_request_failed: "模型请求失败",
  model_retry_scheduled: "已安排模型重试",
  action_parsed: "动作解析完成",
  action_quality_warning: "动作质量告警",
  judge_cue: "法官播报",
  state_updated: "对局状态更新",
  game_completed: "对局完成",
  game_failed: "对局失败",
  game_resumed: "对局已恢复",
};

const PHASE_LABELS: Record<string, string> = {
  night: "夜晚",
  day: "白天",
  vote: "投票",
  summary: "总结",
};

const ACTION_LABELS: Record<string, string> = {
  debate: "白天发言",
  summarize: "轮次总结",
  sheriff_speech: "警长竞选发言",
  sheriff_run: "上警",
  vote: "放逐投票",
  sheriff_pk_speech: "警长平票发言",
  sheriff_withdraw: "退水",
  sheriff_vote: "警长投票",
  witch_poison: "女巫使用毒药",
  werewolf_kill_vote: "狼人刀人投票",
  sheriff_runoff_vote: "警长加赛投票",
  investigate: "预言家查验",
  speech_order: "选择发言顺序",
  witch_save: "女巫使用解药",
  remove: "玩家出局",
  sheriff_badge: "处理警徽",
  hunter_shoot: "猎人开枪",
  night_resolved: "夜间结算",
  werewolves_sleep: "狼人闭眼",
  werewolves_wake: "狼人睁眼",
  witch_death: "女巫确认死亡信息",
  witch_sleep: "女巫闭眼",
  witch_wake: "女巫睁眼",
  dawn_deaths: "公布昨夜死亡",
  werewolf_self_explosion: "狼人自爆",
  seer_sleep: "预言家闭眼",
  seer_wake: "预言家睁眼",
  day_resolution_completed: "白天结算完成",
  public_round_brief: "公布轮次摘要",
  badge_owner_out: "警长出局",
  badge_transfer: "移交警徽",
  exile_resolved: "放逐结算完成",
  exile_result: "公布放逐结果",
  self_explosion_skip: "自爆后跳过流程",
  sheriff_badge_resolved: "警徽处理完成",
  sheriff_election_resolved: "警长竞选结算完成",
  sheriff_raise_hands: "公布上警名单",
  dawn_peaceful: "公布平安夜",
  hunter_shot_choose: "猎人选择开枪目标",
  hunter_shot_resolved: "猎人开枪结算完成",
  hunter_shot_result: "公布猎人开枪结果",
  hunter_shot_start: "猎人技能开始",
  sheriff_election_postponed: "警长竞选延期",
  sheriff_pk_start: "警长平票环节开始",
  sheriff_pk_started: "警长平票发言开始",
  sheriff_result: "公布警长结果",
  sheriff_tie: "警长投票平票",
  sheriff_no_badge: "本局无警徽",
  sheriff_runoff_tied: "警长加赛仍平票",
};

const QUALITY_GATE_LABELS: Record<string, string> = {
  lineup: "阵容质量",
  speech_quality: "发言质量",
  performance: "性能",
  choice_normalization: "选择规范化",
  public_outcomes: "公开结算",
};

const QUALITY_CODE_LABELS: Record<string, string> = {
  lineup_data_unavailable: "阵容数据不可用",
  lineup_blocked: "阵容存在阻断问题",
  lineup_passed: "阵容检查通过",
  speech_data_unavailable: "发言数据不可用",
  speech_checked: "发言检查完成",
  insufficient_latency_sample: "延迟样本不足",
  latency_checked: "延迟检查完成",
  choice_data_unavailable: "选择数据不可用",
  choice_checked: "选择检查完成",
  outcome_data_unavailable: "公开结算数据不可用",
  outcome_summary_checked: "结算与摘要一致",
  lineup_incomplete: "阵容不完整",
  personality_overrepresented: "同类性格过多",
  strategy_profile_overrepresented: "同类策略过多",
  catchphrase_overrepresented: "相同口头禅过多",
  avatar_overrepresented: "相同形象过多",
  tag_overrepresented: "相同标签过多",
  insufficient_style_buckets: "玩家风格多样性不足",
};

const QUALITY_SOURCE_STATUS_LABELS: Record<string, string> = {
  complete: "完整",
  partial: "部分可用",
  missing: "缺失",
  unavailable: "不可用",
  unknown: "未知",
};

const QUALITY_ISSUE_LABELS: Record<string, string> = {
  private_action_public_artifact: "私密动作进入公开内容",
  private_text_public_overlap: "公开内容与私密文本重合",
  private_voice_materialized: "私密内容被合成为语音",
  private_subtitle_materialized: "私密内容进入字幕",
  internal_death_cause_public: "内部死亡原因被公开",
  hidden_role_public_before_reveal: "身份在揭示前被公开",
  wolf_team_public_before_reveal: "狼队信息在揭示前被公开",
  private_role_result_public: "私密角色结果被公开",
  rejected_draft_public: "被拒绝的草稿进入公开内容",
  suspicious_private_term: "公开内容出现疑似私密术语",
};

const QUALITY_CHANNEL_LABELS: Record<string, string> = {
  live_event: "实时事件",
  voice: "语音",
  subtitle: "字幕",
  replay: "回放",
  public_state: "公开状态",
};

export function formatDateTime(value: string | null) {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function displayValue(value: string | null | undefined) {
  return value?.trim() || "—";
}

export function personalityLabel(value: string) {
  return PERSONALITY_LABELS[value] ?? "未识别性格";
}

export function eventTypeLabel(value: string) {
  return EVENT_TYPE_LABELS[value] ?? "未识别事件";
}

export function phaseLabel(value: string) {
  return PHASE_LABELS[value] ?? "未识别阶段";
}

export function actionLabel(value: string) {
  return ACTION_LABELS[value] ?? "未识别动作";
}

export function qualityPolicyLabel(value: string | null) {
  if (!value) return "—";
  return { observe: "观察", repair: "自动修复", enforce: "强制拦截" }[value] ?? "未识别模式";
}

export function qualityGateLabel(value: string) {
  return QUALITY_GATE_LABELS[value] ?? "未识别质量门槛";
}

export function qualityCodeLabel(value: string) {
  return QUALITY_CODE_LABELS[value] ?? "未识别检查结果";
}

export function qualitySourceStatusLabel(value: string) {
  return QUALITY_SOURCE_STATUS_LABELS[value] ?? "未知";
}

export function qualityIssueLabel(value: string) {
  return QUALITY_ISSUE_LABELS[value] ?? "未识别安全问题";
}

export function qualityChannelLabel(value: string) {
  return QUALITY_CHANNEL_LABELS[value] ?? "未知渠道";
}

export function qualitySeverityLabel(value: string) {
  return { warning: "警告", error: "错误", P0: "P0 严重", P1: "P1 高", P2: "P2 提醒" }[value] ?? value;
}

export function qualityActualLabel(value: string | null) {
  if (!value) return "—";
  if (value === "True" || value === "true") return "是";
  if (value === "False" || value === "false") return "否";
  if (value === "None" || value === "null") return "无数据";
  const performance = /^samples=(\d+),p95=(None|\d+)$/.exec(value);
  if (performance) {
    return `样本 ${performance[1]}，P95 ${performance[2] === "None" ? "无数据" : `${performance[2]} 毫秒`}`;
  }
  return value;
}
