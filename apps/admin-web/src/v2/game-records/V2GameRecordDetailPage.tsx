import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Col from "antd/es/grid/col";
import Input from "antd/es/input";
import Modal from "antd/es/modal";
import Row from "antd/es/grid/row";
import Space from "antd/es/space";
import Statistic from "antd/es/statistic";
import Tabs from "antd/es/tabs";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import {
  AdminError,
  AdminLoading,
  AdminPage,
  AdminPageHeader,
} from "@/components/admin/AdminPage";
import { useAdminSession } from "@/features/auth/session-context";
import { readV2GameRecord, stopV2Game } from "@/v2/game-records/api";
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";

const DEFAULT_STOP_REASON = "人工打断异常对局，避免继续消耗 API 额度";
const ACTIVE_STATES = new Set([
  "ready",
  "generating",
  "broadcasting",
  "finalizing",
  "awaiting_observation",
]);

export default function V2GameRecordDetailPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { session } = useAdminSession();
  const { gameId = "" } = useParams();
  const [stopDialogOpen, setStopDialogOpen] = useState(false);
  const [stopReason, setStopReason] = useState(DEFAULT_STOP_REASON);
  const query = useQuery({
    enabled: Boolean(gameId),
    queryFn: ({ signal }) => readV2GameRecord(gameId, signal),
    queryKey: v2GameRecordKeys.detail(gameId),
  });
  const stopMutation = useMutation({
    mutationFn: () =>
      stopV2Game(gameId, stopReason.trim(), session?.csrf_token ?? ""),
    onSuccess: async () => {
      setStopDialogOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: v2GameRecordKeys.detail(gameId),
        }),
        queryClient.invalidateQueries({ queryKey: v2GameRecordKeys.all }),
      ]);
    },
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
  const activeRun = game.runs.find(
    (run) => run.run_id === game.current_run_id,
  );
  const canControl =
    session?.permissions.includes("*") ||
    session?.permissions.includes("runs.control");
  const canStop =
    canControl &&
    ACTIVE_STATES.has(game.status) &&
    activeRun?.stop_requested_at === null;
  return (
    <AdminPage className="v2-game-record-detail-page">
      <AdminPageHeader
        description={`${game.game_id} · ${game.current_run_id}`}
        extra={
          <Space>
            {canStop ? (
              <Button
                danger
                onClick={() => {
                  stopMutation.reset();
                  setStopReason(DEFAULT_STOP_REASON);
                  setStopDialogOpen(true);
                }}
              >
                打断整局
              </Button>
            ) : null}
            <Button onClick={() => navigate("/v2/operations/games")}>
              返回列表
            </Button>
          </Space>
        }
        kicker="LIVE V2 RECORD"
        title={game.title}
      />

      {game.status === "canceled" || activeRun?.stop_requested_at ? (
        <Alert
          message={
            game.status === "canceled"
              ? "对局已由管理员打断"
              : "打断请求已提交"
          }
          description="模型与语音流不会继续推进；移动端会停止当前播放并进入安全终态。"
          showIcon
          type="warning"
        />
      ) : null}

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
                      <Typography.Text type="secondary">{presentation.audience} · action {presentation.action_id ?? "—"} · activation {presentation.activation_id ?? "—"} · speech {presentation.speech_id} · segment {presentation.segment_index}</Typography.Text>
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
                      <Typography.Text type="secondary">{voice.audience} · action {voice.action_id} · activation {voice.activation_id ?? "—"} · {voice.sample_rate} Hz · {voice.sample_count ?? 0} samples · {voice.duration_ms ?? 0} ms</Typography.Text>
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
            {
              children: (
                <div>
                  <RecordSection label="冻结能力快照" records={[game.ability_snapshot]} />
                  <RecordSection label="行动窗口" records={game.action_windows} />
                  <RecordSection label="能力实例" records={game.ability_instances} />
                  <RecordSection label="能力激活与决策" records={game.ability_activations} />
                  <RecordSection label="效果意图" records={game.effect_intents} />
                  <RecordSection label="私密知识" records={game.knowledge_facts} />
                  <RecordSection label="玩家状态" records={game.player_states} />
                </div>
              ),
              key: "ability-runtime",
              label: `能力运行时 (${game.ability_activations.length})`,
            },
          ]}
        />
      </Card>

      <Modal
        cancelText="取消"
        confirmLoading={stopMutation.isPending}
        destroyOnHidden
        okButtonProps={{
          danger: true,
          disabled: stopReason.trim().length < 3,
        }}
        okText="确认打断"
        onCancel={() => {
          if (!stopMutation.isPending) setStopDialogOpen(false);
        }}
        onOk={() => stopMutation.mutate()}
        open={stopDialogOpen}
        title="确认打断整局"
      >
        <Typography.Paragraph>
          此操作不会删除记录，但会立即停止新的模型请求、关闭当前模型/TTS
          流，并让普通直播和上帝视角停止播放。
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary">
          对局 {game.game_id} · 运行 {game.current_run_id}
        </Typography.Paragraph>
        <Typography.Text strong>操作原因</Typography.Text>
        <Input.TextArea
          aria-label="操作原因"
          disabled={stopMutation.isPending}
          maxLength={500}
          onChange={(event) => setStopReason(event.target.value)}
          rows={3}
          value={stopReason}
        />
        {stopMutation.isError ? (
          <Alert
            message="打断请求未成功"
            description={
              isAdminApiError(stopMutation.error)
                ? stopMutation.error.message
                : "暂时无法打断对局，请稍后重试。"
            }
            showIcon
            type="error"
          />
        ) : null}
      </Modal>
    </AdminPage>
  );
}

function RecordSection({
  label,
  records,
}: {
  label: string;
  records: Array<Record<string, unknown>>;
}) {
  return (
    <section>
      <Typography.Title level={5}>{label} ({records.length})</Typography.Title>
      <ol className="v2-record-sequence ant-v2-record-sequence">
        {records.map((record, index) => (
          <li key={`${label}-${index}`}>
            <Typography.Text code>{JSON.stringify(record)}</Typography.Text>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Col lg={6} sm={12} xs={24}>
      <Card><Statistic title={label} value={value} /></Card>
    </Col>
  );
}
