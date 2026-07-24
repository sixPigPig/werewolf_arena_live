import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import {
  ChevronLeft,
  Crown,
  Gavel,
  Moon,
  Radio,
  ShieldAlert,
  Sun,
  Volume2,
} from "lucide-react";

import type {
  V2GamePhase,
  V2LiveState,
  V2MatchState,
  V2Presentation,
  V2PublicPlayerSeat,
} from "../contracts";

export type V2ConnectionState = "idle" | "connecting" | "connected" | "failed";

type V2LiveTheaterProps = {
  audioActive: boolean;
  connectionState: V2ConnectionState;
  error: string | null;
  gamePhase: V2GamePhase | null;
  liveState: V2LiveState | null;
  matchState: V2MatchState | null;
  onEnter: () => void;
  presentation: V2Presentation | null;
  processLabel: string;
  publicPlayers: V2PublicPlayerSeat[];
  reactingPlayerIds: ReadonlySet<string>;
  ruleName: string;
};

type StageTone = "opening" | "night" | "day" | "vote" | "terminal" | "failed";

export function V2LiveTheater({
  audioActive,
  connectionState,
  error,
  gamePhase,
  liveState,
  matchState,
  onEnter,
  presentation,
  processLabel,
  publicPlayers,
  reactingPlayerIds,
  ruleName,
}: V2LiveTheaterProps) {
  const tone = stageTone(gamePhase, liveState, error);
  const activePlayer =
    presentation?.actor.kind === "player"
      ? publicPlayers.find((player) => player.player_id === presentation.actor.id) ?? null
      : null;
  const actorName = presentation
    ? presentation.actor.kind === "judge"
      ? "法官"
      : activePlayer?.display_name ?? presentation.actor.id
    : null;
  const { left, right } = splitPlayers(publicPlayers);
  const terminal = terminalPresentation(liveState, matchState, error);
  const stageState = connectionLabel(connectionState, liveState);

  return (
    <section
      className={[
        "mobile-v2-theater",
        `is-${tone}`,
        presentation ? "has-presentation" : "",
        audioActive ? "is-audio-active" : "",
        terminal ? "has-terminal" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label="Live V2 实时演出舞台"
      data-connection-state={connectionState}
      data-live-state={liveState ?? "unknown"}
    >
      <header className="mobile-v2-theater-top">
        <Link aria-label="返回对局大厅" className="mobile-v2-theater-back" to="/games">
          <ChevronLeft aria-hidden="true" />
        </Link>
        <div className="mobile-v2-theater-title">
          <strong>{ruleName}</strong>
          <span>{phaseTitle(gamePhase, matchState)}</span>
        </div>
        <div className={`mobile-v2-theater-signal is-${connectionState}`}>
          <Radio aria-hidden="true" />
          <span>{stageState}</span>
        </div>
      </header>

      <StageRhythm gamePhase={gamePhase} matchState={matchState} />

      <div className="mobile-v2-stage-world">
        <div className="mobile-v2-stage-atmosphere" aria-hidden="true" />
        <CastColumn
          activePlayerId={activePlayer?.player_id ?? null}
          matchState={matchState}
          players={left}
          reactingPlayerIds={reactingPlayerIds}
          side="left"
        />

        <article
          aria-label={actorName ?? "当前舞台焦点"}
          className={[
            "mobile-v2-stage-focus",
            presentation ? "is-open" : "is-waiting",
            presentation?.actor.kind === "player" ? "is-player" : "is-judge",
          ].join(" ")}
          role="region"
        >
          <div className="mobile-v2-stage-spotlight" aria-hidden="true" />
          <div className="mobile-v2-focus-portrait">
            {activePlayer?.avatar_url ? (
              <img alt="" src={activePlayer.avatar_url} />
            ) : (
              <Gavel aria-hidden="true" className="mobile-v2-judge-mark" />
            )}
          </div>
        </article>

        <CastColumn
          activePlayerId={activePlayer?.player_id ?? null}
          matchState={matchState}
          players={right}
          reactingPlayerIds={reactingPlayerIds}
          side="right"
        />

        <StageSubtitle
          actorName={actorName}
          audioActive={audioActive}
          presentation={presentation}
          processLabel={processLabel}
        />

        {connectionState === "idle" && !terminal ? (
          <div className="mobile-v2-stage-entry">
            <strong>演出正在此刻发生</strong>
            <p>入场后只接收当前与未来内容，不会补播已经结束的片段。</p>
            <button className="mobile-v2-stage-button" onClick={onEnter} type="button">
              进入实时观赛
            </button>
          </div>
        ) : null}

        {connectionState === "connecting" ? (
          <div className="mobile-v2-stage-connecting" role="status">
            <Radio aria-hidden="true" />
            <strong>正在接入这一刻</strong>
            <span>声音解锁后，字幕与 PCM 将从当前 presentation 开始。</span>
          </div>
        ) : null}

        {terminal ? (
          <div
            className={`mobile-v2-stage-terminal is-${terminal.kind}`}
            role={terminal.kind === "failed" || terminal.kind === "interrupted" ? "alert" : "status"}
          >
            {terminal.kind === "failed" || terminal.kind === "interrupted" ? (
              <ShieldAlert aria-hidden="true" />
            ) : (
              <Gavel aria-hidden="true" />
            )}
            <strong>{terminal.title}</strong>
            <p>{terminal.description}</p>
            {terminal.kind === "failed" ||
            (terminal.kind === "interrupted" && liveState !== "canceled") ? (
              <button className="mobile-v2-stage-button is-secondary" onClick={onEnter} type="button">
                重新接入当前直播
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

type CastColumnProps = {
  activePlayerId: string | null;
  matchState: V2MatchState | null;
  players: V2PublicPlayerSeat[];
  reactingPlayerIds: ReadonlySet<string>;
  side: "left" | "right";
};

function CastColumn({
  activePlayerId,
  matchState,
  players,
  reactingPlayerIds,
  side,
}: CastColumnProps) {
  return (
    <ol className={`mobile-v2-cast mobile-v2-cast-${side}`} aria-label={`${side === "left" ? "左" : "右"}侧玩家站位`}>
      {players.map((player, index) => {
        const isSheriff =
          matchState?.sheriff_badge_state === "held" &&
          matchState.sheriff_player_id === player.player_id;
        const style = {
          "--mobile-v2-cast-delay": `${index * 100}ms`,
          "--mobile-v2-idle-delay": `${(player.seat % 4) * -0.7}s`,
        } as CSSProperties;
        return (
          <li
            key={player.player_id}
            aria-label={`${player.seat}号 ${player.display_name}${player.alive ? "" : "，已公开死亡"}${isSheriff ? "，警长" : ""}`}
            className={[
              "mobile-v2-cast-member",
              activePlayerId === player.player_id ? "is-speaking" : "",
              player.alive ? "is-alive" : "is-dead",
              reactingPlayerIds.has(player.player_id) ? "is-reacting" : "",
              isSheriff ? "is-sheriff" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            style={style}
          >
            <span className="mobile-v2-cast-frame" aria-hidden="true">
              {player.avatar_url ? <img alt="" src={player.avatar_url} /> : null}
              <span className="mobile-v2-cast-seat">{player.seat}</span>
              {isSheriff ? <Crown className="mobile-v2-cast-crown" /> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

type StageSubtitleProps = {
  actorName: string | null;
  audioActive: boolean;
  presentation: V2Presentation | null;
  processLabel: string;
};

function StageSubtitle({
  actorName,
  audioActive,
  presentation,
  processLabel,
}: StageSubtitleProps) {
  return (
    <footer className="mobile-v2-stage-subtitle" aria-live="polite">
      <div>
        <strong>{actorName ?? "实时舞台"}</strong>
        <span className={audioActive ? "is-active" : undefined}>
          <Volume2 aria-hidden="true" />
          {audioActive ? "正在播放" : presentation ? "等待声音" : "候场"}
        </span>
      </div>
      <blockquote>
        {presentation?.subtitle_text ||
          (presentation ? "镜头已打开，正在等待第一句实时字幕…" : processLabel)}
      </blockquote>
      <small>{processLabel}</small>
    </footer>
  );
}

function StageRhythm({
  gamePhase,
  matchState,
}: Pick<V2LiveTheaterProps, "gamePhase" | "matchState">) {
  const current = phaseGroup(gamePhase);
  return (
    <div className="mobile-v2-stage-rhythm" aria-label="当前回合节奏">
      <span className={rhythmClass("opening", current)}>序幕</span>
      <span className={rhythmClass("night", current)}>
        <Moon aria-hidden="true" />
        第 {matchState?.round_no ?? 1} 夜
      </span>
      <span className={rhythmClass("day", current)}>
        <Sun aria-hidden="true" />
        第 {matchState?.round_no ?? 1} 天
      </span>
    </div>
  );
}

function rhythmClass(
  target: "opening" | "night" | "day",
  current: "opening" | "night" | "day" | "terminal",
): string {
  const order = { opening: 0, night: 1, day: 2, terminal: 3 };
  if (target === current) return "is-current";
  return order[target] < order[current] ? "is-complete" : "";
}

function splitPlayers(players: V2PublicPlayerSeat[]) {
  const ordered = [...players].sort((left, right) => left.seat - right.seat);
  const middle = Math.ceil(ordered.length / 2);
  return { left: ordered.slice(0, middle), right: ordered.slice(middle) };
}

function phaseGroup(
  phase: V2GamePhase | null,
): "opening" | "night" | "day" | "terminal" {
  if (phase?.phase_state === "game_completed") return "terminal";
  if (phase?.phase_id === "first_night" || phase?.phase_id.startsWith("night_")) {
    return "night";
  }
  if (phase?.phase_id.startsWith("day_")) return "day";
  return "opening";
}

function stageTone(
  phase: V2GamePhase | null,
  liveState: V2LiveState | null,
  error: string | null,
): StageTone {
  if (
    error ||
    liveState === "canceled" ||
    liveState === "failed" ||
    phase?.phase_state === "failed"
  ) {
    return "failed";
  }
  if (liveState === "awaiting_observation" || phase?.phase_state === "game_completed") {
    return "terminal";
  }
  if (
    phase?.phase_state === "sheriff_election_open" ||
    phase?.phase_state === "public_discussion_open"
  ) {
    return "vote";
  }
  const group = phaseGroup(phase);
  return group === "terminal" ? "terminal" : group;
}

function phaseTitle(
  phase: V2GamePhase | null,
  matchState: V2MatchState | null,
): string {
  if (phase?.phase_state === "game_completed") return "终局";
  if (phase?.phase_state === "sheriff_election_open") return "警长竞选";
  if (phase?.phase_state === "public_discussion_open") return "公开讨论";
  if (phase?.phase_id === "first_night" || phase?.phase_id.startsWith("night_")) {
    return `第 ${matchState?.round_no ?? 1} 夜`;
  }
  if (phase?.phase_id.startsWith("day_")) return `第 ${matchState?.round_no ?? 1} 天`;
  return "序幕";
}

function connectionLabel(
  connectionState: V2ConnectionState,
  liveState: V2LiveState | null,
): string {
  if (liveState === "canceled") return "运营已中断";
  if (liveState === "awaiting_observation") return "已停播";
  if (liveState === "failed") return "演出异常";
  if (connectionState === "idle") return "未入场";
  if (connectionState === "connecting") return "连接中";
  if (connectionState === "failed") return "连接中断";
  if (liveState === "waiting_to_start") return "等待开幕";
  if (liveState === "ready") return "实时待机";
  if (liveState === "generating") return "动作生成中";
  if (liveState === "broadcasting") return "正在播出";
  if (liveState === "finalizing") return "演出收束中";
  return "已连接";
}

function terminalPresentation(
  liveState: V2LiveState | null,
  matchState: V2MatchState | null,
  error: string | null,
): { kind: "complete" | "paused" | "interrupted" | "failed"; title: string; description: string } | null {
  if (liveState === "canceled") {
    return {
      kind: "interrupted",
      title: "本局已由管理员终止",
      description: "当前字幕与语音已经停止，不会追播或恢复已打断的内容。",
    };
  }
  if (error) {
    const interrupted = /operator|运营|人工|中断|取消|cancel|stop/i.test(error);
    return interrupted
      ? {
          kind: "interrupted",
          title: "运营已中断本局",
          description: "舞台已经停下；重新接入仍只会接收当前和未来内容。",
        }
      : {
          kind: "failed",
          title: "实时演出未能继续",
          description: error,
        };
  }
  if (liveState === "failed") {
    return {
      kind: "failed",
      title: "实时演出未能继续",
      description: "本次实时动作已经失败；重新接入仍只接收当前和未来内容。",
    };
  }
  if (liveState !== "awaiting_observation") return null;
  if (matchState?.winner) {
    return {
      kind: "complete",
      title: matchState.winner === "villagers" ? "好人阵营获胜" : "狼人阵营获胜",
      description: "胜负已经结算，本局实时舞台正式落幕。",
    };
  }
  return {
    kind: "paused",
    title: "直播已停在当前时刻",
    description: "已播语音已经保存；这里不会补播已经结束的片段。",
  };
}
