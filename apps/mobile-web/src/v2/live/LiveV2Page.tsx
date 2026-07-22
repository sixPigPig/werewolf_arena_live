import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { fetchV2LiveSnapshot, resolveV2WebSocketUrl } from "../api";
import {
  decodeV2AudioFrame,
  parseV2ServerMessage,
  type V2GamePhase,
  type V2LiveState,
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

type ConnectionState = "idle" | "connecting" | "connected" | "failed";
type RosterState = "loading" | "ready" | "failed";

export function LiveV2Page() {
  const { gameId = "" } = useParams();
  const godViewAccessToken = readGodViewAccessToken(gameId);
  const socketRef = useRef<WebSocket | null>(null);
  const playerRef = useRef<V2PcmPlayer | null>(null);
  const presentationRef = useRef<V2Presentation | null>(null);
  const terminalRef = useRef(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
  const [liveState, setLiveState] = useState<V2LiveState | null>(null);
  const [gamePhase, setGamePhase] = useState<V2GamePhase | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [presentation, setPresentation] = useState<V2Presentation | null>(null);
  const [publicPlayers, setPublicPlayers] = useState<V2PublicPlayerSeat[]>([]);
  const [publicRule, setPublicRule] = useState<V2PublicRuleSnapshot | null>(null);
  const [roleAssignment, setRoleAssignment] =
    useState<V2PublicRoleAssignmentStatus | null>(null);
  const [rosterState, setRosterState] = useState<RosterState>("loading");
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nightProgress, setNightProgress] = useState<
    "night_started" | "actions_in_progress" | "night_resolved" | "dawn_announced" | null
  >(null);

  useEffect(() => {
    let active = true;
    void fetchV2LiveSnapshot(gameId)
      .then((snapshot) => {
        if (!active) return;
        setPublicRule(snapshot.public_rule);
        setPublicPlayers(snapshot.public_players);
        setRoleAssignment(snapshot.public_role_assignment);
        setGamePhase(snapshot.game_phase);
        setRosterState("ready");
      })
      .catch((reason) => {
        if (!active) return;
        setRosterState("failed");
        setRosterError(reason instanceof Error ? reason.message : "无法读取本局座位快照");
      });
    return () => {
      active = false;
    };
  }, [gameId]);

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
    socketRef.current?.close();
    if (playerRef.current) await playerRef.current.close();
    terminalRef.current = false;
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
            setRunId(message.run_id);
            if (message.type === "live.snapshot") {
              setLiveState(message.live_state);
              setGamePhase(message.game_phase);
              setPublicRule(message.public_rule);
              setPublicPlayers(message.public_players);
              setRoleAssignment(message.public_role_assignment);
              setRosterState("ready");
              setRosterError(null);
              presentationRef.current = message.current_presentation;
              setPresentation(message.current_presentation);
              if (message.current_presentation) player.begin(message.current_presentation);
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
              if (message.live_state === "failed") {
                terminalRef.current = true;
                player.stop();
                setError(message.reason ?? "V2 实时动作失败");
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
            if (message.type === "night.progress_changed") {
              setNightProgress(message.stage);
              return;
            }
            if (message.type === "ability.progress_changed") {
              throw new Error("普通观众连接收到私密能力投影，连接已关闭");
            }
            if (message.type === "dawn.result_announced") {
              const dead = new Set(message.dead_player_ids);
              setPublicPlayers((current) =>
                current.map((player) =>
                  dead.has(player.player_id) ? { ...player, alive: false } : player,
                ),
              );
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
              player.stop();
              setLiveState("failed");
              setError(`${message.failure_kind}: ${message.failure_code}`);
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
            throw new Error("V2 收到未知二进制类型");
          }
          player.push(decodeV2AudioFrame(event.data));
        } catch (reason) {
          terminalRef.current = true;
          player.stop();
          setLiveState("failed");
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
          setError("V2 实时连接已断开；重新进入只会接收当前和未来内容");
        }
      };
    } catch (reason) {
      setConnectionState("failed");
      setError(reason instanceof Error ? reason.message : "无法启动 V2 实时直播");
    }
  }

  return (
    <main className={`mobile-page mobile-live-v2-page${gamePhase?.phase_id === "first_night" ? " is-first-night" : ""}`}>
      <header className="mobile-live-v2-heading">
        <span>LIVE V2 · REALTIME</span>
        <h1>Live V2</h1>
        <small>{gameId}</small>
      </header>

      <section className="mobile-live-v2-rule" aria-labelledby="v2-rule-heading">
        <header>
          <div>
            <span>冻结规则</span>
            <h2 id="v2-rule-heading">{publicRule?.name ?? "规则快照"}</h2>
          </div>
          {publicRule ? <strong>v{publicRule.version}</strong> : null}
        </header>
        {rosterState === "loading" ? <p role="status">正在读取不可变规则快照...</p> : null}
        {rosterState === "ready" && !publicRule ? <p>本对局没有大厅规则快照。</p> : null}
        {publicRule ? (
          <>
            <p>{publicRule.player_count} 位玩家 · 最多 {publicRule.max_rounds} 轮</p>
            <ul aria-label="本局角色构成">
              {publicRule.roles.map((role) => (
                <li key={role.role}><strong>{role.role}</strong><span>× {role.count}</span></li>
              ))}
            </ul>
            <dl>
              <div><dt>警长</dt><dd>{ruleFlagLabel(publicRule.sheriff_enabled)}</dd></div>
              <div><dt>狼人自爆</dt><dd>{ruleFlagLabel(publicRule.werewolf_self_explosion_enabled)}</dd></div>
              <div><dt>放逐遗言</dt><dd>{ruleFlagLabel(publicRule.exile_last_words_enabled)}</dd></div>
            </dl>
          </>
        ) : null}
      </section>

      <section className="mobile-live-v2-roster" aria-labelledby="v2-roster-heading">
        <header>
          <h2 id="v2-roster-heading">本局座位</h2>
          <span>{rosterState === "ready" ? `${publicPlayers.length} 位玩家` : "读取中"}</span>
        </header>
        {roleAssignment ? (
          <div className={`mobile-live-v2-role-seal is-${roleAssignment.state}`}>
            <strong>
              {roleAssignment.state === "sealed"
                ? `身份已私密封存 · ${roleAssignment.assigned_count} 人`
                : "身份尚未分配"}
            </strong>
            <span>普通直播不会展示任何座位对应的角色或阵营。</span>
          </div>
        ) : null}
        {rosterState === "loading" ? <p role="status">正在读取不可变玩家快照...</p> : null}
        {rosterState === "failed" ? <p role="alert">{rosterError}</p> : null}
        {rosterState === "ready" && publicPlayers.length === 0 ? (
          <p>本对局没有大厅玩家快照。</p>
        ) : null}
        {publicPlayers.length > 0 ? (
          <ol aria-label="本局玩家座位">
            {publicPlayers.map((player) => (
              <li key={player.player_id} className={player.alive ? undefined : "is-dead"}>
                <span className="mobile-live-v2-seat-number">{player.seat}号</span>
                <span className="mobile-live-v2-seat-avatar" aria-hidden="true">
                  {player.avatar_url ? (
                    <img src={player.avatar_url} alt="" />
                  ) : (
                    player.display_name.slice(0, 1)
                  )}
                </span>
                <strong>{player.display_name}{player.alive ? "" : " · 已死亡"}</strong>
              </li>
            ))}
          </ol>
        ) : null}
      </section>

      {godViewAccessToken ? (
        <Link
          className="mobile-live-v2-god-link"
          to={godViewPageUrl(gameId, godViewAccessToken)}
        >
          <span>全知观赛模式</span>
          <strong>进入上帝视角</strong>
          <small>查看所有座位的真实角色与阵营</small>
        </Link>
      ) : null}

      {connectionState === "idle" ? (
        <section className="mobile-live-v2-stage">
          <span>实时对局</span>
          <blockquote>点击后解锁音频；法官播报、玩家决策和语音都将在对应动作发生时实时生成。</blockquote>
          <button className="mobile-button mobile-button-primary" onClick={() => void enterLive()} type="button">
            进入实时直播
          </button>
        </section>
      ) : null}

      {connectionState === "connecting" ? (
        <p className="mobile-status-banner" role="status">正在建立 V2 实时连接...</p>
      ) : null}

      {presentation ? (
        <section className="mobile-live-v2-stage" aria-labelledby="v2-actor-label">
          <span id="v2-actor-label">
            {presentation.actor.kind === "judge"
              ? "法官"
              : publicPlayerName(publicPlayers, presentation.actor.id)}
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
      ) : connectionState !== "idle" && !error ? (
        <p className="mobile-status-banner" role="status">{liveLabel(liveState, gamePhase)}</p>
      ) : null}

      {gamePhase?.phase_id === "first_night" ? (
        <section className="mobile-live-v2-night" aria-label="当前游戏阶段">
          <span>第一夜</span>
          <strong>{gamePhase.phase_state === "night_running" ? "首夜能力正在实时执行" : "天黑，请闭眼"}</strong>
          <small>{nightProgressLabel(nightProgress)}</small>
        </section>
      ) : null}

      {gamePhase?.phase_id === "day_1" ? (
        <section className="mobile-live-v2-night" aria-label="当前游戏阶段">
          <span>第一天</span>
          <strong>{gamePhase.phase_state === "sheriff_election_ready" ? "等待警长竞选" : gamePhase.phase_state === "game_completed" ? "对局已结束" : "黎明结算完成"}</strong>
          <small>首夜所有已配置能力已经结算，当前停在下一公开行动窗口之前。</small>
        </section>
      ) : null}

      {liveState === "awaiting_observation" ? (
        <p className="mobile-status-banner" role="status">当前验收切片已实时完成；所有已播语音均已分别保存，流程停在下一行动窗口之前。</p>
      ) : null}

      {error ? (
        <section className="mobile-live-v2-error" role="alert">
          <strong>V2 实时直播失败</strong>
          <p>{error}</p>
          <button className="mobile-button" onClick={() => void enterLive()} type="button">重新连接当前直播</button>
        </section>
      ) : null}

      <Link className="mobile-button" to="/games">返回对局大厅</Link>
    </main>
  );
}

function liveLabel(state: V2LiveState | null, phase: V2GamePhase | null): string {
  const isNight = phase?.phase_id === "first_night";
  if (state === "ready") return "音频已解锁，等待启动实时法官动作...";
  if (state === "generating") {
    if (phase?.phase_state === "night_running") return "首夜动作正在实时请求大模型...";
    if (phase?.phase_id === "day_1") return "法官正在实时生成黎明播报...";
    return isNight
      ? "法官正在通过大模型实时生成入夜播报..."
      : "法官正在通过大模型实时生成开场播报...";
  }
  if (state === "broadcasting") {
    if (phase?.phase_state === "night_running") return "首夜动作语音正在实时播出";
    if (phase?.phase_id === "day_1") return "黎明结果正在实时播报";
    return isNight ? "法官入夜话术实时播报中" : "法官开场话术实时播报中";
  }
  if (state === "finalizing") return "语音播报完成，正在校验并保存 V2 语音资产...";
  if (state === "awaiting_observation") return "当前流程已完成，等待本步验收";
  if (state === "failed") return "本次实时动作已明确失败";
  return "正在读取当前实时状态...";
}

function nightProgressLabel(
  stage: "night_started" | "actions_in_progress" | "night_resolved" | "dawn_announced" | null,
): string {
  if (stage === "night_started") return "首夜行动窗口已经打开。";
  if (stage === "actions_in_progress") return "私密能力正在依规则执行；普通观众只接收安全进度。";
  if (stage === "night_resolved") return "首夜效果已由确定性规则结算，正在等待黎明播报。";
  if (stage === "dawn_announced") return "黎明结果已公开播报。";
  return "等待首夜实时行动开始。";
}

function ruleFlagLabel(value: boolean | null): string {
  if (value === null) return "未配置";
  return value ? "开启" : "关闭";
}

function publicPlayerName(players: V2PublicPlayerSeat[], playerId: string): string {
  return players.find((player) => player.player_id === playerId)?.display_name ?? playerId;
}
