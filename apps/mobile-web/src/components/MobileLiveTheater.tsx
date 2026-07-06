import { Link } from "react-router-dom";

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

type LiveDirectorControlsState = ReturnType<typeof useLiveDirector>;
type GodViewState = ReturnType<typeof deriveGodViewState>;

export type MobileLiveTheaterRun = {
  session_id: string;
  status: GameRunStatus | (string & {});
  rule_set?: RuleSetSummary | null;
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
  phaseSegments: LivePhaseSegment[];
  replayLinkVisible: boolean;
  resumeIsPending: boolean;
  run: MobileLiveTheaterRun;
  terminalEvent: LiveGameEvent | undefined;
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
  phaseSegments,
  replayLinkVisible,
  resumeIsPending,
  run,
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
        />
        <LiveSeatColumn players={right} side="right" />
      </section>
      <LiveTheaterControls
        canResumeRun={canResumeRun}
        currentPlayer={currentPlayer}
        director={director}
        godViewState={godViewState}
        onResumeRun={onResumeRun}
        replayLinkVisible={replayLinkVisible}
        resumeIsPending={resumeIsPending}
        run={run}
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
      {players.map((player) => (
        <LiveSeatAvatar key={player.name} player={player} />
      ))}
    </div>
  );
}

type LiveSeatAvatarProps = {
  player: GodViewPlayer;
};

export function LiveSeatAvatar({ player }: LiveSeatAvatarProps) {
  const roleLabel = roleShortLabel(player.role);
  const statusLabel = player.isSpeaking ? "发言中" : player.stageStatus.label;
  const seatLabel = `${player.seatNumber}号 ${player.name} ${player.role || "未知"} ${statusLabel}`;
  const avatarImageUrl = resolveAvatarImageUrl({
    avatar_image_url: player.avatarImageUrl,
  });
  const className = [
    "mobile-live-seat",
    player.isSpeaking ? "mobile-live-seat-speaking" : "",
    player.isAlive ? "" : "mobile-live-seat-out",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <article aria-label={seatLabel} className={className}>
      <span className="mobile-live-seat-number">{player.seatNumber}</span>
      <span className="mobile-live-seat-avatar">
        {avatarImageUrl ? (
          <img alt="" src={avatarImageUrl} />
        ) : (
          <span>{avatarInitial(player.name, player.seatNumber)}</span>
        )}
      </span>
      <span className="mobile-live-seat-role">{roleLabel}</span>
      <strong>{player.name}</strong>
      <small>{statusLabel}</small>
    </article>
  );
}

type LiveCenterStageProps = {
  currentEvent: LiveGameEvent | null;
  currentPlayer: GodViewPlayer | null;
  godViewState: GodViewState;
};

export function LiveCenterStage({
  currentEvent,
  currentPlayer,
  godViewState,
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
      </div>
      <span>{currentPlayer ? `${currentPlayer.seatNumber}号` : "等待"}</span>
      <strong>{currentPlayer?.name ?? "等待玩家行动"}</strong>
      <em>{currentPlayer?.stageStatus.label ?? godViewState.currentSeatLabel}</em>
      <p>{currentEvent?.type ?? "等待事件"}</p>
      {currentEvent?.action ? <small>{currentEvent.action}</small> : null}
    </section>
  );
}

type LiveTheaterControlsProps = {
  canResumeRun: boolean;
  currentPlayer: GodViewPlayer | null;
  director: LiveDirectorControlsState;
  godViewState: GodViewState;
  onResumeRun: () => void;
  replayLinkVisible: boolean;
  resumeIsPending: boolean;
  run: MobileLiveTheaterRun;
};

export function LiveTheaterControls({
  canResumeRun,
  currentPlayer,
  director,
  godViewState,
  onResumeRun,
  replayLinkVisible,
  resumeIsPending,
  run,
}: LiveTheaterControlsProps) {
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
          {director.isPaused ? "继续" : "暂停"}
        </button>
        <button
          className="mobile-button"
          onClick={() => director.setSpeed(director.speed === 1 ? 2 : 1)}
          type="button"
        >
          {director.speed === 1 ? "1x" : "2x"}
        </button>
        <button
          className="mobile-button"
          onClick={director.catchUpToLatest}
          type="button"
        >
          最新
        </button>
        {canResumeRun ? (
          <button
            className="mobile-button mobile-button-primary"
            disabled={resumeIsPending}
            onClick={onResumeRun}
            type="button"
          >
            {resumeIsPending ? "继续中" : "继续对局"}
          </button>
        ) : null}
        {replayLinkVisible ? (
          <Link
            className="mobile-button mobile-live-link"
            to={`/games/${run.session_id}/replay`}
          >
            复盘
          </Link>
        ) : null}
      </div>
    </footer>
  );
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
