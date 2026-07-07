import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Gauge, Mic, Pause, Play, Radio, RotateCcw, Volume2 } from "lucide-react";

import {
  actionLabel,
  deriveGodViewState,
  liveEventTitle,
  phaseLabel,
  resolveAvatarImageUrl,
  useLiveDirector,
  type GameRunStatus,
  type GodViewPlayer,
  type LiveGameEvent,
  type LivePhaseSegment,
  type RuleSetSummary,
} from "@werewolf-arena/game-client";

import { MobileLivePhaseBar } from "./MobileLivePhaseBar";
import {
  splitMobileSubtitleText,
  subtitleSegmentDurationMs,
  type MobileLiveSubtitle,
} from "./mobileLiveSubtitle";

type LiveDirectorControlsState = ReturnType<typeof useLiveDirector>;
type GodViewState = ReturnType<typeof deriveGodViewState>;

const LIVE_SEAT_REVEAL_STAGGER_MS = 90;

export type MobileLiveTheaterRun = {
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
};

export type MobileLiveTheaterProps = {
  canResumeRun: boolean;
  currentEvent: LiveGameEvent | null;
  director: LiveDirectorControlsState;
  godViewState: GodViewState;
  liveStatusLabel: string;
  onBack: () => void;
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
  onSelectPhase,
  onResumeRun,
  onToggleVoice,
  phaseSegments,
  replayLinkVisible,
  resumeIsPending,
  run,
  subtitle = null,
  voiceEnabled,
  voiceState,
}: MobileLiveTheaterProps) {
  const currentPlayer = getCurrentTheaterPlayer(godViewState);
  const { left, right } = splitPlayersForColumns(godViewState.players);

  return (
    <section className="mobile-live-theater" aria-label="实时观战剧场">
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
        <LiveSeatColumn players={left} side="left" />
        <LiveCenterStage
          currentEvent={currentEvent}
          currentPlayer={currentPlayer}
          godViewState={godViewState}
          subtitle={subtitle}
        />
        <LiveSeatColumn players={right} side="right" />
      </section>
      <LiveTheaterControls
        canResumeRun={canResumeRun}
        currentPlayer={currentPlayer}
        director={director}
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
  side: "left" | "right";
};

export function LiveSeatColumn({ players, side }: LiveSeatColumnProps) {
  return (
    <div className={`mobile-live-seat-column mobile-live-seat-column-${side}`}>
      {players.map((player, index) => (
        <LiveSeatAvatar
          key={player.name}
          player={player}
          revealIndex={index}
          revealSide={side}
        />
      ))}
    </div>
  );
}

type LiveSeatAvatarProps = {
  player: GodViewPlayer;
  revealIndex?: number;
  revealSide?: "left" | "right";
};

export function LiveSeatAvatar({
  player,
  revealIndex = 0,
  revealSide = "left",
}: LiveSeatAvatarProps) {
  const roleLabel = roleShortLabel(player.role);
  const statusLabel = player.isSpeaking ? "发言中" : player.stageStatus.label;
  const seatLabel = `${player.seatNumber}号 ${player.name} ${player.role || "未知"} ${statusLabel}`;
  const avatarImageUrl = resolveAvatarImageUrl({
    avatar_image_url: player.avatarImageUrl,
  });
  const className = [
    "mobile-live-seat",
    `mobile-live-seat-reveal-${revealSide}`,
    player.isSpeaking ? "mobile-live-seat-speaking" : "",
    player.isAlive ? "" : "mobile-live-seat-out",
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
        <span className="mobile-live-seat-avatar">
          {avatarImageUrl ? (
            <img alt="" src={avatarImageUrl} />
          ) : (
            <span>{avatarInitial(player.name, player.seatNumber)}</span>
          )}
        </span>
        <span className="mobile-live-seat-role">{roleLabel}</span>
      </span>
      <span className="mobile-live-seat-nameplate">
        <strong>{player.name}</strong>
        <small className="mobile-live-seat-status">{statusLabel}</small>
      </span>
    </article>
  );
}

type LiveCenterStageProps = {
  currentEvent: LiveGameEvent | null;
  currentPlayer: GodViewPlayer | null;
  godViewState: GodViewState;
  subtitle: MobileLiveSubtitle | null;
};

export function LiveCenterStage({
  currentEvent,
  currentPlayer,
  godViewState,
  subtitle,
}: LiveCenterStageProps) {
  const presenterAvatarImageUrl = currentPlayer
    ? resolveAvatarImageUrl({
        avatar_image_url: currentPlayer.avatarImageUrl,
      })
    : null;

  return (
    <section className="mobile-live-center-stage" aria-label="当前舞台">
      <div className="mobile-live-presenter" aria-hidden="true">
        {presenterAvatarImageUrl ? (
          <img alt="" src={presenterAvatarImageUrl} />
        ) : (
          <span>
            {currentPlayer
              ? avatarInitial(currentPlayer.name, currentPlayer.seatNumber)
              : "?"}
          </span>
        )}
        {currentPlayer ? (
          <span className="mobile-live-presenter-mic">
            <Mic aria-hidden="true" size={14} strokeWidth={2.8} />
          </span>
        ) : null}
      </div>
      <span>{currentPlayer ? `${currentPlayer.seatNumber}号` : "等待"}</span>
      <strong>{currentPlayer?.name ?? "等待玩家行动"}</strong>
      <em>{currentPlayer?.stageStatus.label ?? godViewState.currentSeatLabel}</em>
      <p>{currentEvent ? liveStageEventLabel(currentEvent) : "等待事件"}</p>
      {subtitle ? <LiveSubtitle subtitle={subtitle} /> : null}
      {currentEvent?.phase ? (
        <small>{phaseLabel(currentEvent.phase)}阶段</small>
      ) : null}
    </section>
  );
}

type LiveSubtitleProps = {
  subtitle: MobileLiveSubtitle;
};

function LiveSubtitle({ subtitle }: LiveSubtitleProps) {
  const { segmentText } = useLiveSubtitleSegment(subtitle);
  const className = [
    "mobile-live-subtitle",
    subtitle.tone === "judge"
      ? "mobile-live-subtitle-judge"
      : `mobile-live-subtitle-player-${subtitle.colorIndex}`,
  ].join(" ");

  return (
    <div aria-label="直播字幕" className={className} role="status">
      <strong>{subtitle.speakerName}</strong>
      <span>{segmentText}</span>
    </div>
  );
}

function useLiveSubtitleSegment(subtitle: MobileLiveSubtitle) {
  const segments = useMemo(
    () => splitMobileSubtitleText(subtitle.text),
    [subtitle.text],
  );
  const subtitleKey = `${subtitle.tone}:${subtitle.colorIndex}:${subtitle.speakerName}`;
  const previousKeyRef = useRef(subtitleKey);
  const previousTextRef = useRef(subtitle.text);
  const [segmentIndex, setSegmentIndex] = useState(0);
  const segmentCount = segments.length;
  const segmentText = segments[segmentIndex] ?? subtitle.text;

  useEffect(() => {
    const isSameGrowingSpeech =
      previousKeyRef.current === subtitleKey &&
      subtitle.text.startsWith(previousTextRef.current);

    previousKeyRef.current = subtitleKey;
    previousTextRef.current = subtitle.text;
    setSegmentIndex((currentIndex) =>
      isSameGrowingSpeech ? Math.min(currentIndex, segmentCount - 1) : 0,
    );
  }, [segmentCount, subtitle.text, subtitleKey]);

  useEffect(() => {
    if (segmentIndex >= segmentCount - 1) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setSegmentIndex((currentIndex) =>
        Math.min(currentIndex + 1, segmentCount - 1),
      );
    }, subtitleSegmentDurationMs(segmentText));

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [segmentCount, segmentIndex, segmentText, subtitleKey]);

  return { segmentText };
}

type LiveTheaterControlsProps = {
  canResumeRun: boolean;
  currentPlayer: GodViewPlayer | null;
  director: LiveDirectorControlsState;
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
    </footer>
  );
}

function liveStageEventLabel(event: LiveGameEvent) {
  return event.action ? actionLabel(event.action) : liveEventTitle(event);
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

function getCurrentTheaterPlayer(state: GodViewState) {
  return (
    state.speakerFlow.current ??
    state.players.find((player) => player.isSpeaking) ??
    null
  );
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
