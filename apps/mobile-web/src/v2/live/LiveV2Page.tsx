import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { fetchV2LiveSnapshot, resolveV2WebSocketUrl } from "../api";
import {
  decodeV2AudioFrame,
  parseV2ServerMessage,
  type V2LiveState,
  type V2Presentation,
  type V2PublicPlayerSeat,
} from "../contracts";
import { V2PcmPlayer } from "./V2PcmPlayer";

type ConnectionState = "idle" | "connecting" | "connected" | "failed";
type RosterState = "loading" | "ready" | "failed";

export function LiveV2Page() {
  const { gameId = "" } = useParams();
  const socketRef = useRef<WebSocket | null>(null);
  const playerRef = useRef<V2PcmPlayer | null>(null);
  const presentationRef = useRef<V2Presentation | null>(null);
  const terminalRef = useRef(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
  const [liveState, setLiveState] = useState<V2LiveState | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [presentation, setPresentation] = useState<V2Presentation | null>(null);
  const [publicPlayers, setPublicPlayers] = useState<V2PublicPlayerSeat[]>([]);
  const [rosterState, setRosterState] = useState<RosterState>("loading");
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void fetchV2LiveSnapshot(gameId)
      .then((snapshot) => {
        if (!active) return;
        setPublicPlayers(snapshot.public_players);
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
              setPublicPlayers(message.public_players);
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
    <main className="mobile-page mobile-live-v2-page">
      <header className="mobile-live-v2-heading">
        <span>LIVE V2 · REALTIME</span>
        <h1>Live V2</h1>
        <small>{gameId}</small>
      </header>

      <section className="mobile-live-v2-roster" aria-labelledby="v2-roster-heading">
        <header>
          <h2 id="v2-roster-heading">本局座位</h2>
          <span>{rosterState === "ready" ? `${publicPlayers.length} 位玩家` : "读取中"}</span>
        </header>
        {rosterState === "loading" ? <p role="status">正在读取不可变玩家快照...</p> : null}
        {rosterState === "failed" ? <p role="alert">{rosterError}</p> : null}
        {rosterState === "ready" && publicPlayers.length === 0 ? (
          <p>本对局没有大厅玩家快照。</p>
        ) : null}
        {publicPlayers.length > 0 ? (
          <ol aria-label="本局玩家座位">
            {publicPlayers.map((player) => (
              <li key={player.player_id}>
                <span className="mobile-live-v2-seat-number">{player.seat}号</span>
                <span className="mobile-live-v2-seat-avatar" aria-hidden="true">
                  {player.avatar_url ? (
                    <img src={player.avatar_url} alt="" />
                  ) : (
                    player.display_name.slice(0, 1)
                  )}
                </span>
                <strong>{player.display_name}</strong>
              </li>
            ))}
          </ol>
        ) : null}
      </section>

      {connectionState === "idle" ? (
        <section className="mobile-live-v2-stage">
          <span>实时首句验收</span>
          <blockquote>点击后才会解锁音频并发起本次真实模型请求。</blockquote>
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
          <span id="v2-actor-label">{presentation.actor.kind === "judge" ? "法官" : presentation.actor.id}</span>
          <blockquote>{presentation.subtitle_text || "正在等待完整句子..."}</blockquote>
          <p aria-live="polite" role="status">{liveLabel(liveState)}</p>
          <dl>
            <div><dt>run</dt><dd>{runId}</dd></div>
            <div><dt>action</dt><dd>{presentation.action_id}</dd></div>
            <div><dt>presentation</dt><dd>#{presentation.presentation_seq} · {presentation.presentation_id}</dd></div>
            <div><dt>speech</dt><dd>{presentation.speech_id} · segment {presentation.segment_index}</dd></div>
          </dl>
        </section>
      ) : connectionState !== "idle" && !error ? (
        <p className="mobile-status-banner" role="status">{liveLabel(liveState)}</p>
      ) : null}

      {liveState === "awaiting_observation" ? (
        <p className="mobile-status-banner" role="status">法官第一句话已直播并保存，流程正在等待本步验收。</p>
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

function liveLabel(state: V2LiveState | null): string {
  if (state === "ready") return "音频已解锁，等待启动实时动作...";
  if (state === "generating") return "法官正在通过大模型实时生成第一句话...";
  if (state === "broadcasting") return "法官第一句话实时播报中";
  if (state === "finalizing") return "语音播报完成，正在校验并保存 V2 语音资产...";
  if (state === "awaiting_observation") return "第一句话已完成，等待本步验收";
  if (state === "failed") return "本次实时动作已明确失败";
  return "正在读取当前实时状态...";
}
