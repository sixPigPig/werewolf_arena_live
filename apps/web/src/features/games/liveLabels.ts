import type { LiveGameEvent } from "./types";

const ACTION_LABELS: Record<string, string> = {
  debate: "公开发言",
  sheriff_speech: "警上发言",
  sheriff_pk_speech: "警长 PK 发言",
  sheriff_run: "选择是否上警",
  sheriff_withdraw: "选择是否退水",
  sheriff_vote: "警长投票",
  sheriff_runoff_vote: "警长 PK 投票",
  werewolf_self_explosion: "考虑自爆",
  investigate: "查验目标",
  remove: "夜间袭击",
  protect: "守护目标",
  witch_save: "选择是否救人",
  witch_poison: "选择是否用毒",
  hunter_shoot: "猎人开枪",
  speech_order: "决定发言顺序",
  sheriff_badge: "移交警徽",
  vote: "白天投票",
  bid: "表达发言意愿",
  summarize: "总结局势",
};

export function phaseLabel(phase: string | null) {
  if (phase === "night") {
    return "夜晚";
  }
  if (phase === "day") {
    return "白天";
  }
  if (phase === "vote") {
    return "投票";
  }
  if (phase === "summary") {
    return "总结";
  }
  return phase || "";
}

export function actionLabel(action: string | null) {
  if (!action) {
    return "行动";
  }
  return ACTION_LABELS[action] ?? action;
}

export function liveEventTitle(event: LiveGameEvent) {
  if (event.type === "run_created") {
    return "运行已创建";
  }
  if (event.type === "run_started") {
    return "运行已开始";
  }
  if (event.type === "game_started") {
    return "对局开始";
  }
  if (event.type === "round_started") {
    return event.round === null ? "新回合开始" : `第 ${event.round} 轮开始`;
  }
  if (event.type === "phase_started") {
    const label = phaseLabel(event.phase);
    return label ? `${label}阶段开始` : "阶段开始";
  }
  if (event.type === "action_requested" && event.actor) {
    return `${event.actor} 正在${actionLabel(event.action)}`;
  }
  if (event.type === "model_request_started" && event.actor) {
    return `${event.actor} 正在思考`;
  }
  if (event.type === "model_response_received" && event.actor) {
    return `${event.actor} 的模型返回已接收`;
  }
  if (event.type === "action_parsed" && event.actor) {
    return `${event.actor} 完成${actionLabel(event.action)}`;
  }
  if (event.type === "game_completed") {
    return "对局完成";
  }
  if (event.type === "game_failed") {
    return "对局失败";
  }
  return event.type;
}
