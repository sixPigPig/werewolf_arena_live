import type {
  GamePhase,
  LiveState,
  MatchState,
  MatchStatus,
  RuntimeProjection,
} from "./contracts";

export function runtimeFromSnapshot(
  snapshot: RuntimeProjection,
): RuntimeProjection {
  return {
    audio_mode: snapshot.audio_mode,
    match_status: snapshot.match_status,
    execution_state: snapshot.execution_state,
    winner: snapshot.winner,
    completion_reason: snapshot.completion_reason,
    completed_at: snapshot.completed_at,
  };
}

export function effectiveWinner(
  runtime: RuntimeProjection | null,
  match: MatchState | null,
): RuntimeProjection["winner"] {
  return runtime?.winner ?? match?.winner ?? null;
}

export function effectiveMatchStatus(
  runtime: RuntimeProjection | null,
  phase: GamePhase | null,
  match: MatchState | null,
  liveState: LiveState | null,
): MatchStatus | null {
  const winner = effectiveWinner(runtime, match);
  if (runtime !== null) {
    return runtime.match_status === "completed" && winner === null
      ? null
      : runtime.match_status;
  }
  if (phase?.phase_state === "game_completed" && winner !== null) {
    return "completed";
  }
  if (liveState === "canceled") {
    return "canceled";
  }
  if (
    liveState === "failed" ||
    phase?.phase_state === "failed"
  ) {
    return "failed";
  }
  return null;
}

export function awaitingObservationLabel(
  runtime: RuntimeProjection | null,
): string {
  if (runtime?.execution_state === "owned") return "等待观察/播放确认";
  if (
    runtime?.execution_state === "stopped" ||
    runtime?.execution_state === "stale"
  ) {
    return "实时流程已停止";
  }
  if (runtime?.execution_state === "unowned") return "等待执行器接管";
  return "等待实时流程状态确认";
}
