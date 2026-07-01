import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  deriveGodViewState,
  deriveLiveNavStatus,
  deriveLiveSpectatorState,
  getGameRun,
  resumeGameRun,
  resolveAvatarImageUrl,
  useGameRunEvents,
  useLiveDirector,
  type GameRun,
  type GodViewPlayer,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";

const EMPTY_EVENTS: LiveGameEvent[] = [];

export function LivePage() {
  const { gameId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { connectionState, events, latestEvent } = useGameRunEvents(gameId);
  const runQuery = useQuery({
    queryKey: ["game-run", gameId],
    queryFn: () => getGameRun(gameId ?? ""),
    enabled: Boolean(gameId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 15000;
    },
  });
  const resumeMutation = useMutation({
    mutationFn: (sessionId: string) => resumeGameRun(sessionId),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["games"] });
      void queryClient.invalidateQueries({ queryKey: ["game-run", gameId] });
      navigate(`/games/${run.run_id}/live`);
    },
  });

  const run = runQuery.data;
  const terminalEvent = events.find(isTerminalEvent);
  const director = useLiveDirector(events, {
    resetKey: gameId,
    startAtLatestTerminal: isTerminalRunStatus(run?.status),
  });
  const stageEvents = useMemo(() => {
    const currentEventId = director.currentEventId;
    if (currentEventId === null) {
      return EMPTY_EVENTS;
    }

    const visibleEvents = events.filter((event) => event.id <= currentEventId);
    if (
      !director.isPaused &&
      director.backlogCount === 0 &&
      latestEvent &&
      latestEvent.id > currentEventId &&
      isLiveSpeakerDelta(latestEvent) &&
      !visibleEvents.some((event) => event.id === latestEvent.id)
    ) {
      return [...visibleEvents, latestEvent];
    }

    return visibleEvents;
  }, [
    director.backlogCount,
    director.currentEventId,
    director.isPaused,
    events,
    latestEvent,
  ]);
  const currentEvent = stageEvents.at(-1) ?? latestEvent;
  const spectatorState = useMemo(
    () => deriveLiveSpectatorState(stageEvents),
    [stageEvents],
  );
  const godViewState = useMemo(
    () =>
      deriveGodViewState(
        stageEvents,
        spectatorState,
        run?.rule_set?.name ?? "实时对局",
        { sheriffEnabled: run?.rule_set?.sheriff_enabled },
      ),
    [
      run?.rule_set?.name,
      run?.rule_set?.sheriff_enabled,
      spectatorState,
      stageEvents,
    ],
  );
  const liveStatus = deriveLiveNavStatus({
    backlogCount: director.backlogCount,
    connectionState,
    hasCompletedTerminalEvent: terminalEvent?.type === "game_completed",
    hasFailedTerminalEvent: terminalEvent?.type === "game_failed",
    isPaused: director.isPaused,
    runStatus: run?.status ?? "queued",
    speed: director.speed,
  });
  const canResumeRun =
    run?.status === "failed" || terminalEvent?.type === "game_failed";

  return (
    <main className="mobile-page mobile-live-page">
      <h1 className="mobile-sr-only">实时观战</h1>

      {runQuery.isPending ? (
        <p className="mobile-status-banner" role="status">
          正在读取实时对局...
        </p>
      ) : null}
      {runQuery.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法读取实时对局
        </p>
      ) : null}
      {resumeMutation.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法继续对局
        </p>
      ) : null}

      {!run && runQuery.isPending ? (
        <section className="mobile-live-theater" aria-label="实时观战剧场">
          <LiveTheaterTopBar
            connectionState={connectionState}
            liveStatusLabel={liveStatus.label}
            onBack={() => navigateBackToGames(navigate)}
            ruleName="实时对局"
          />
        </section>
      ) : null}

      {run ? (
        <LiveTheater
          canResumeRun={canResumeRun}
          connectionState={connectionState}
          currentEvent={currentEvent}
          director={director}
          godViewState={godViewState}
          liveStatusLabel={liveStatus.label}
          onBack={() => navigateBackToGames(navigate)}
          onResumeRun={() => resumeMutation.mutate(run.session_id)}
          resumeIsPending={resumeMutation.isPending}
          run={run}
          terminalEvent={terminalEvent}
        />
      ) : null}
    </main>
  );
}

type LiveDirectorControlsState = ReturnType<typeof useLiveDirector>;
type GodViewState = ReturnType<typeof deriveGodViewState>;

type LiveTheaterProps = {
  canResumeRun: boolean;
  connectionState: string;
  currentEvent: LiveGameEvent | null;
  director: LiveDirectorControlsState;
  godViewState: GodViewState;
  liveStatusLabel: string;
  onBack: () => void;
  onResumeRun: () => void;
  resumeIsPending: boolean;
  run: GameRun;
  terminalEvent: LiveGameEvent | undefined;
};

function LiveTheater({
  canResumeRun,
  connectionState,
  currentEvent,
  director,
  godViewState,
  liveStatusLabel,
  onBack,
  onResumeRun,
  resumeIsPending,
  run,
  terminalEvent,
}: LiveTheaterProps) {
  const currentPlayer = getCurrentTheaterPlayer(godViewState);
  const { left, right } = splitPlayersForColumns(godViewState.players);

  return (
    <section className="mobile-live-theater" aria-label="实时观战剧场">
      <LiveTheaterTopBar
        connectionState={connectionState}
        liveStatusLabel={liveStatusLabel}
        onBack={onBack}
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
        resumeIsPending={resumeIsPending}
        run={run}
        terminalEvent={terminalEvent}
      />
    </section>
  );
}

type LiveTheaterTopBarProps = {
  connectionState: string;
  liveStatusLabel: string;
  onBack: () => void;
  ruleName: string;
};

function LiveTheaterTopBar({
  connectionState,
  liveStatusLabel,
  onBack,
  ruleName,
}: LiveTheaterTopBarProps) {
  return (
    <header className="mobile-live-theater-top">
      <button
        aria-label="返回对局大厅"
        className="mobile-live-back-button"
        onClick={onBack}
        type="button"
      >
        ‹
      </button>
      <div>
        <strong>{ruleName}</strong>
        <span>{liveStatusLabel}</span>
      </div>
      <span className="mobile-live-connection">
        {connectionLabel(connectionState)}
      </span>
    </header>
  );
}

type LiveSkyBannerProps = {
  dayNightLabel: string;
  phaseLabel: string;
};

function LiveSkyBanner({ dayNightLabel, phaseLabel }: LiveSkyBannerProps) {
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

function LiveSeatColumn({ players, side }: LiveSeatColumnProps) {
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

function LiveSeatAvatar({ player }: LiveSeatAvatarProps) {
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

function LiveCenterStage({
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
  resumeIsPending: boolean;
  run: GameRun;
  terminalEvent: LiveGameEvent | undefined;
};

function LiveTheaterControls({
  canResumeRun,
  currentPlayer,
  director,
  godViewState,
  onResumeRun,
  resumeIsPending,
  run,
  terminalEvent,
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
        {isTerminalRunStatus(run.status) || terminalEvent ? (
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

  return labels[normalized] ?? labels[trimmed] ?? (trimmed.slice(0, 1) || "未知");
}

function isLiveSpeakerDelta(event: LiveGameEvent) {
  return (
    event.type === "model_response_delta" &&
    (event.action === "debate" ||
      event.action === "sheriff_speech" ||
      event.action === "sheriff_pk_speech")
  );
}

function navigateBackToGames(navigate: ReturnType<typeof useNavigate>) {
  const historyState = window.history.state as { idx?: number } | null;
  if (typeof historyState?.idx === "number" && historyState.idx > 0) {
    navigate(-1);
    return;
  }

  navigate("/games");
}

function connectionLabel(state: string) {
  if (state === "open") return "连接正常";
  if (state === "connecting") return "正在连接";
  if (state === "error") return "连接中断";
  if (state === "closed") return "连接已关闭";
  return "等待连接";
}

function isTerminalEvent(event: LiveGameEvent) {
  return event.type === "game_completed" || event.type === "game_failed";
}

function isTerminalRunStatus(status: string | undefined) {
  return status === "completed" || status === "failed";
}
