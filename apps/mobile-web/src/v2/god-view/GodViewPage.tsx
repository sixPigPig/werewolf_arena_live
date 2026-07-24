import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import {
  fetchV2GodViewIdentitySnapshot,
  resolveV2GodViewWebSocketUrl,
} from "../api";
import {
  decodeV2AudioFrame,
  parseV2ServerMessage,
  type V2GodViewIdentitySnapshot,
  type V2GodViewLiveSnapshot,
  type V2GamePhase,
  type V2LiveState,
  type V2Presentation,
  type V2AbilityProgress,
} from "../contracts";
import { V2PcmPlayer } from "../V2PcmPlayer";
import {
  godViewAccessTokenFromHash,
  readGodViewAccessToken,
  saveGodViewAccessToken,
} from "./access";

const GOD_VIEW_WEBSOCKET_SUBPROTOCOL = "live-v2-god-view";

type LoadState = "loading" | "ready" | "failed" | "denied";
type ConnectionState = "idle" | "connecting" | "connected" | "failed";
type GodViewSnapshot = V2GodViewIdentitySnapshot | V2GodViewLiveSnapshot;

export function GodViewPage() {
  const { gameId = "" } = useParams();
  const location = useLocation();
  const hashToken = godViewAccessTokenFromHash(location.hash);
  const accessToken = hashToken ?? readGodViewAccessToken(gameId);
  const socketRef = useRef<WebSocket | null>(null);
  const playerRef = useRef<V2PcmPlayer | null>(null);
  const presentationRef = useRef<V2Presentation | null>(null);
  const terminalRef = useRef(false);
  const [loadState, setLoadState] = useState<LoadState>(
    accessToken ? "loading" : "denied",
  );
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
  const [snapshot, setSnapshot] = useState<GodViewSnapshot | null>(null);
  const [liveState, setLiveState] = useState<V2LiveState | null>(null);
  const [gamePhase, setGamePhase] = useState<V2GamePhase | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [presentation, setPresentation] = useState<V2Presentation | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [abilityProgress, setAbilityProgress] = useState<V2AbilityProgress[]>([]);

  useEffect(() => {
    if (hashToken) saveGodViewAccessToken(gameId, hashToken);
  }, [gameId, hashToken]);

  useEffect(() => {
    if (!accessToken) return;
    let active = true;
    void fetchV2GodViewIdentitySnapshot(gameId, accessToken)
      .then((value) => {
        if (!active) return;
        setSnapshot(value);
        setLiveState(value.live_state);
        setGamePhase(value.game_phase);
        setRunId(value.run_id);
        setLoadState("ready");
      })
      .catch((reason) => {
        if (!active) return;
        setLoadState("failed");
        setLoadError(
          reason instanceof Error ? reason.message : "无法读取上帝视角身份快照",
        );
      });
    return () => {
      active = false;
    };
  }, [accessToken, gameId]);

  useEffect(() => {
    return () => {
      terminalRef.current = true;
      socketRef.current?.close();
      const player = playerRef.current;
      playerRef.current = null;
      if (player) void player.close();
    };
  }, []);

  async function enterLive() {
    if (!accessToken) {
      setLoadState("denied");
      return;
    }
    socketRef.current?.close();
    if (playerRef.current) await playerRef.current.close();
    terminalRef.current = false;
    presentationRef.current = null;
    setPresentation(null);
    setLiveError(null);
    setAbilityProgress([]);
    setConnectionState("connecting");

    try {
      const player = new V2PcmPlayer();
      await player.unlock();
      playerRef.current = player;
      const socket = new WebSocket(resolveV2GodViewWebSocketUrl(gameId), [
        GOD_VIEW_WEBSOCKET_SUBPROTOCOL,
        accessToken,
      ]);
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;
      let readySent = false;

      socket.onopen = () => {
        if (socket.protocol !== GOD_VIEW_WEBSOCKET_SUBPROTOCOL) {
          terminalRef.current = true;
          setConnectionState("failed");
          setLiveError("上帝视角实时连接没有完成受众协议确认");
          socket.close();
          return;
        }
        setConnectionState("connected");
      };
      socket.onmessage = (event) => {
        try {
          if (typeof event.data === "string") {
            const message = parseV2ServerMessage(event.data);
            setRunId(message.run_id);
            if (message.type === "god_view.live_snapshot") {
              setSnapshot(message);
              setLiveState(message.live_state);
              setGamePhase(message.game_phase);
              if (message.live_state === "canceled") {
                terminalRef.current = true;
                presentationRef.current = null;
                setPresentation(null);
                player.stop();
                socket.close();
                return;
              }
              presentationRef.current = message.current_presentation;
              setPresentation(message.current_presentation);
              if (message.current_presentation) player.begin(message.current_presentation);
              if (!readySent) {
                socket.send(
                  JSON.stringify({
                    protocol_version: 1,
                    type: "god_view.ready",
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
            if (message.type === "live.snapshot") {
              throw new Error("上帝视角收到普通观众投影，连接已关闭");
            }
            if (message.type === "live.state_changed") {
              setLiveState(message.live_state);
              if (message.live_state === "canceled") {
                terminalRef.current = true;
                presentationRef.current = null;
                setPresentation(null);
                player.stop();
                socket.close();
                return;
              }
              if (message.live_state === "failed") {
                terminalRef.current = true;
                player.stop();
                setLiveError(message.reason ?? "V2 上帝视角实时动作失败");
              }
              if (message.live_state === "awaiting_observation") {
                terminalRef.current = true;
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
            if (message.type === "ability.progress_changed") {
              setAbilityProgress((current) => {
                if (message.status === "completed") {
                  const existingIndex = current.findLastIndex(
                    (item) =>
                      item.ability_id === message.ability_id &&
                      item.actor_player_id === message.actor_player_id &&
                      item.target_player_id === message.target_player_id,
                  );
                  if (existingIndex >= 0) {
                    return current.map((item, index) =>
                      index === existingIndex ? message : item,
                    );
                  }
                }
                return [...current.slice(-11), message];
              });
              return;
            }
            if (message.type === "day.progress_changed") {
              return;
            }
            if (message.type === "match.state_changed") {
              setSnapshot((current) =>
                current
                  ? {
                      ...current,
                      match_state: {
                        round_no: message.round_no,
                        sheriff_player_id: message.sheriff_player_id,
                        sheriff_badge_state: message.sheriff_badge_state,
                        winner: message.winner,
                      },
                    }
                  : current,
              );
              return;
            }
            if (message.type === "player.state_changed") {
              setSnapshot((current) =>
                current
                  ? {
                      ...current,
                      players: current.players.map((item) =>
                        item.player_id === message.player_id
                          ? {
                              ...item,
                              alive: message.alive,
                              death_cause: message.alive ? null : message.cause,
                            }
                          : item,
                      ),
                    }
                  : current,
              );
              return;
            }
            if (message.type === "night.progress_changed") {
              throw new Error("上帝视角收到普通观众夜间投影，连接已关闭");
            }
            if (message.type === "god_view.night_resolved") {
              const deaths = new Map(
                message.deaths.map((item) => [item.player_id, item.cause]),
              );
              setSnapshot((current) =>
                current
                  ? {
                      ...current,
                      players: current.players.map((item) =>
                        deaths.has(item.player_id)
                          ? {
                              ...item,
                              alive: false,
                              death_cause: deaths.get(item.player_id) ?? null,
                            }
                          : item,
                      ),
                    }
                  : current,
              );
              return;
            }
            if (message.type === "dawn.result_announced") {
              throw new Error("上帝视角收到普通观众黎明投影，连接已关闭");
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
                throw new Error("上帝视角字幕归属与当前展示不一致");
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
              player.stop();
              setLiveState("failed");
              setLiveError(`${message.failure_kind}: ${message.failure_code}`);
              return;
            }
            if (message.type === "presentation.closed") {
              if (presentationRef.current?.presentation_id === message.presentation_id) {
                presentationRef.current = null;
                setPresentation(null);
                player.stop();
              }
              return;
            }
          }
          if (!(event.data instanceof ArrayBuffer)) {
            throw new Error("上帝视角收到未知二进制类型");
          }
          player.push(decodeV2AudioFrame(event.data));
        } catch (reason) {
          terminalRef.current = true;
          player.stop();
          setLiveState("failed");
          setConnectionState("failed");
          setLiveError(reason instanceof Error ? reason.message : "V2 上帝视角协议错误");
          socket.close();
        }
      };
      socket.onerror = () => {
        setConnectionState("failed");
        setLiveError("上帝视角 WebSocket 鉴权或连接失败");
      };
      socket.onclose = () => {
        if (!terminalRef.current) {
          setConnectionState("failed");
          setLiveError("上帝视角实时连接已断开；重连只接收当前和未来内容");
        }
      };
    } catch (reason) {
      setConnectionState("failed");
      setLiveError(reason instanceof Error ? reason.message : "无法启动上帝视角实时观赛");
    }
  }

  return (
    <main className={`mobile-page mobile-god-view-page${isNightPhase(gamePhase) ? " is-night" : ""}`}>
      <header className="mobile-god-view-heading">
        <span>LIVE V2 · OMNISCIENT</span>
        <h1>上帝视角</h1>
        <small>{gameId}</small>
        {snapshot?.match_state ? (
          <small>
            第 {snapshot.match_state.round_no} 轮 · {godSheriffLabel(snapshot)}
          </small>
        ) : null}
      </header>

      <section className="mobile-god-view-warning" aria-label="上帝视角隐私提示">
        <strong>全知模式</strong>
        <p>当前页面包含全部玩家的真实身份与阵营，请勿向普通观众泄露。</p>
      </section>

      {loadState === "loading" ? (
        <p className="mobile-status-banner" role="status">正在解封全部身份...</p>
      ) : null}
      {loadState === "denied" ? (
        <p className="mobile-status-banner mobile-status-banner-error" role="alert">
          缺少上帝视角访问凭证，普通直播链接不能进入全知模式。
        </p>
      ) : null}
      {loadState === "failed" ? (
        <p className="mobile-status-banner mobile-status-banner-error" role="alert">
          {loadError}
        </p>
      ) : null}

      {snapshot && connectionState === "idle" && liveState !== "canceled" ? (
        <section className="mobile-god-view-stage">
          <span>全知实时观赛</span>
          <blockquote>身份已经解封。进入后将实时接收当前法官字幕与语音。</blockquote>
          <button
            className="mobile-button mobile-button-primary"
            onClick={() => void enterLive()}
            type="button"
          >
            进入上帝视角实时观赛
          </button>
        </section>
      ) : null}

      {connectionState === "connecting" ? (
        <p className="mobile-status-banner" role="status">正在鉴权并连接上帝视角...</p>
      ) : null}

      {presentation ? (
        <section className="mobile-god-view-stage" aria-labelledby="god-view-actor-label">
          <span id="god-view-actor-label">
            {presentation.actor.kind === "judge"
              ? "法官"
              : playerName(snapshot, presentation.actor.id)}
          </span>
          <blockquote>{presentation.subtitle_text || "正在等待完整句子..."}</blockquote>
          <p aria-live="polite" role="status">{liveLabel(liveState, gamePhase)}</p>
          <dl>
            <div><dt>run</dt><dd>{runId}</dd></div>
            <div><dt>action</dt><dd>{presentation.action_id}</dd></div>
            <div><dt>presentation</dt><dd>#{presentation.presentation_seq} · {presentation.presentation_id}</dd></div>
            <div><dt>speech</dt><dd>{presentation.speech_id} · segment {presentation.segment_index}</dd></div>
          </dl>
        </section>
      ) : connectionState === "connected" &&
        liveState !== "canceled" &&
        !liveError ? (
        <p className="mobile-status-banner" role="status">{liveLabel(liveState, gamePhase)}</p>
      ) : null}

      {isNightPhase(gamePhase) ? (
        <section className="mobile-live-v2-night" aria-label="当前游戏阶段">
          <span>第 {snapshot?.match_state?.round_no ?? 1} 夜 · 全知模式</span>
          <strong>{gamePhase?.phase_state === "night_running" ? "全知夜间能力执行中" : "天黑，请闭眼"}</strong>
          <small>全部私密决策、目标、字幕和同源语音只投影到本模式。</small>
        </section>
      ) : null}

      {isDayPhase(gamePhase) ? (
        <section className="mobile-live-v2-night" aria-label="当前游戏阶段">
          <span>第 {snapshot?.match_state?.round_no ?? 1} 天 · 全知模式</span>
          <strong>{dayPhaseLabel(gamePhase?.phase_state ?? "")}</strong>
          <small>公开动作向所有观众播出；秘密自爆判断只在全知模式展示。</small>
        </section>
      ) : null}

      {abilityProgress.length > 0 ? (
        <section className="mobile-god-view-stage" aria-labelledby="god-ability-progress">
          <span>私密能力流水</span>
          <h2 id="god-ability-progress">夜间实时决策</h2>
          <ol>
            {abilityProgress.map((item, index) => (
              <li key={`${item.ability_id}-${item.actor_player_id ?? "system"}-${index}`}>
                <strong>{abilityLabel(item.ability_id)}</strong>
                <span>{item.actor_player_id ? playerName(snapshot, item.actor_player_id) : "系统"}</span>
                <small>{item.target_player_id ? `目标：${playerName(snapshot, item.target_player_id)}` : statusLabel(item.status)}</small>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {liveState === "awaiting_observation" && connectionState !== "idle" ? (
        <p className="mobile-status-banner" role="status">
          {snapshot?.match_state?.winner
            ? `完整对局已结束：${snapshot.match_state.winner === "villagers" ? "好人阵营" : "狼人阵营"}获胜。`
            : "当前对局已停止；私密与公开语音均已分别保存。"}
        </p>
      ) : null}

      {liveState === "canceled" ? (
        <section className="mobile-live-v2-error" role="alert">
          <strong>本局已由管理员终止</strong>
          <p>上帝视角已停止当前字幕与语音，不会继续播放或补播。</p>
        </section>
      ) : null}

      {liveError ? (
        <section className="mobile-live-v2-error" role="alert">
          <strong>上帝视角实时观赛失败</strong>
          <p>{liveError}</p>
          <button className="mobile-button" onClick={() => void enterLive()} type="button">
            重新连接当前直播
          </button>
        </section>
      ) : null}

      {snapshot ? (
        <section className="mobile-god-view-identities" aria-labelledby="god-identities-heading">
          <header>
            <div>
              <span>冻结身份快照</span>
              <h2 id="god-identities-heading">{snapshot.rule?.name ?? "本局身份"}</h2>
            </div>
            <strong>{snapshot.players.length} 位玩家</strong>
          </header>
          <ol aria-label="上帝视角玩家身份">
            {snapshot.players.map((player) => (
              <li key={player.player_id} className={player.alive ? undefined : "is-dead"}>
                <span className="mobile-god-view-seat">{player.seat}号</span>
                <span className="mobile-god-view-avatar" aria-hidden="true">
                  {player.avatar_url ? (
                    <img src={player.avatar_url} alt="" />
                  ) : (
                    player.display_name.slice(0, 1)
                  )}
                </span>
                <div>
                  <strong>{player.display_name}</strong>
                  <small>{player.alive ? teamLabel(player.team) : `已死亡 · ${deathCauseLabel(player.death_cause)}`}</small>
                </div>
                <b>{player.role}</b>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <Link className="mobile-button mobile-button-secondary" to={`/v2/games/${gameId}/live`}>
        返回普通直播
      </Link>
    </main>
  );
}

function liveLabel(state: V2LiveState | null, phase: V2GamePhase | null): string {
  const isNight = isNightPhase(phase);
  if (state === "waiting_to_start") return "等待观众点击进入，正式对局尚未开始";
  if (state === "ready") return "音频已解锁，等待启动实时法官动作...";
  if (state === "generating") {
    if (phase?.phase_state === "night_running") return "夜间私密动作正在实时请求大模型...";
    if (phase?.phase_state === "sheriff_election_ready") return "法官正在实时生成警长竞选开场...";
    if (phase?.phase_state === "public_day_ready") return "法官正在实时生成白天发言开场...";
    if (isDayPhase(phase)) return "白天公开动作正在实时请求大模型...";
    return isNight
      ? "法官正在通过大模型实时生成入夜播报..."
      : "法官正在通过大模型实时生成开场播报...";
  }
  if (state === "broadcasting") {
    if (phase?.phase_state === "night_running") return "夜间私密字幕与语音正在实时播出";
    if (phase?.phase_state === "sheriff_election_ready") return "警长竞选开场正在实时播报";
    if (phase?.phase_state === "public_day_ready") return "白天发言开场正在实时播报";
    if (isDayPhase(phase)) return "白天公开动作正在实时播报";
    return isNight
      ? "法官入夜话术正在向全部观众实时播报"
      : "法官开场话术正在向全部观众实时播报";
  }
  if (state === "finalizing") return "播报完成，正在校验并保存同源 V2 语音资产...";
  if (state === "awaiting_observation") return "完整对局已经结束";
  if (state === "canceled") return "本局已由管理员终止";
  if (state === "failed") return "本次实时动作已明确失败";
  return "正在读取当前实时状态...";
}

function abilityLabel(value: string): string {
  const labels: Record<string, string> = {
    "werewolf.attack": "狼人袭击",
    "guard.protect": "守卫守护",
    "seer.investigate": "预言家查验",
    "witch.heal": "女巫解药",
    "witch.poison": "女巫毒药",
    "hunter.death_shot": "猎人开枪",
    "night.resolve": "夜间结算",
  };
  return labels[value] ?? value;
}

function isNightPhase(phase: V2GamePhase | null): boolean {
  return phase?.phase_id === "first_night" || phase?.phase_id.startsWith("night_") === true;
}

function isDayPhase(phase: V2GamePhase | null): boolean {
  return phase?.phase_id.startsWith("day_") === true;
}

function dayPhaseLabel(phaseState: string): string {
  if (phaseState === "sheriff_election_ready") return "准备警长竞选";
  if (phaseState === "sheriff_election_open") return "警长竞选进行中";
  if (phaseState === "public_discussion_open") return "公开发言与放逐流程进行中";
  if (phaseState === "game_completed") return "对局已结束";
  return "黎明结算与死亡响应进行中";
}

function godSheriffLabel(snapshot: GodViewSnapshot): string {
  const match = snapshot.match_state;
  if (!match || match.sheriff_badge_state === "disabled") return "本局无警长";
  if (match.sheriff_badge_state === "pending") return "警长待选";
  if (match.sheriff_badge_state === "destroyed") return "警徽已流失";
  return `警长：${playerName(snapshot, match.sheriff_player_id ?? "")}`;
}

function statusLabel(value: string): string {
  if (value === "completed") return "已完成";
  if (value === "no_consensus_no_attack") return "两轮未达成一致，空刀";
  return value;
}

function playerName(snapshot: GodViewSnapshot | null, playerId: string): string {
  return snapshot?.players.find((player) => player.player_id === playerId)?.display_name ?? playerId;
}

function deathCauseLabel(value: string | null): string {
  if (value === "werewolf_attack") return "狼人袭击";
  if (value === "witch_poison") return "女巫毒杀";
  if (value === "hunter_shot") return "猎人开枪";
  if (value === "exile") return "投票放逐";
  if (value === "werewolf_self_explosion") return "狼人自爆";
  return value ?? "原因未记录";
}

function teamLabel(team: string | null): string {
  if (team === "werewolves") return "狼人阵营";
  if (team === "villagers" || team === "village") return "好人阵营";
  return team ?? "未标注阵营";
}
