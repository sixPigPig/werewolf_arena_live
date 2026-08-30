import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import {
  Clapperboard,
  ChevronLeft,
  Crown,
  Eye,
  EyeOff,
  Gavel,
  Moon,
  Radio,
  ShieldAlert,
  Sun,
  Volume2,
} from "lucide-react";

import type {
  AbilityProgress,
  DirectorScene,
  GamePhase,
  GodViewNightResolved,
  GodViewPlayerIdentity,
  LiveState,
  MatchState,
  Presentation,
  PublicPlayerSeat,
  RuntimeProjection,
} from "../contracts";
import {
  awaitingObservationLabel,
  effectiveMatchStatus,
  effectiveWinner,
} from "../runtime";

export type ConnectionState = "idle" | "connecting" | "connected" | "failed";
export type ViewingMode = "director" | "challenge";

type LiveTheaterProps = {
  audioActive: boolean;
  connectionState: ConnectionState;
  directorAbility: AbilityProgress | null;
  directorPlayers: GodViewPlayerIdentity[];
  directorResolution: GodViewNightResolved | null;
  directorScene: DirectorScene | null;
  error: string | null;
  gamePhase: GamePhase | null;
  liveState: LiveState | null;
  matchState: MatchState | null;
  runtimeProjection: RuntimeProjection | null;
  onEnter: () => void;
  onViewingModeChange: (mode: ViewingMode) => void;
  presentation: Presentation | null;
  processLabel: string;
  publicPlayers: PublicPlayerSeat[];
  reactingPlayerIds: ReadonlySet<string>;
  ruleName: string;
  viewingMode: ViewingMode;
};

type StageTone = "opening" | "night" | "day" | "vote" | "terminal" | "failed";

export function LiveTheater({
  audioActive,
  connectionState,
  directorAbility,
  directorPlayers,
  directorResolution,
  directorScene,
  error,
  gamePhase,
  liveState,
  matchState,
  runtimeProjection,
  onEnter,
  onViewingModeChange,
  presentation,
  processLabel,
  publicPlayers,
  reactingPlayerIds,
  ruleName,
  viewingMode,
}: LiveTheaterProps) {
  const tone = stageTone(
    gamePhase,
    liveState,
    matchState,
    runtimeProjection,
    error,
  );
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
  const terminal = terminalPresentation(
    liveState,
    gamePhase,
    matchState,
    runtimeProjection,
    error,
  );
  const stageState = connectionLabel(
    connectionState,
    liveState,
    gamePhase,
    matchState,
    runtimeProjection,
  );
  const activeIdentity =
    activePlayer === null
      ? null
      : directorPlayers.find(
          (player) => player.player_id === activePlayer.player_id,
        ) ?? null;
  const abilityTargetId = directorAbility?.target_player_id ?? null;

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
      data-viewing-mode={viewingMode}
    >
      <header className="mobile-v2-theater-top">
        <Link aria-label="返回对局大厅" className="mobile-v2-theater-back" to="/games">
          <ChevronLeft aria-hidden="true" />
        </Link>
        <div className="mobile-v2-theater-title">
          <strong>{ruleName}</strong>
          <span>
            {phaseTitle(gamePhase, matchState)} ·{" "}
            {viewingMode === "director" ? "导演全知" : "推理挑战"}
          </span>
        </div>
        <div className={`mobile-v2-theater-signal is-${connectionState}`}>
          <Radio aria-hidden="true" />
          <span>{stageState}</span>
        </div>
      </header>

      <StageRhythm gamePhase={gamePhase} matchState={matchState} />

      <div className="mobile-v2-stage-world">
        <div className="mobile-v2-stage-atmosphere" aria-hidden="true" />
        {viewingMode === "director" && connectionState !== "idle" ? (
          <DirectorSceneRibbon
            ability={directorAbility}
            players={directorPlayers}
            resolution={directorResolution}
            scene={directorScene}
          />
        ) : null}
        <CastColumn
          activePlayerId={activePlayer?.player_id ?? null}
          matchState={matchState}
          players={left}
          reactingPlayerIds={reactingPlayerIds}
          side="left"
          targetedPlayerId={abilityTargetId}
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
          targetedPlayerId={abilityTargetId}
        />

        <StageSubtitle
          actorName={actorName}
          actorRole={
            viewingMode === "director" ? activeIdentity?.role ?? null : null
          }
          audioActive={audioActive}
          audioMode={runtimeProjection?.audio_mode ?? "legacy_unknown"}
          presentation={presentation}
          processLabel={processLabel}
        />

        {connectionState === "idle" && !terminal ? (
          <div className="mobile-v2-stage-entry">
            <strong>演出正在此刻发生</strong>
            <p>
              选择你的观赛规则。入场后只接收当前与未来，不会补播。
              {runtimeProjection?.audio_mode === "text_only"
                ? " 本局为纯文本模式，无需音频权限。"
                : runtimeProjection?.audio_mode === "legacy_unknown"
                  ? " 旧记录音频模式未知，将仅接收字幕。"
                : ""}
            </p>
            <ViewingModePicker
              onChange={onViewingModeChange}
              value={viewingMode}
            />
            <button
              className="mobile-v2-stage-button"
              disabled={runtimeProjection === null}
              onClick={onEnter}
              type="button"
            >
              以{viewingMode === "director" ? "导演全知" : "推理挑战"}入场
            </button>
          </div>
        ) : null}

        {connectionState === "connecting" ? (
          <div className="mobile-v2-stage-connecting" role="status">
            <Radio aria-hidden="true" />
            <strong>正在接入这一刻</strong>
            <span>
              {runtimeProjection?.audio_mode === "tts"
                ? "声音解锁后，字幕与 PCM 将从当前 presentation 开始。"
                : runtimeProjection?.audio_mode === "text_only"
                  ? "本局为纯文本模式，将从当前 presentation 接收字幕。"
                  : "旧记录音频模式未知，将仅从当前 presentation 接收字幕。"}
            </span>
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
            (terminal.kind === "interrupted" && liveState !== "canceled") ||
            (terminal.kind === "paused" &&
              liveState === "paused_model_error" &&
              connectionState === "idle") ? (
              <button className="mobile-v2-stage-button is-secondary" onClick={onEnter} type="button">
                {liveState === "paused_model_error"
                  ? "接入并等待恢复"
                  : "重新接入当前直播"}
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
  matchState: MatchState | null;
  players: PublicPlayerSeat[];
  reactingPlayerIds: ReadonlySet<string>;
  side: "left" | "right";
  targetedPlayerId: string | null;
};

function CastColumn({
  activePlayerId,
  matchState,
  players,
  reactingPlayerIds,
  side,
  targetedPlayerId,
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
              targetedPlayerId === player.player_id ? "is-targeted" : "",
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
  actorRole: string | null;
  audioActive: boolean;
  audioMode: RuntimeProjection["audio_mode"];
  presentation: Presentation | null;
  processLabel: string;
};

function StageSubtitle({
  actorName,
  actorRole,
  audioActive,
  audioMode,
  presentation,
  processLabel,
}: StageSubtitleProps) {
  return (
    <footer className="mobile-v2-stage-subtitle" aria-live="polite">
      <div>
        <strong>
          {actorName ?? "实时舞台"}
          {actorRole ? <em>{roleLabel(actorRole)}</em> : null}
        </strong>
        <span className={audioActive ? "is-active" : undefined}>
          <Volume2 aria-hidden="true" />
          {audioMode === "tts"
            ? audioActive
              ? "正在播放"
              : presentation
                ? "等待声音"
                : "候场"
            : audioMode === "text_only"
              ? presentation
                ? "纯文本播出"
                : "纯文本模式"
              : "音频模式未知"}
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

type ViewingModePickerProps = {
  onChange: (mode: ViewingMode) => void;
  value: ViewingMode;
};

function ViewingModePicker({ onChange, value }: ViewingModePickerProps) {
  return (
    <div
      aria-label="选择观赛模式"
      className="mobile-v2-viewing-modes"
      role="group"
    >
      <button
        aria-pressed={value === "director"}
        className={value === "director" ? "is-selected" : undefined}
        onClick={() => onChange("director")}
        type="button"
      >
        <Eye aria-hidden="true" />
        <span>
          <strong>导演全知</strong>
          <small>跟随私密场景，默认推荐</small>
        </span>
      </button>
      <button
        aria-pressed={value === "challenge"}
        className={value === "challenge" ? "is-selected" : undefined}
        onClick={() => onChange("challenge")}
        type="button"
      >
        <EyeOff aria-hidden="true" />
        <span>
          <strong>推理挑战</strong>
          <small>只看公开信息，自己破局</small>
        </span>
      </button>
    </div>
  );
}

type DirectorSceneRibbonProps = {
  ability: AbilityProgress | null;
  players: GodViewPlayerIdentity[];
  resolution: GodViewNightResolved | null;
  scene: DirectorScene | null;
};

function DirectorSceneRibbon({
  ability,
  players,
  resolution,
  scene,
}: DirectorSceneRibbonProps) {
  return (
    <aside className="mobile-v2-director-scene" aria-live="polite">
      <Clapperboard aria-hidden="true" />
      <div>
        <span>导演镜头</span>
        <strong>{sceneLabel(scene)}</strong>
        <small>{directorSceneSummary(ability, resolution, players, scene)}</small>
      </div>
    </aside>
  );
}

function directorSceneSummary(
  ability: AbilityProgress | null,
  resolution: GodViewNightResolved | null,
  players: GodViewPlayerIdentity[],
  scene: DirectorScene | null,
): string {
  if (resolution?.deaths.length) {
    return `夜间结算：${resolution.deaths
      .map((death) => playerName(players, death.player_id))
      .join("、")}`;
  }
  if (resolution?.attack_prevented_by) {
    return `致命行动被${playerName(players, resolution.attack_prevented_by)}阻止`;
  }
  if (ability) {
    const actor = ability.actor_player_id
      ? playerName(players, ability.actor_player_id)
      : roleLabel(scene?.ability_id ?? "");
    const target = ability.target_player_id
      ? playerName(players, ability.target_player_id)
      : "未选择目标";
    return `${actor} → ${target}`;
  }
  if (scene?.actor_player_id) {
    const actor = players.find(
      (player) => player.player_id === scene.actor_player_id,
    );
    return actor
      ? `${actor.display_name} · ${roleLabel(actor.role)}正在行动`
      : "私密行动正在此刻发生";
  }
  return scene?.scene_kind === "public_stage"
    ? "所有观众正在观看同一个公开舞台"
    : "镜头将跟随当前关键行动";
}

function playerName(
  players: GodViewPlayerIdentity[],
  playerId: string,
): string {
  return (
    players.find((player) => player.player_id === playerId)?.display_name ??
    playerId
  );
}

function sceneLabel(scene: DirectorScene | null): string {
  if (!scene) return "等待下一幕";
  return {
    opening: "开幕舞台",
    public_stage: "公共舞台",
    nightfall: "夜幕转场",
    werewolves: "狼人房间",
    guard: "守卫行动",
    seer: "预言家查验",
    witch: "女巫用药",
    hunter: "猎人反击",
    dawn: "黎明公布",
    terminal: "终局舞台",
  }[scene.scene_kind];
}

function roleLabel(role: string): string {
  return (
    {
      werewolf: "狼人",
      villager: "平民",
      seer: "预言家",
      witch: "女巫",
      guard: "守卫",
      hunter: "猎人",
      judge: "法官",
    }[role] ?? role
  );
}

function StageRhythm({
  gamePhase,
  matchState,
}: Pick<LiveTheaterProps, "gamePhase" | "matchState">) {
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

function splitPlayers(players: PublicPlayerSeat[]) {
  const ordered = [...players].sort((left, right) => left.seat - right.seat);
  const middle = Math.ceil(ordered.length / 2);
  return { left: ordered.slice(0, middle), right: ordered.slice(middle) };
}

function phaseGroup(
  phase: GamePhase | null,
): "opening" | "night" | "day" | "terminal" {
  if (phase?.phase_state === "game_completed") return "terminal";
  if (phase?.phase_id === "first_night" || phase?.phase_id.startsWith("night_")) {
    return "night";
  }
  if (phase?.phase_id.startsWith("day_")) return "day";
  return "opening";
}

function stageTone(
  phase: GamePhase | null,
  liveState: LiveState | null,
  matchState: MatchState | null,
  runtime: RuntimeProjection | null,
  error: string | null,
): StageTone {
  if (
    effectiveMatchStatus(runtime, phase, matchState, liveState) === "completed"
  ) {
    return "terminal";
  }
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
  if (liveState === "paused_model_error") return "terminal";
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
  phase: GamePhase | null,
  matchState: MatchState | null,
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
  connectionState: ConnectionState,
  liveState: LiveState | null,
  phase: GamePhase | null,
  matchState: MatchState | null,
  runtime: RuntimeProjection | null,
): string {
  const matchStatus = effectiveMatchStatus(runtime, phase, matchState, liveState);
  if (matchStatus === "completed") return "对局已完成";
  if (liveState === "canceled") return "运营已中断";
  if (liveState === "awaiting_observation") {
    return awaitingObservationLabel(runtime);
  }
  if (liveState === "paused_model_error") return "等待运营恢复";
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
  liveState: LiveState | null,
  phase: GamePhase | null,
  matchState: MatchState | null,
  runtime: RuntimeProjection | null,
  error: string | null,
): { kind: "complete" | "paused" | "interrupted" | "failed"; title: string; description: string } | null {
  const matchStatus = effectiveMatchStatus(runtime, phase, matchState, liveState);
  const winner = effectiveWinner(runtime, matchState);
  if (matchStatus === "completed" && winner) {
    return {
      kind: "complete",
      title: winner === "villagers" ? "好人阵营获胜" : "狼人阵营获胜",
      description: "胜负已经权威结算，本局实时舞台正式落幕。",
    };
  }
  if (liveState === "canceled") {
    return {
      kind: "interrupted",
      title: "本局已由管理员终止",
      description: "当前字幕与语音已经停止，不会追播或恢复已打断的内容。",
    };
  }
  if (liveState === "paused_model_error") {
    return {
      kind: "paused",
      title: "模型服务暂时异常",
      description: "当前动作已安全冻结；运营恢复后会从同一动作继续，无需刷新页面。",
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
  return {
    kind: "paused",
    title: awaitingObservationLabel(runtime),
    description:
      runtime?.execution_state === "owned"
        ? "比赛尚未形成权威胜负，执行器仍在等待观察或播放确认。"
        : "比赛尚未形成权威胜负；已播内容已经保存，这里不会补播。",
  };
}
