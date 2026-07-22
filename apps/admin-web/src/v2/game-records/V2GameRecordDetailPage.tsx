import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { readV2GameRecord } from "@/v2/game-records/api";
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";

export default function V2GameRecordDetailPage() {
  const { gameId = "" } = useParams();
  const query = useQuery({
    enabled: Boolean(gameId),
    queryFn: ({ signal }) => readV2GameRecord(gameId, signal),
    queryKey: v2GameRecordKeys.detail(gameId),
  });

  if (query.isPending) {
    return <div className="game-detail-loading" role="status">正在读取 V2 对局记录...</div>;
  }
  if (query.isError) {
    return (
      <section className="game-detail-load-error" role="alert">
        <h1>无法读取 V2 对局</h1>
        <p>{isAdminApiError(query.error) ? query.error.message : "记录服务暂时不可用。"}</p>
        <Link to="/v2/operations/games">返回 V2 对局记录</Link>
      </section>
    );
  }

  const game = query.data;
  return (
    <div className="admin-page v2-game-record-detail-page">
      <header className="page-heading game-detail-heading">
        <div>
          <span className="page-kicker">LIVE V2 RECORD</span>
          <h1>{game.title}</h1>
          <p>{game.game_id} · {game.current_run_id}</p>
        </div>
        <Link className="admin-secondary-button" to="/v2/operations/games">返回列表</Link>
      </header>

      <div className="game-detail-metrics">
        <article><span>状态</span><strong>{game.status}</strong><small>schema v{game.record_schema_version}</small></article>
        <article><span>事实序列</span><strong>#{game.last_record_seq}</strong><small>{game.events.length} 条不可变事实</small></article>
        <article><span>展示序列</span><strong>#{game.last_presentation_seq}</strong><small>{game.presentations.length} 条正式展示</small></article>
        <article><span>运行</span><strong>{game.runs.length}</strong><small>{game.current_run_id}</small></article>
      </div>

      <div className="game-detail-grid v2-record-grid">
        <section className="game-detail-panel" aria-labelledby="v2-events-title">
          <div className="game-panel-heading"><div><span>RECORD SEQ</span><h2 id="v2-events-title">事实序列</h2></div><small>{game.events.length} 条</small></div>
          <ol className="v2-record-sequence">
            {game.events.map((event) => (
              <li key={event.event_id}>
                <strong>#{event.record_seq} · {event.event_type}</strong>
                <small>{event.run_id} · payload v{event.payload_schema_version}</small>
                <code>{JSON.stringify(event.payload)}</code>
              </li>
            ))}
          </ol>
        </section>
        <section className="game-detail-panel" aria-labelledby="v2-presentations-title">
          <div className="game-panel-heading"><div><span>PRESENTATION SEQ</span><h2 id="v2-presentations-title">展示序列</h2></div><small>{game.presentations.length} 条</small></div>
          <ol className="v2-record-sequence">
            {game.presentations.map((presentation) => (
              <li key={presentation.presentation_id}>
                <strong>#{presentation.presentation_seq} · {presentation.actor_kind} · {presentation.state}</strong>
                <p>{presentation.subtitle_text}</p>
                <small>action {presentation.action_id ?? "—"} · speech {presentation.speech_id} · segment {presentation.segment_index} · voice {presentation.voice_asset_id ?? "—"}</small>
              </li>
            ))}
          </ol>
        </section>
        <section className="game-detail-panel" aria-labelledby="v2-voices-title">
          <div className="game-panel-heading"><div><span>VOICE ASSETS</span><h2 id="v2-voices-title">保存语音</h2></div><small>{game.voice_assets.length} 条</small></div>
          <ol className="v2-record-sequence">
            {game.voice_assets.map((voice) => (
              <li key={voice.voice_asset_id}>
                <strong>{voice.voice_asset_id} · {voice.state}</strong>
                <small>action {voice.action_id} · {voice.sample_rate} Hz · {voice.sample_count ?? 0} samples · {voice.duration_ms ?? 0} ms</small>
                <code>pcm sha256 {voice.pcm_sha256 ?? "—"}</code>
                {voice.audio_url ? (
                  <audio controls preload="none" src={voice.audio_url}>
                    当前浏览器不支持播放 V2 保存语音。
                  </audio>
                ) : (
                  <p>语音资产尚未保存完成。</p>
                )}
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
