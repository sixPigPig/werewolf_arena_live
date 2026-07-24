import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { fetchV2LiveSnapshot, resolveV2WebSocketUrl } from "../api";
import {
  decodeV2AudioFrame,
  parseV2ServerMessage,
  type V2GamePhase,
  type V2LiveState,
  type V2MatchState,
  type V2Presentation,
  type V2PublicPlayerSeat,
  type V2PublicRoleAssignmentStatus,
  type V2PublicRuleSnapshot,
} from "../contracts";
import {
  godViewPageUrl,
  readGodViewAccessToken,
} from "../god-view/access";
import { V2PcmPlayer } from "../V2PcmPlayer";
import {
  V2LiveTheater,
  type V2ConnectionState,
} from "./V2LiveTheater";

type RosterState = "loading" | "ready" | "failed";
type NightProgress =
  | "night_started"
  | "actions_in_progress"
  | "night_resolved"
  | "dawn_announced"
  | null;

export function LiveV2Page() {
  const { gameId = "" } = useParams();
  const godViewAccessToken = readGodViewAccessToken(gameId);
  const socketRef = useRef<WebSocket | null>(null);
  const playerRef = useRef<V2PcmPlayer | null>(null);
  const presentationRef = useRef<V2Presentation | null>(null);
  const terminalRef = useRef(false);
  const audioPulseTimerRef = useRef<number | null>(null);
  const deathReactionTimerRef = useRef<number | null>(null);
  const [connectionState, setConnectionState] =
    useState<V2ConnectionState>("idle");
  const [liveState, setLiveState] = useState<V2LiveState | null>(null);
  const [gamePhase, setGamePhase] = useState<V2GamePhase | null>(null);
  const [matchState, setMatchState] = useState<V2MatchState | null>(null);
  const [presentation, setPresentation] = useState<V2Presentation | null>(null);
  const [publicPlayers, setPublicPlayers] = useState<V2PublicPlayerSeat[]>([]);
  const [publicRule, setPublicRule] = useState<V2PublicRuleSnapshot | null>(null);
  const [roleAssignment, setRoleAssignment] =
    useState<V2PublicRoleAssignmentStatus | null>(null);
  const [rosterState, setRosterState] = useState<RosterState>("loading");
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nightProgress, setNightProgress] = useState<NightProgress>(null);
  const [dayProgress, setDayProgress] = useState<string | null>(null);
  const [audioActive, setAudioActive] = useState(false);
  const [reactingPlayerIds, setReactingPlayerIds] = useState<Set<string>>(
    () => new Set(),
  );

  useEffect(() => {
    let active = true;
    void fetchV2LiveSnapshot(gameId)
      .then((snapshot) => {
        if (!active) return;
        setPublicRule(snapshot.public_rule);
        setPublicPlayers(snapshot.public_players);
        setRoleAssignment(snapshot.public_role_assignment);
        setGamePhase(snapshot.game_phase);
        setMatchState(snapshot.match_state);
        setLiveState(snapshot.live_state);
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
    try {
      const player = new V2PcmPlayer();
      await player.unlock();
      playerRef.current = player;
      const socket = new WebSocket(resolveV2WebSocketUrl(gameId));
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;
      let readySent = false;
      socket.onopen = () => setConnectionState("connected");
      socket.onmessage = (event) => {
        try {
          if (typeof event.data === "string") {
            const message = parseV2ServerMessage(event.data);
            if (message.type === "live.snapshot") {
              setLiveState(message.live_state);
              setGamePhase(message.game_phase);
              setMatchState(message.match_state);
              setPublicRule(message.public_rule);
              setPublicPlayers(message.public_players);
              setRoleAssignment(message.public_role_assignment);
              setRosterState("ready");
              setRosterError(null);
              if (message.live_state === "canceled") {
                terminalRef.current = true;
                presentationRef.current = null;
                setPresentation(null);
                setAudioActive(false);
                player.stop();
                socket.close();
                return;
              }
              presentationRef.current = message.current_presentation;
              setPresentation(message.current_presentation);
              if (message.current_presentation) {
                player.begin(message.current_presentation);
              }
              if (!readySent) {
                socket.send(
                  JSON.stringify({
                    protocol_version: 1,
                    type: "client.ready",
                    audio: {
                      encoding: "pcm_s16le",
                      sample_rate: 24000,
                      channels: 1,
                    },
                  }),
                );
                readySent = true;
              }
              if (
                message.live_state === "awaiting_observation" ||
                message.live_state === "failed"
              ) {
                terminalRef.current = true;
              }
              return;
            }
            if (message.type === "live.state_changed") {
              setLiveState(message.live_state);
              if (message.live_state === "canceled") {
                terminalRef.current = true;
                presentationRef.current = null;
                setPresentation(null);
                setAudioActive(false);
                player.stop();
                socket.close();
                return;
              }
              if (message.live_state === "failed") {
                terminalRef.current = true;
                setAudioActive(false);
                player.stop();
                setError(message.reason ?? "V2 实时动作失败");
              }
              if (message.live_state === "awaiting_observation") {
                terminalRef.current = true;
                setAudioActive(false);
              }
              return;
            }
            if (message.type === "game.phase_changed") {
              setGamePhase({
                phase_seq: message.phase_seq,
                phase_id: message.phase_id,
                phase_state: message.phase_state,
              });
              return;
            }
            if (message.type === "night.progress_changed") {
              setNightProgress(message.stage);
              return;
            }
            if (message.type === "day.progress_changed") {
              setDayProgress(message.stage);
              return;
            }
            if (message.type === "match.state_changed") {
              setMatchState({
                round_no: message.round_no,
                sheriff_player_id: message.sheriff_player_id,
                sheriff_badge_state: message.sheriff_badge_state,
                winner: message.winner,
              });
              return;
            }
            if (message.type === "player.state_changed") {
              if (message.cause !== null) {
                throw new Error("普通观众连接收到私密死亡原因，连接已关闭");
              }
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
              return;
            }
            if (message.type === "ability.progress_changed") {
              throw new Error("普通观众连接收到私密能力投影，连接已关闭");
            }
            if (message.type === "dawn.result_announced") {
              revealPublicDeaths(message.dead_player_ids);
              return;
            }
            if (message.type === "god_view.night_resolved") {
              throw new Error("普通观众连接收到上帝视角结算，连接已关闭");
            }
            if (message.type === "presentation.opened") {
              const current: V2Presentation = {
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
              player.begin(current);
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
                subtitle_text: message.text,
              };
              presentationRef.current = committed;
              setPresentation(committed);
              return;
            }
            if (message.type === "presentation.failed") {
              terminalRef.current = true;
              setAudioActive(false);
              player.stop();
              setLiveState("failed");
              setError(`${message.failure_kind}: ${message.failure_code}`);
              return;
            }
            if (message.type === "presentation.closed") {
              if (
                presentationRef.current?.presentation_id ===
                message.presentation_id
              ) {
                presentationRef.current = null;
                setPresentation(null);
                setAudioActive(false);
                player.stop();
              }
              return;
            }
          }
          if (!(event.data instanceof ArrayBuffer)) {
            throw new Error("V2 收到未知二进制类型");
          }
          player.push(decodeV2AudioFrame(event.data));
          showAudioPulse();
        } catch (reason) {
          terminalRef.current = true;
          setAudioActive(false);
          player.stop();
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
    nightProgress,
    dayProgress,
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

      <V2LiveTheater
        audioActive={audioActive}
        connectionState={connectionState}
        error={error}
        gamePhase={gamePhase}
        liveState={liveState}
        matchState={matchState}
        onEnter={() => void enterLive()}
        presentation={presentation}
        processLabel={processLabel}
        publicPlayers={publicPlayers}
        reactingPlayerIds={reactingPlayerIds}
        ruleName={publicRule?.name ?? "Live V2"}
      />

      {godViewAccessToken ? (
        <Link
          className="mobile-v2-god-link"
          to={godViewPageUrl(gameId, godViewAccessToken)}
        >
          <span>持有全知凭证</span>
          <strong>进入上帝视角</strong>
        </Link>
      ) : null}

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
              <span>普通直播不会展示任何座位对应的角色或阵营，也不会公开私密死亡原因。</span>
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
  connectionState: V2ConnectionState,
  liveState: V2LiveState | null,
  phase: V2GamePhase | null,
  nightProgress: NightProgress,
  dayProgress: string | null,
): string {
  if (liveState === "canceled") return "本局已由运营中断";
  if (liveState === "failed") return "实时演出已停止";
  if (liveState === "awaiting_observation") return "本局实时流程已经停播";
  if (connectionState === "idle") return "舞台已就位，等待观众入场";
  if (connectionState === "connecting") return "正在连接当前实时进度";
  if (liveState === "waiting_to_start") return "玩家与规则已冻结，等待开幕";
  if (liveState === "finalizing") return "本句播完，正在保存同源语音";
  if (liveState === "broadcasting") return "字幕与 PCM 正在同步播出";
  if (liveState === "generating") {
    if (isNightPhase(phase)) return "夜间动作正在实时生成";
    if (isDayPhase(phase)) return dayProgressLabel(dayProgress);
    return "法官正在生成开幕播报";
  }
  if (isNightPhase(phase)) return nightProgressLabel(nightProgress);
  if (isDayPhase(phase)) return dayProgressLabel(dayProgress);
  return "声音已解锁，等待下一幕";
}

function nightProgressLabel(stage: NightProgress): string {
  if (stage === "night_started") return "夜间行动窗口已经打开";
  if (stage === "actions_in_progress") return "私密能力执行中，普通观众仅接收安全进度";
  if (stage === "night_resolved") return "夜间效果已结算，等待黎明公开";
  if (stage === "dawn_announced") return "黎明结果已经公开";
  return "夜幕中的下一项动作正在准备";
}

function dayProgressLabel(stage: string | null): string {
  if (!stage || stage === "day_started") return "白天公开流程正在展开";
  if (stage === "pre_sheriff_election") return "警长竞选即将开始";
  if (stage === "before_exile_vote") return "发言结束，放逐投票即将开始";
  if (stage.startsWith("discussion_round_")) return "存活玩家正在依次公开发言";
  if (stage.includes("sheriff")) return "警长竞选与投票正在进行";
  if (stage.includes("vote") || stage.includes("exile")) {
    return "公开投票与放逐结算正在进行";
  }
  return "白天公开动作正在实时推进";
}

function isNightPhase(phase: V2GamePhase | null): boolean {
  return (
    phase?.phase_id === "first_night" ||
    phase?.phase_id.startsWith("night_") === true
  );
}

function isDayPhase(phase: V2GamePhase | null): boolean {
  return phase?.phase_id.startsWith("day_") === true;
}

function ruleFlagLabel(value: boolean | null): string {
  if (value === null) return "未配置";
  return value ? "开启" : "关闭";
}
