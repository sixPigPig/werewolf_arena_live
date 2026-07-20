import { useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import {
  BadgeCheck,
  Gauge,
  Gavel,
  Hand,
  PawPrint,
  Pause,
  Play,
  Radio,
  RotateCcw,
  Volume2,
} from "lucide-react";

import {
  deriveGodViewState,
  resolveAvatarImageUrl,
  useLiveDirector,
  type GameRunStatus,
  type GodViewPlayer,
  type LiveGameEvent,
  type LivePhaseSegment,
  type RuleSetSummary,
} from "@werewolf-arena/game-client";

import { MobileLivePhaseBar } from "./MobileLivePhaseBar";
import { MobileLiveActionStage } from "./MobileLiveActionStage";
import { MobileLiveEventRail } from "./MobileLiveEventRail";
import {
  deriveMobileLiveFocusPresentation,
  getActiveTheaterPlayer,
  type MobileLiveFocusPresentation,
} from "./mobileLiveActionModel";
import { type MobileLiveSubtitle } from "./mobileLiveSubtitle";

type LiveDirectorControlsState = ReturnType<typeof useLiveDirector>;
type GodViewState = ReturnType<typeof deriveGodViewState>;

const LIVE_SEAT_REVEAL_STAGGER_MS = 90;

export type MobileLiveTheaterRun = {
  error?: string | null;
  session_id: string;
  status: GameRunStatus | (string & {});
  rule_set?: RuleSetSummary | null;
};

export type MobileLiveVoiceState = {
  connectionState:
    | "idle"
    | "connecting"
    | "open"
    | "error"
    | "closed"
    | "unavailable";
  currentSpeakerName: string | null;
  errors?: string[];
};

export type MobileLiveTheaterProps = {
  canResumeRun: boolean;
  currentEvent: LiveGameEvent | null;
  director: LiveDirectorControlsState;
  godViewState: GodViewState;
  liveStatusLabel: string;
  onBack: () => void;
  onSelectEvent?: (eventId: number) => void;
  onSelectPhase: (segment: LivePhaseSegment) => void;
  onResumeRun: () => void;
  onToggleVoice?: () => void;
  phaseSegments: LivePhaseSegment[];
  replayLinkVisible: boolean;
  resumeIsPending: boolean;
  run: MobileLiveTheaterRun;
  subtitle?: MobileLiveSubtitle | null;
  terminalEvent: LiveGameEvent | undefined;
  voiceEnabled?: boolean;
  voiceState?: MobileLiveVoiceState;
};

export function MobileLiveTheater({
  canResumeRun,
  currentEvent,
  director,
  godViewState,
  liveStatusLabel,
  onBack,
  onSelectEvent,
  onSelectPhase,
  onResumeRun,
  onToggleVoice,
  phaseSegments,
  replayLinkVisible,
  resumeIsPending,
  run,
  subtitle = null,
  terminalEvent,
  voiceEnabled,
  voiceState,
}: MobileLiveTheaterProps) {
  const currentPlayer = getActiveTheaterPlayer(godViewState);
  const presentation = deriveMobileLiveFocusPresentation(currentEvent, godViewState);
  const { left, right } = splitPlayersForColumns(godViewState.players);
  const failureReason = getLiveFailureReason(terminalEvent, run);
  const theaterRef = useRef<HTMLElement | null>(null);
  const railTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [eventSheetOpen, setEventSheetOpen] = useState(false);

  return (
    <section className="mobile-live-theater" aria-label="实时观战剧场" ref={theaterRef}>
      <MobileLiveTheaterTopBar
        liveStatusLabel={liveStatusLabel}
        onBack={onBack}
        onSelectPhase={onSelectPhase}
        phaseSegments={phaseSegments}
        ruleName={run.rule_set?.name ?? "实时对局"}
      />
      <LiveSkyBanner
        dayNightLabel={godViewState.dayNightLabel}
        phaseLabel={godViewState.phaseLabel}
      />
      <section className="mobile-live-seat-stage" aria-label="玩家席位">
        <LiveSeatColumn players={left} presentation={presentation} side="left" />
        <MobileLiveActionStage
          presentation={presentation}
          currentPlayer={currentPlayer}
          godViewState={godViewState}
        />
        <LiveSeatColumn players={right} presentation={presentation} side="right" />
        {subtitle ? <LiveSubtitle subtitle={subtitle} /> : null}
      </section>
      <MobileLiveEventRail
        backgroundRef={theaterRef}
        eventLines={godViewState.eventLines}
        godViewState={godViewState}
        onCloseSheet={() => setEventSheetOpen(false)}
        onSelectEvent={(eventId) => {
          setEventSheetOpen(false);
          onSelectEvent?.(eventId);
        }}
        onToggleSheet={() => setEventSheetOpen((value) => !value)}
        sheetOpen={eventSheetOpen}
        triggerRef={railTriggerRef}
      />
      <LiveTheaterControls
        canResumeRun={canResumeRun}
        currentPlayer={currentPlayer}
        director={director}
        failureReason={failureReason}
        godViewState={godViewState}
        onResumeRun={onResumeRun}
        onToggleVoice={onToggleVoice}
        replayLinkVisible={replayLinkVisible}
        resumeIsPending={resumeIsPending}
        run={run}
        voiceEnabled={voiceEnabled}
        voiceState={voiceState}
      />
    </section>
  );
}

type MobileLiveTheaterTopBarProps = {
  liveStatusLabel: string;
  onBack: () => void;
  onSelectPhase?: (segment: LivePhaseSegment) => void;
  phaseSegments?: LivePhaseSegment[];
  ruleName: string;
};

export function MobileLiveTheaterTopBar({
  liveStatusLabel,
  onBack,
  onSelectPhase,
  phaseSegments = [],
  ruleName,
}: MobileLiveTheaterTopBarProps) {
  return (
    <header className="mobile-live-theater-top">
      <button
        aria-label="返回对局大厅"
        className="mobile-live-back-button"
        onClick={onBack}
        type="button"
      />
      <div className="mobile-live-title-board">
        <strong>{ruleName}</strong>
        <span>{liveStatusLabel}</span>
      </div>
      {onSelectPhase ? (
        <MobileLivePhaseBar
          onSelectPhase={onSelectPhase}
          segments={phaseSegments}
        />
      ) : null}
    </header>
  );
}

type LiveSkyBannerProps = {
  dayNightLabel: string;
  phaseLabel: string;
};

export function LiveSkyBanner({ dayNightLabel, phaseLabel }: LiveSkyBannerProps) {
  return (
    <section className="mobile-live-sky" aria-label="当前轮次">
      <div className="mobile-live-sky-orb" aria-hidden="true" />
      <div className="mobile-live-day-banner">
        <span>{phaseLabel}</span>
        <strong>{dayNightLabel}</strong>
      </div>
    </section>
  );
}

type LiveSeatColumnProps = {
  players: GodViewPlayer[];
  presentation: MobileLiveFocusPresentation;
  side: "left" | "right";
};

export function LiveSeatColumn({ players, presentation, side }: LiveSeatColumnProps) {
  return (
    <div className={`mobile-live-seat-column mobile-live-seat-column-${side}`}>
      {players.map((player, index) => (
        <LiveSeatAvatar
          key={player.name}
          player={player}
          presentation={presentation}
          revealIndex={index}
          revealSide={side}
        />
      ))}
    </div>
  );
}

type LiveSeatAvatarProps = {
  player: GodViewPlayer;
  presentation: MobileLiveFocusPresentation;
  revealIndex?: number;
  revealSide?: "left" | "right";
};

export function LiveSeatAvatar({
  player,
  presentation,
  revealIndex = 0,
  revealSide = "left",
}: LiveSeatAvatarProps) {
  const roleLabel = roleShortLabel(player.role);
  const statusLabel = player.isSpeaking ? "发言中" : player.stageStatus.label;
  const exitMarker = liveSeatExitMarker(player);
  const modifier = seatModifierFor(player, presentation);
  const seatLabel = `${player.seatNumber}号 ${player.name} ${player.role || "未知"} ${statusLabel}${player.isSheriff ? " 警长" : ""}${player.hasRaisedHand ? " 举手上警" : ""}${player.hasWithdrawn ? " 已退水" : ""}`;
  const avatarImageUrl = resolveAvatarImageUrl({
    avatar_image_url: player.avatarImageUrl,
  });
  const className = [
    "mobile-live-seat",
    `mobile-live-seat-reveal-${revealSide}`,
    player.isSheriff ? "mobile-live-seat-sheriff" : "",
    player.isSpeaking ? "mobile-live-seat-speaking" : "",
    player.isAlive ? "" : "mobile-live-seat-out",
    modifier.acting ? "mobile-live-seat-acting" : "",
    modifier.targetTone ? `mobile-live-seat-target mobile-live-seat-target-${modifier.targetTone}` : "",
    modifier.voteCount !== null ? "mobile-live-seat-vote-target" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const revealStyle = {
    "--mobile-live-seat-reveal-delay": `${revealIndex * LIVE_SEAT_REVEAL_STAGGER_MS}ms`,
  } as CSSProperties;

  return (
    <article aria-label={seatLabel} className={className} style={revealStyle}>
      <span className="mobile-live-seat-medal">
        <span className="mobile-live-seat-number">{player.seatNumber}</span>
        {player.isSheriff ? (
          <span
            aria-label="警长，持有警徽"
            className="mobile-live-seat-sheriff-badge"
            role="img"
          >
            <BadgeCheck aria-hidden="true" strokeWidth={2.4} />
          </span>
        ) : null}
        {player.hasRaisedHand ? (
          <span
            aria-label="举手上警"
            className="mobile-live-seat-raised-hand"
            role="img"
          >
            <Hand aria-hidden="true" strokeWidth={2.4} />
          </span>
        ) : null}
        {player.hasWithdrawn ? (
          <span
            aria-label="已退水"
            className="mobile-live-seat-withdrawn"
            role="img"
          >
            退
          </span>
        ) : null}
        <span className="mobile-live-seat-avatar">
          {avatarImageUrl ? (
            <img alt="" src={avatarImageUrl} />
          ) : (
            <span>{avatarInitial(player.name, player.seatNumber)}</span>
          )}
        </span>
        {exitMarker === "night" ? (
          <span
            aria-label="夜晚出局"
            className="mobile-live-seat-outcome mobile-live-seat-outcome-night"
            role="img"
          >
            <PawPrint aria-hidden="true" strokeWidth={1.8} />
          </span>
        ) : null}
        {exitMarker === "day-exile" ? (
          <span
            aria-label="白天驱逐"
            className="mobile-live-seat-outcome mobile-live-seat-outcome-day-exile"
            role="img"
          >
            <Gavel aria-hidden="true" strokeWidth={2.2} />
          </span>
        ) : null}
        {modifier.targetIcon ? (
          <span
            aria-label={`目标${modifier.targetLabel}`}
            className={`mobile-live-seat-badge mobile-live-seat-badge-${modifier.targetTone}`}
            role="img"
          >
            {modifier.targetIcon}
          </span>
        ) : null}
        {modifier.voteCount !== null ? (
          <span
            aria-label={`${modifier.voteCount}票`}
            className="mobile-live-seat-vote-count"
          >
            {modifier.voteCount}票
          </span>
        ) : null}
        <span className="mobile-live-seat-role">{roleLabel}</span>
      </span>
    </article>
  );
}

type SeatModifier = {
  acting: boolean;
  targetTone: "" | "danger" | "success" | "info" | "warning";
  targetLabel: string;
  targetIcon: "刀" | "救" | "毒" | "守" | "查" | "投" | "逐" | null;
  voteCount: number | null;
};

function seatModifierFor(
  player: GodViewPlayer,
  presentation: MobileLiveFocusPresentation,
): SeatModifier {
  const isWerewolfTeamActing =
    presentation.kind === "night-action" &&
    presentation.actorName === "狼人阵营" &&
    presentation.targetName === null &&
    player.identityGroup === "狼人";
  const acting =
    (presentation.actorSeat === player.seatNumber || isWerewolfTeamActing) &&
    presentation.kind !== "night-result" &&
    presentation.kind !== "vote-result" &&
    presentation.kind !== "terminal";

  const targetTone = targetToneFor(presentation);
  const isTarget =
    Boolean(targetTone) &&
    presentation.targetName !== null &&
    presentation.targetName === player.name;
  const targetLabel = isTarget ? targetLabelFor(presentation) : "";
  const targetIcon = isTarget ? targetIconFor(presentation) : null;

  const showVoteCount =
    (presentation.kind === "vote-action" || presentation.kind === "vote-result") &&
    player.receivedVotes > 0;
  const voteCount = showVoteCount ? player.receivedVotes : null;

  return {
    acting,
    targetTone: isTarget ? targetTone : "",
    targetLabel,
    targetIcon,
    voteCount,
  };
}

function targetToneFor(
  presentation: MobileLiveFocusPresentation,
): "" | "danger" | "success" | "info" | "warning" {
  if (presentation.kind === "night-action") {
    if (presentation.tone === "danger") return "danger";
    if (presentation.tone === "success") return "success";
    if (presentation.tone === "info") return "info";
  }
  if (presentation.kind === "vote-action" || presentation.kind === "vote-result") {
    return "warning";
  }
  return "";
}

function targetLabelFor(presentation: MobileLiveFocusPresentation): string {
  if (presentation.kind === "vote-action") return "投票";
  if (presentation.kind === "vote-result") return "票型";
  return presentation.title;
}

function targetIconFor(
  presentation: MobileLiveFocusPresentation,
): SeatModifier["targetIcon"] {
  if (presentation.kind === "vote-action" || presentation.kind === "vote-result") {
    return "投";
  }
  if (
    presentation.eyebrow === "狼人阵营" ||
    presentation.eyebrow === "狼人目标" ||
    presentation.eyebrow === "狼人刀票"
  ) {
    return "刀";
  }
  if (presentation.eyebrow === "女巫") {
    return presentation.tone === "danger" ? "毒" : "救";
  }
  if (presentation.eyebrow === "守卫") return "守";
  if (presentation.eyebrow === "预言家") return "查";
  return null;
}

type LiveSeatExitMarker = "night" | "day-exile" | null;

function liveSeatExitMarker(player: GodViewPlayer): LiveSeatExitMarker {
  if (!player.isAlive && player.exitKind === "night") {
    return "night";
  }
  if (!player.isAlive && player.exitKind === "day-exile") {
    return "day-exile";
  }

  return null;
}

type LiveSubtitleProps = {
  subtitle: MobileLiveSubtitle;
};

function LiveSubtitle({ subtitle }: LiveSubtitleProps) {
  const className = [
    "mobile-live-subtitle",
    subtitle.tone === "judge"
      ? "mobile-live-subtitle-judge"
      : subtitle.tone === "private"
        ? "mobile-live-subtitle-private"
        : `mobile-live-subtitle-player-${subtitle.colorIndex}`,
  ].join(" ");

  return (
    <div aria-label="直播字幕" className={className} role="status">
      <strong>{subtitle.speakerName}</strong>
      {subtitle.statusLabel ? (
        <em className="mobile-live-subtitle-status">{subtitle.statusLabel}</em>
      ) : null}
      <span aria-label={subtitle.text} className="mobile-live-subtitle-text">
        <span
          aria-hidden="true"
          className="mobile-live-subtitle-completed"
        >
          {subtitle.completedText}
        </span>
        <span aria-hidden="true" className="mobile-live-subtitle-active">
          {subtitle.activeText}
        </span>
        <span aria-hidden="true" className="mobile-live-subtitle-pending">
          {subtitle.pendingText}
        </span>
      </span>
    </div>
  );
}

type LiveTheaterControlsProps = {
  canResumeRun: boolean;
  currentPlayer: GodViewPlayer | null;
  director: LiveDirectorControlsState;
  failureReason: string | null;
  godViewState: GodViewState;
  onResumeRun: () => void;
  onToggleVoice?: () => void;
  replayLinkVisible: boolean;
  resumeIsPending: boolean;
  run: MobileLiveTheaterRun;
  voiceEnabled?: boolean;
  voiceState?: MobileLiveVoiceState;
};

export function LiveTheaterControls({
  canResumeRun,
  currentPlayer,
  director,
  failureReason,
  godViewState,
  onResumeRun,
  onToggleVoice,
  replayLinkVisible,
  resumeIsPending,
  run,
  voiceEnabled,
  voiceState,
}: LiveTheaterControlsProps) {
  const canToggleVoice = Boolean(onToggleVoice && voiceState);
  const voiceIssueMessage = voiceState?.errors?.at(-1) ?? null;
  const failureTitle =
    run.status === "canceled" ? "对局已停止" : "对局异常中断";

  return (
    <footer className="mobile-live-control-deck" aria-label="实时观战操作">
      <div className="mobile-live-focus-strip">
        <span>{currentPlayer ? `${currentPlayer.seatNumber}` : "-"}</span>
        <strong>{currentPlayer?.name ?? "等待行动"}</strong>
        <em>{godViewState.countdownLabel}</em>
      </div>
      <div className="mobile-live-action-bar">
        <button
          className="mobile-button"
          onClick={director.togglePaused}
          type="button"
        >
          <span className="mobile-live-control-icon">
            {director.isPaused ? (
              <Play aria-hidden="true" size={18} strokeWidth={2.8} />
            ) : (
              <Pause aria-hidden="true" size={18} strokeWidth={2.8} />
            )}
          </span>
          <span className="mobile-live-control-label">
            {director.isPaused ? "继续" : "暂停"}
          </span>
        </button>
        {canToggleVoice && voiceState && onToggleVoice ? (
          <button
            aria-label={voiceControlAriaLabel(Boolean(voiceEnabled), voiceState)}
            className="mobile-button"
            disabled={voiceState.connectionState === "unavailable"}
            onClick={onToggleVoice}
            type="button"
          >
            <span className="mobile-live-control-icon">
              <Volume2 aria-hidden="true" size={18} strokeWidth={2.8} />
            </span>
            <span className="mobile-live-control-label">
              {voiceControlLabel(Boolean(voiceEnabled), voiceState)}
            </span>
          </button>
        ) : null}
        <button
          className="mobile-button"
          onClick={() => director.setSpeed(director.speed === 1 ? 2 : 1)}
          type="button"
        >
          <span className="mobile-live-control-icon">
            <Gauge aria-hidden="true" size={18} strokeWidth={2.8} />
          </span>
          <span className="mobile-live-control-label">
            {director.speed === 1 ? "1x" : "2x"}
          </span>
        </button>
        <button
          className="mobile-button"
          onClick={director.catchUpToLatest}
          type="button"
        >
          <span className="mobile-live-control-icon">
            <Radio aria-hidden="true" size={18} strokeWidth={2.8} />
          </span>
          <span className="mobile-live-control-label">最新</span>
        </button>
        {canResumeRun ? (
          <button
            className="mobile-button mobile-button-primary"
            disabled={resumeIsPending}
            onClick={onResumeRun}
            type="button"
          >
            <span className="mobile-live-control-icon">
              <Play aria-hidden="true" size={18} strokeWidth={2.8} />
            </span>
            <span className="mobile-live-control-label">
              {resumeIsPending ? "继续中" : "继续对局"}
            </span>
          </button>
        ) : replayLinkVisible ? (
          <Link
            className="mobile-button mobile-live-link"
            to={`/games/${run.session_id}/replay`}
          >
            <span className="mobile-live-control-icon">
              <RotateCcw aria-hidden="true" size={18} strokeWidth={2.8} />
            </span>
            <span className="mobile-live-control-label">复盘</span>
          </Link>
        ) : (
          <button className="mobile-button mobile-live-link" disabled type="button">
            <span className="mobile-live-control-icon">
              <RotateCcw aria-hidden="true" size={18} strokeWidth={2.8} />
            </span>
            <span className="mobile-live-control-label">复盘</span>
          </button>
        )}
      </div>
      {failureReason ? (
        <p className="mobile-live-failure-notice" role="alert">
          <strong>{failureTitle}</strong>
          <span>{failureReason}</span>
        </p>
      ) : null}
      {voiceIssueMessage ? (
        <p className="mobile-live-voice-notice" role="status">
          {voiceIssueMessage}
        </p>
      ) : null}
    </footer>
  );
}

function voiceControlLabel(enabled: boolean, state: MobileLiveVoiceState) {
  if (state.connectionState === "unavailable") {
    return "不可用";
  }
  if (!enabled) {
    return "语音";
  }
  if (state.connectionState === "connecting") {
    return "连接中";
  }
  if (state.connectionState === "error") {
    return "重试";
  }

  return state.currentSpeakerName ?? "语音";
}

function voiceControlAriaLabel(enabled: boolean, state: MobileLiveVoiceState) {
  if (state.connectionState === "unavailable") {
    return "语音不可用";
  }
  if (enabled && state.connectionState === "error") {
    return "重试语音";
  }

  return enabled ? "关闭语音" : "开启语音";
}

function getLiveFailureReason(
  terminalEvent: LiveGameEvent | undefined,
  run: MobileLiveTheaterRun,
) {
  if (terminalEvent?.type === "game_canceled" || run.status === "canceled") {
    return "本次运行已由管理员停止；如存在检查点，可稍后恢复。";
  }
  if (terminalEvent?.type === "game_failed") {
    const eventError = stringField(terminalEvent.payload, "error");
    if (eventError) {
      return eventError;
    }
  }

  if (run.status === "failed") {
    const runError = run.error?.trim();
    if (runError) {
      return runError;
    }
  }

  return null;
}

function stringField(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function splitPlayersForColumns(players: GodViewPlayer[]) {
  const midpoint = Math.ceil(players.length / 2);

  return {
    left: players.slice(0, midpoint),
    right: players.slice(midpoint),
  };
}

function avatarInitial(name: string, seatNumber: number) {
  const trimmed = name.trim();

  return trimmed ? trimmed.slice(0, 1) : String(seatNumber);
}

function roleShortLabel(role: string) {
  const labels: Record<string, string> = {
    guard: "守",
    doctor: "医",
    hunter: "猎",
    idiot: "白",
    seer: "预",
    villager: "民",
    werewolf: "狼",
    witch: "巫",
    守卫: "守",
    医生: "医",
    平民: "民",
    村民: "民",
    狼人: "狼",
    预言家: "预",
    女巫: "巫",
    猎人: "猎",
    白痴: "白",
  };
  const trimmed = role.trim();
  const normalized = trimmed.toLowerCase();

  return (
    labels[normalized] ?? labels[trimmed] ?? (trimmed.slice(0, 1) || "未知")
  );
}
