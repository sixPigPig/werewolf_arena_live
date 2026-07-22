import { useQuery } from "@tanstack/react-query";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Col from "antd/es/grid/col";
import Row from "antd/es/grid/row";
import Statistic from "antd/es/statistic";
import Tabs from "antd/es/tabs";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { useNavigate, useParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import {
  AdminError,
  AdminLoading,
  AdminPage,
  AdminPageHeader,
} from "@/components/admin/AdminPage";
import { readV2GameRecord } from "@/v2/game-records/api";
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";

export default function V2GameRecordDetailPage() {
  const navigate = useNavigate();
  const { gameId = "" } = useParams();
  const query = useQuery({
    enabled: Boolean(gameId),
    queryFn: ({ signal }) => readV2GameRecord(gameId, signal),
    queryKey: v2GameRecordKeys.detail(gameId),
  });

  if (query.isPending) {
    return <AdminLoading message="正在读取 V2 对局记录..." />;
  }
  if (query.isError) {
    return (
      <AdminError
        description={isAdminApiError(query.error) ? query.error.message : "记录服务暂时不可用。"}
        title="无法读取 V2 对局"
      />
    );
  }

  const game = query.data;
  return (
    <AdminPage className="v2-game-record-detail-page">
      <AdminPageHeader
        description={`${game.game_id} · ${game.current_run_id}`}
        extra={<Button onClick={() => navigate("/v2/operations/games")}>返回列表</Button>}
        kicker="LIVE V2 RECORD"
        title={game.title}
      />

      <Row gutter={[12, 12]}>
        <Metric label="状态" value={game.status} />
        <Metric label="事实序列" value={`#${game.last_record_seq}`} />
        <Metric label="展示序列" value={`#${game.last_presentation_seq}`} />
        <Metric label="运行" value={String(game.runs.length)} />
      </Row>

      <Card>
        <Tabs
          items={[
            {
              children: (
                <ol className="v2-record-sequence ant-v2-record-sequence">
                  {game.events.map((event) => (
                    <li key={event.event_id}>
                      <Tag color="blue">#{event.record_seq}</Tag>
                      <Typography.Text strong>{event.event_type}</Typography.Text>
                      <Typography.Text type="secondary">{event.run_id} · payload v{event.payload_schema_version}</Typography.Text>
                      <Typography.Text code>{JSON.stringify(event.payload)}</Typography.Text>
                    </li>
                  ))}
                </ol>
              ),
              key: "events",
              label: `事实序列 (${game.events.length})`,
            },
            {
              children: (
                <ol className="v2-record-sequence ant-v2-record-sequence">
                  {game.presentations.map((presentation) => (
                    <li key={presentation.presentation_id}>
                      <Tag color="purple">#{presentation.presentation_seq}</Tag>
                      <Typography.Text strong>{presentation.actor_kind} · {presentation.state}</Typography.Text>
                      <Typography.Paragraph>{presentation.subtitle_text}</Typography.Paragraph>
                      <Typography.Text type="secondary">action {presentation.action_id ?? "—"} · speech {presentation.speech_id} · segment {presentation.segment_index}</Typography.Text>
                    </li>
                  ))}
                </ol>
              ),
              key: "presentations",
              label: `展示序列 (${game.presentations.length})`,
            },
            {
              children: (
                <ol className="v2-record-sequence ant-v2-record-sequence">
                  {game.voice_assets.map((voice) => (
                    <li key={voice.voice_asset_id}>
                      <Tag color={voice.state === "ready" ? "success" : "processing"}>{voice.state}</Tag>
                      <Typography.Text strong>{voice.voice_asset_id}</Typography.Text>
                      <Typography.Text type="secondary">action {voice.action_id} · {voice.sample_rate} Hz · {voice.sample_count ?? 0} samples · {voice.duration_ms ?? 0} ms</Typography.Text>
                      <Typography.Text code>pcm sha256 {voice.pcm_sha256 ?? "—"}</Typography.Text>
                      {voice.audio_url ? (
                        <audio controls preload="none" src={voice.audio_url}>当前浏览器不支持播放 V2 保存语音。</audio>
                      ) : (
                        <Typography.Text type="secondary">语音资产尚未保存完成。</Typography.Text>
                      )}
                    </li>
                  ))}
                </ol>
              ),
              key: "voices",
              label: `保存语音 (${game.voice_assets.length})`,
            },
          ]}
        />
      </Card>
    </AdminPage>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Col lg={6} sm={12} xs={24}>
      <Card><Statistic title={label} value={value} /></Card>
    </Col>
  );
}
