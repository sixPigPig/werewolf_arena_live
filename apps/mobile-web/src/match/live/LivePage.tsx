import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import {
  fetchLiveSnapshot,
  resolveDirectorWebSocketUrl,
  resolveWebSocketUrl,
} from "../api";
import {
  decodeAudioFrame,
  parseServerMessage,
  type AbilityProgress,
  type DirectorScene,
  type DayProgress,
  type GamePhase,
  type GodViewNightResolved,
  type GodViewPlayerIdentity,
  type LiveState,
  type MatchState,
  type Presentation,
  type PublicPlayerSeat,
  type PublicRoleAssignmentStatus,
  type PublicRuleSnapshot,
  type RuntimeProjection,
} from "../contracts";
import { PcmPlayer } from "../PcmPlayer";
import {
  awaitingObservationLabel,
  effectiveMatchStatus,
  effectiveWinner,
  runtimeFromSnapshot,
} from "../runtime";
import {
  LiveTheater,
  type ConnectionState,
  type ViewingMode,
} from "./LiveTheater";

type RosterState = "loading" | "ready" | "failed";
type NightProgress =
  | "night_started"
  | "actions_in_progress"
  | "night_resolved"
  | "dawn_announced"
  | null;

export function LivePage() {
  const { gameId = "" } = useParams();
  const socketRef = useRef<WebSocket | null>(null);
  const playerRef = useRef<PcmPlayer | null>(null);
  const presentationRef = useRef<Presentation | null>(null);
  const terminalRef = useRef(false);
  const audioPulseTimerRef = useRef<number | null>(null);
  const deathReactionTimerRef = useRef<number | null>(null);
  const playbackCursorRef = useRef(0);
  const pendingRevealsRef = useRef<Array<{ seq: number; apply: () => void }>>(
    [],
  );

  const applyWhenRevealed = (seq: number, apply: () => void) => {
    if (seq <= playbackCursorRef.current) {
      apply();
      return;
    }
    pendingRevealsRef.current.push({ seq, apply });
  };

  const advancePlaybackCursor = (cursor: number) => {
    if (cursor < playbackCursorRef.current) return;
    playbackCursorRef.current = cursor;
    const remaining: Array<{ seq: number; apply: () => void }> = [];
    for (const item of pendingRevealsRef.current) {
      if (item.seq <= playbackCursorRef.current) {
        item.apply();
      } else {
        remaining.push(item);
      }
    }
    pendingRevealsRef.current = remaining;
  };
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("idle");
  const [liveState, setLiveState] = useState<LiveState | null>(null);
  const [gamePhase, setGamePhase] = useState<GamePhase | null>(null);
  const [matchState, setMatchState] = useState<MatchState | null>(null);
  const [runtimeProjection, setRuntimeProjection] =
    useState<RuntimeProjection | null>(null);
  const [presentation, setPresentation] = useState<Presentation | null>(null);
  const [viewingMode, setViewingMode] = useState<ViewingMode>("director");
  const [publicPlayers, setPublicPlayers] = useState<PublicPlayerSeat[]>([]);
  const [directorPlayers, setDirectorPlayers] = useState<
    GodViewPlayerIdentity[]
  >([]);
  const [directorScene, setDirectorScene] = useState<DirectorScene | null>(null);
  const [directorAbility, setDirectorAbility] =
    useState<AbilityProgress | null>(null);
  const [directorResolution, setDirectorResolution] =
    useState<GodViewNightResolved | null>(null);
  const [publicRule, setPublicRule] = useState<PublicRuleSnapshot | null>(null);
  const [roleAssignment, setRoleAssignment] =
    useState<PublicRoleAssignmentStatus | null>(null);
  const [rosterState, setRosterState] = useState<RosterState>("loading");
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nightProgress, setNightProgress] = useState<NightProgress>(null);
  const [dayProgress, setDayProgress] = useState<DayProgress | null>(null);
  const [audioActive, setAudioActive] = useState(false);
  const [reactingPlayerIds, setReactingPlayerIds] = useState<Set<string>>(
    () => new Set(),
  );

  useEffect(() => {
    let active = true;
    void fetchLiveSnapshot(gameId)
      .then((snapshot) => {
        if (!active) return;
        setPublicRule(snapshot.public_rule);
        setPublicPlayers(snapshot.public_players);
        setRoleAssignment(snapshot.public_role_assignment);
        playbackCursorRef.current = snapshot.playback_cursor;
        pendingRevealsRef.current = [];
        setGamePhase(snapshot.game_phase);
        setMatchState(snapshot.match_state);
        setLiveState(snapshot.live_state);
        setRuntimeProjection(runtimeFromSnapshot(snapshot));
        setRosterState("ready");
      })
      .catch((reason) => {
        if (!active) return;
        setRosterState("failed");
        setRosterError(
          reason instanceof Error ? reason.message : "无法读取本局座位快照",
        );
      });
    return () => {
      active = false;
    };
  }, [gameId]);

  useEffect(() => {
    return () => {
      terminalRef.current = true;
      socketRef.current?.close();
      if (audioPulseTimerRef.current !== null) {
        window.clearTimeout(audioPulseTimerRef.current);
      }
      if (deathReactionTimerRef.current !== null) {
        window.clearTimeout(deathReactionTimerRef.current);
      }
      const player = playerRef.current;
      playerRef.current = null;
      if (player) void player.close();
    };
  }, []);

  function revealPublicDeaths(playerIds: string[]) {
    const dead = new Set(playerIds);
    setPublicPlayers((current) =>
      current.map((player) =>
        dead.has(player.player_id) ? { ...player, alive: false } : player,
      ),
    );
    setReactingPlayerIds(dead);
    if (deathReactionTimerRef.current !== null) {
      window.clearTimeout(deathReactionTimerRef.current);
    }
    deathReactionTimerRef.current = window.setTimeout(() => {
      setReactingPlayerIds(new Set());
      deathReactionTimerRef.current = null;
    }, 1800);
  }

  function showAudioPulse() {
    setAudioActive(true);
    if (audioPulseTimerRef.current !== null) {
      window.clearTimeout(audioPulseTimerRef.current);
    }
    audioPulseTimerRef.current = window.setTimeout(() => {
      setAudioActive(false);
      audioPulseTimerRef.current = null;
    }, 420);
  }

  async function enterLive() {
    socketRef.current?.close();
    if (playerRef.current) await playerRef.current.close();
    terminalRef.current = false;
    setAudioActive(false);
    setError(null);
    setConnectionState("connecting");
    presentationRef.current = null;
    setPresentation(null);
    setDirectorAbility(null);
    setDirectorResolution(null);
    try {
      const enteredMode = viewingMode;
      const audioEnabled = runtimeProjection?.audio_mode === "tts";
      const player = audioEnabled ? new PcmPlayer() : null;
      if (player) await player.unlock();
      playerRef.current = player;
      const socket = new WebSocket(
        enteredMode === "director"
          ? resolveDirectorWebSocketUrl(gameId)
          : resolveWebSocketUrl(gameId),
      );
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;
      let readySent = false;
      socket.onopen = () => setConnectionState("connected");
      socket.onmessage = (event) => {
        try {
          if (typeof event.data === "string") {
            const message = parseServerMessage(event.data);
            if (message.type === "director.live_snapshot") {
              if (enteredMode !== "director") {
                throw new Error("推理挑战连接收到导演投影，连接已关闭");
              }
              playbackCursorRef.current = message.playback_cursor;
              pendingRevealsRef.current = [];
              setLiveState(message.live_state);
              setGamePhase(message.game_phase);
              setMatchState(message.match_state);
              setRuntimeProjection(runtimeFromSnapshot(message));
              setPublicRule(message.rule);
              setDirectorPlayers(message.players);
              setPublicPlayers(message.players.map(toPublicPlayer));
              setRoleAssignment({
                state: "sealed",
                assigned_count: message.players.length,
              });
              setDirectorScene(message.current_scene);
              setRosterState("ready");
              setRosterError(null);
              if (message.live_state === "canceled") {
                terminalRef.current = true;
                presentationRef.current = null;
                setPresentation(null);
                setAudioActive(false);
                player?.stop();
                socket.close();
                return;
              }
              const currentPresentation = normalizePresentation(
                message.current_presentation,
              );
              presentationRef.current = currentPresentation;
              setPresentation(currentPresentation);
              if (currentPresentation) {
                player?.begin(currentPresentation);
              }
              if (!readySent) {
                socket.send(
                  JSON.stringify({
                    protocol_version: 1,
                    type: "director.ready",
                    ...(audioEnabled
                      ? {
                          audio: {
                            encoding: "pcm_s16le",
                            sample_rate: 24000,
                            channels: 1,
                          },
                        }
                      : {}),
                  }),
                );
                readySent = true;
              }
              if (message.live_state === "failed") {
                terminalRef.current = true;
              }
              return;
            }
            if (message.type === "live.snapshot") {
              if (enteredMode !== "challenge") {
                throw new Error("导演直播连接收到推理挑战投影，连接已关闭");
              }
              playbackCursorRef.current = message.playback_cursor;
              pendingRevealsRef.current = [];
              setLiveState(message.live_state);
              setGamePhase(message.game_phase);
              setMatchState(message.match_state);
              setRuntimeProjection(runtimeFromSnapshot(message));
              setPublicRule(message.public_rule);
              setPublicPlayers(message.public_players);
              setRoleAssignment(message.public_role_assignment);
              setDirectorPlayers([]);
              setDirectorScene(null);
              setRosterState("ready");
              setRosterError(null);
              if (message.live_state === "canceled") {
                terminalRef.current = true;
                presentationRef.current = null;
                setPresentation(null);
                setAudioActive(false);
                player?.stop();
                socket.close();
                return;
              }
              const currentPresentation = normalizePresentation(
                message.current_presentation,
              );
              presentationRef.current = currentPresentation;
              setPresentation(currentPresentation);
              if (currentPresentation) {
                player?.begin(currentPresentation);
              }
              if (!readySent) {
                socket.send(
                  JSON.stringify({
                    protocol_version: 1,
                    type: "client.ready",
                    ...(audioEnabled
                      ? {
                          audio: {
                            encoding: "pcm_s16le",
                            sample_rate: 24000,
                            channels: 1,
                          },
                        }
                      : {}),
                  }),
                );
                readySent = true;
              }
              if (message.live_state === "failed") {
                terminalRef.current = true;
              }
              return;
            }
            if (message.type === "god_view.live_snapshot") {
              throw new Error("普通直播收到上帝分析台投影，连接已关闭");
            }
            if (message.type === "director.scene_changed") {
              if (enteredMode !== "director") {
                throw new Error("推理挑战连接收到导演场景，连接已关闭");
              }
              setDirectorScene(message);
              setDirectorAbility(null);
              setDirectorResolution(null);
              return;
            }
            if (message.type === "live.state_changed") {
              setLiveState(message.live_state);
              if (message.live_state === "canceled") {
                terminalRef.current = true;
                presentationRef.current = null;
                setPresentation(null);
                setAudioActive(false);
                player?.stop();
                setRuntimeProjection((current) =>
                  current
                    ? { ...current, match_status: "canceled", execution_state: "stopped" }
                    : current,
                );
                socket.close();
                return;
              }
              if (message.live_state === "failed") {
                terminalRef.current = true;
                setAudioActive(false);
                player?.stop();
                setRuntimeProjection((current) =>
                  current?.match_status === "completed"
                    ? current
                    : current
                      ? { ...current, match_status: "failed", execution_state: "stopped" }
                      : current,
                );
                setError(message.reason ?? "V2 实时动作失败");
              }
              return;
            }
            if (message.type === "game.phase_changed") {
              applyWhenRevealed(message.reveal_presentation_seq, () => {
                setGamePhase({
                  phase_seq: message.phase_seq,
                  phase_id: message.phase_id,
                  phase_state: message.phase_state,
                });
              });
              return;
            }
            if (message.type === "night.progress_changed") {
              setNightProgress(message.stage);
              return;
            }
            if (message.type === "day.progress_changed") {
              applyWhenRevealed(message.reveal_presentation_seq, () => {
                setDayProgress(message);
              });
              return;
            }
            if (message.type === "match.state_changed") {
              applyWhenRevealed(message.reveal_presentation_seq, () => {
                setMatchState({
                  round_no: message.round_no,
                  sheriff_player_id: message.sheriff_player_id,
                  sheriff_badge_state: message.sheriff_badge_state,
                  winner: message.winner,
                });
                setRuntimeProjection((current) =>
                  current
                    ? {
                        ...current,
                        winner: message.winner,
                      }
                    : current,
                );
              });
              return;
            }
            if (message.type === "player.state_changed") {
              if (enteredMode === "challenge" && message.cause !== null) {
                throw new Error("普通观众连接收到私密死亡原因，连接已关闭");
              }
              applyWhenRevealed(message.reveal_presentation_seq, () => {
                if (message.alive) {
                  setPublicPlayers((current) =>
                    current.map((player) =>
                      player.player_id === message.player_id
                        ? { ...player, alive: true }
                        : player,
                    ),
                  );
                } else {
                  revealPublicDeaths([message.player_id]);
                }
              });
              return;
            }
            if (message.type === "ability.progress_changed") {
              if (enteredMode === "challenge") {
                throw new Error("推理挑战连接收到私密能力投影，连接已关闭");
              }
              setDirectorAbility(message);
              return;
            }
            if (message.type === "dawn.result_announced") {
              applyWhenRevealed(message.reveal_presentation_seq, () => {
                revealPublicDeaths(message.dead_player_ids);
              });
              return;
            }
            if (message.type === "god_view.night_resolved") {
              if (enteredMode === "challenge") {
                throw new Error("推理挑战连接收到上帝视角结算，连接已关闭");
              }
              setDirectorResolution(message);
              return;
            }
            if (message.type === "presentation.opened") {
              const current: Presentation = {
                action_id: message.action_id,
                presentation_seq: message.presentation_seq,
                presentation_id: message.presentation_id,
                phase_id: message.phase_id,
                actor: message.actor,
                speech_id: message.speech_id,
                segment_index: 0,
                subtitle_text: "",
                join_sample_cursor: 0,
              };
              presentationRef.current = current;
              setPresentation(current);
              setAudioActive(false);
              player?.begin(current);
              return;
            }
            if (message.type === "speech.segment_committed") {
              const current = presentationRef.current;
              if (
                !current ||
                current.action_id !== message.action_id ||
                current.presentation_id !== message.presentation_id ||
                current.speech_id !== message.speech_id
              ) {
                throw new Error("V2 字幕归属与当前展示不一致");
              }
              const committed = {
                ...current,
                segment_index: message.segment_index,
                subtitle_text: displaySubtitleText(message.text),
              };
              presentationRef.current = committed;
              setPresentation(committed);
              return;
            }
            if (message.type === "presentation.failed") {
              if (
                presentationRef.current?.presentation_id ===
                message.presentation_id
              ) {
                setAudioActive(false);
                player?.stop();
                presentationRef.current = null;
                if (audioEnabled) {
                  setPresentation(null);
                }
              }
              advancePlaybackCursor(message.presentation_seq);
              return;
            }
            if (message.type === "presentation.closed") {
              if (
                presentationRef.current?.presentation_id ===
                message.presentation_id
              ) {
                setAudioActive(false);
                player?.stop();
                presentationRef.current = null;
                if (audioEnabled) {
                  setPresentation(null);
                }
              }
              advancePlaybackCursor(message.playback_cursor);
              return;
            }
          }
          if (!(event.data instanceof ArrayBuffer)) {
            throw new Error("V2 收到未知二进制类型");
          }
          if (!player) {
            throw new Error("未确认启用语音的对局收到意外音频帧");
          }
          player.push(decodeAudioFrame(event.data));
          showAudioPulse();
        } catch (reason) {
          terminalRef.current = true;
          setAudioActive(false);
          player?.stop();
          setLiveState("failed");
          setConnectionState("failed");
          setError(reason instanceof Error ? reason.message : "V2 实时协议错误");
          socket.close();
        }
      };
      socket.onerror = () => {
        setConnectionState("failed");
        setError("V2 WebSocket 连接失败");
      };
      socket.onclose = () => {
        if (!terminalRef.current) {
          setConnectionState("failed");
          setAudioActive(false);
          setError("V2 实时连接已断开；重新进入只会接收当前和未来内容");
        }
      };
    } catch (reason) {
      setConnectionState("failed");
      setError(reason instanceof Error ? reason.message : "无法启动 V2 实时直播");
    }
  }

  const processLabel = liveProcessLabel(
    connectionState,
    liveState,
    gamePhase,
    matchState,
    nightProgress,
    dayProgress,
    viewingMode,
    directorScene,
    runtimeProjection,
    presentation !== null,
  );

  return (
    <main
      className={[
        "mobile-page",
        "mobile-live-v2-page",
        isNightPhase(gamePhase) ? "is-night" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <h1 className="mobile-sr-only">Live V2</h1>

      <LiveTheater
        audioActive={audioActive}
        connectionState={connectionState}
        error={error}
        gamePhase={gamePhase}
        liveState={liveState}
        matchState={matchState}
        runtimeProjection={runtimeProjection}
        directorAbility={directorAbility}
        directorPlayers={directorPlayers}
        directorResolution={directorResolution}
        directorScene={directorScene}
        onEnter={() => void enterLive()}
        onViewingModeChange={setViewingMode}
        presentation={presentation}
        processLabel={processLabel}
        publicPlayers={publicPlayers}
        reactingPlayerIds={reactingPlayerIds}
        ruleName={publicRule?.name ?? "Live V2"}
        viewingMode={viewingMode}
      />

      <details className="mobile-v2-live-details">
        <summary>
          <span>
            <strong>本局资料</strong>
            <small>规则与公开座位</small>
          </span>
          <b>{rosterState === "ready" ? `${publicPlayers.length} 人` : "读取中"}</b>
        </summary>

        <div className="mobile-v2-live-details-body">
          {roleAssignment ? (
            <p className="mobile-v2-privacy-seal">
              <strong>
                {roleAssignment.state === "sealed"
                  ? `身份已私密封存 · ${roleAssignment.assigned_count} 人`
                  : "身份尚未分配"}
              </strong>
              <span>
                {viewingMode === "director"
                  ? "导演全知会在对应私密场景按需展示身份、发言和行动；角色之间仍严格隔离。"
                  : "推理挑战不会展示座位身份、私密行动或死亡原因。"}
              </span>
            </p>
          ) : null}

          <section aria-labelledby="v2-rule-heading">
            <header>
              <h2 id="v2-rule-heading">{publicRule?.name ?? "规则快照"}</h2>
              {publicRule ? <span>v{publicRule.version}</span> : null}
            </header>
            {publicRule ? (
              <>
                <p>
                  {publicRule.player_count} 位玩家 · 最多 {publicRule.max_rounds} 轮
                </p>
                <ul aria-label="本局公开角色构成">
                  {publicRule.roles.map((role) => (
                    <li key={role.role}>
                      <strong>{role.role}</strong>
                      <span>× {role.count}</span>
                    </li>
                  ))}
                </ul>
                <dl>
                  <div>
                    <dt>警长</dt>
                    <dd>{ruleFlagLabel(publicRule.sheriff_enabled)}</dd>
                  </div>
                  <div>
                    <dt>狼人自爆</dt>
                    <dd>{ruleFlagLabel(publicRule.werewolf_self_explosion_enabled)}</dd>
                  </div>
                  <div>
                    <dt>放逐遗言</dt>
                    <dd>{ruleFlagLabel(publicRule.exile_last_words_enabled)}</dd>
                  </div>
                  <div>
                    <dt>首夜遗言</dt>
                    <dd>{ruleFlagLabel(publicRule.first_night_last_words_enabled)}</dd>
                  </div>
                </dl>
              </>
            ) : (
              <p>{rosterState === "loading" ? "正在读取规则…" : "没有规则快照"}</p>
            )}
          </section>

          <section aria-labelledby="v2-roster-heading">
            <header>
              <h2 id="v2-roster-heading">公开座位</h2>
              <span>{publicPlayers.length} 位</span>
            </header>
            {rosterError ? <p role="alert">{rosterError}</p> : null}
            <ol aria-label="本局公开玩家座位">
              {publicPlayers.map((player) => (
                <li
                  key={player.player_id}
                  className={player.alive ? undefined : "is-dead"}
                >
                  <span>{player.seat}号</span>
                  <strong>
                    {player.display_name}
                    {player.alive ? "" : " · 已死亡"}
                  </strong>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </details>
    </main>
  );
}

function liveProcessLabel(
  connectionState: ConnectionState,
  liveState: LiveState | null,
  phase: GamePhase | null,
  match: MatchState | null,
  nightProgress: NightProgress,
  dayProgress: DayProgress | null,
  viewingMode: ViewingMode,
  directorScene: DirectorScene | null,
  runtime: RuntimeProjection | null,
  presentationActive: boolean,
): string {
  const matchStatus = effectiveMatchStatus(runtime, phase, match, liveState);
  const winner = effectiveWinner(runtime, match);
  const audioEnabled = runtime?.audio_mode === "tts";
  if (presentationActive) {
    return audioEnabled ? "字幕与 PCM 正在同步播出" : "字幕正在实时展示";
  }
  if (matchStatus === "completed" && winner) {
    return winner === "villagers" ? "好人阵营获胜，对局已完成" : "狼人阵营获胜，对局已完成";
  }
  if (liveState === "canceled") return "本局已由运营中断";
  if (liveState === "failed") return "实时演出已停止";
  if (liveState === "awaiting_observation") {
    return awaitingObservationLabel(runtime);
  }
  if (liveState === "paused_model_error") {
    return "模型服务暂时异常，当前动作已安全冻结";
  }
  if (connectionState === "idle") return "舞台已就位，等待观众入场";
  if (connectionState === "connecting") return "正在连接当前实时进度";
  if (liveState === "waiting_to_start") return "玩家与规则已冻结，等待开幕";
  if (
    isDayPhase(phase) &&
    !presentationActive &&
    dayProgress?.stage.startsWith("pre_exile_")
  ) {
    return dayProgressLabel(dayProgress);
  }
  if (liveState === "finalizing") {
    return audioEnabled
      ? "本句播完，正在保存同源语音"
      : "字幕展示完成，正在保存实时记录";
  }
  if (liveState === "broadcasting") {
    return audioEnabled ? "字幕与 PCM 正在同步播出" : "字幕正在实时展示";
  }
  if (liveState === "generating") {
    if (isNightPhase(phase) && viewingMode === "director") {
      return `${directorSceneTitle(directorScene)}正在实时生成`;
    }
    if (isNightPhase(phase)) return "夜间动作正在实时生成";
    if (isDayPhase(phase)) return dayProgressLabel(dayProgress);
    return "法官正在生成开幕播报";
  }
  if (isNightPhase(phase) && viewingMode === "director") {
    return `${directorSceneTitle(directorScene)}正在此刻发生`;
  }
  if (isNightPhase(phase)) return nightProgressLabel(nightProgress);
  if (isDayPhase(phase)) return dayProgressLabel(dayProgress);
  if (audioEnabled) return "声音已解锁，等待下一幕";
  if (runtime?.audio_mode === "legacy_unknown") {
    return "旧记录音频模式未知，仅接收实时字幕";
  }
  return "纯文本通道已就绪，等待下一幕";
}

function directorSceneTitle(scene: DirectorScene | null): string {
  if (!scene) return "夜间私密场景";
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

function nightProgressLabel(stage: NightProgress): string {
  if (stage === "night_started") return "夜间行动窗口已经打开";
  if (stage === "actions_in_progress") return "私密能力执行中，普通观众仅接收安全进度";
  if (stage === "night_resolved") return "夜间效果已结算，等待黎明公开";
  if (stage === "dawn_announced") return "黎明结果已经公开";
  return "夜幕中的下一项动作正在准备";
}

function dayProgressLabel(progress: DayProgress | null): string {
  const stage = progress?.stage ?? null;
  if (!stage || stage === "day_started") return "白天公开流程正在展开";
  if (stage === "pre_sheriff_election") return "警长竞选即将开始";
  if (stage === "pre_exile_special_action") return "正在确认是否有特殊行动";
  if (
    progress !== null &&
    stage === "pre_exile_vote_collecting" &&
    progress.completed_count !== null &&
    progress.total_count !== null
  ) {
    return `投票决策已完成 ${progress.completed_count}/${progress.total_count}`;
  }
  if (stage === "before_exile_vote") return "发言结束，放逐投票即将开始";
  if (stage.startsWith("discussion_round_")) return "存活玩家正在依次公开发言";
  if (stage.includes("sheriff")) return "警长竞选与投票正在进行";
  if (stage.includes("vote") || stage.includes("exile")) {
    return "公开投票与放逐结算正在进行";
  }
  return "白天公开动作正在实时推进";
}

function isNightPhase(phase: GamePhase | null): boolean {
  return (
    phase?.phase_id === "first_night" ||
    phase?.phase_id.startsWith("night_") === true
  );
}

function isDayPhase(phase: GamePhase | null): boolean {
  return phase?.phase_id.startsWith("day_") === true;
}

function ruleFlagLabel(value: boolean | null): string {
  if (value === null) return "未配置";
  return value ? "开启" : "关闭";
}

function toPublicPlayer(player: GodViewPlayerIdentity): PublicPlayerSeat {
  return {
    seat: player.seat,
    player_id: player.player_id,
    display_name: player.display_name,
    avatar_url: player.avatar_url,
    alive: player.alive,
  };
}

function normalizePresentation(
  presentation: Presentation | null,
): Presentation | null {
  return presentation === null
    ? null
    : {
        ...presentation,
        subtitle_text: displaySubtitleText(presentation.subtitle_text),
      };
}

function displaySubtitleText(value: string): string {
  const trimmed = value.trim();
  const fenced =
    /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(trimmed)?.[1] ?? trimmed;
  try {
    const parsed: unknown = JSON.parse(fenced);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "speech" in parsed &&
      typeof parsed.speech === "string" &&
      parsed.speech.trim()
    ) {
      return parsed.speech.trim();
    }
  } catch {
    const partialSpeech = /"speech"\s*:\s*"([\s\S]*)/.exec(fenced)?.[1];
    if (partialSpeech) {
      return partialSpeech
        .replace(/"\s*}\s*$/, "")
        .replace(/\\"/g, '"')
        .replace(/\\n/g, "\n")
        .trim();
    }
  }
  return value;
}
