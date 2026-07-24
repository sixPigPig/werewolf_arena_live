import {
  CheckCircleFilled,
  CloseCircleFilled,
  DatabaseOutlined,
  LoadingOutlined,
  SearchOutlined,
  SoundOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import Button from "antd/es/button";
import Descriptions from "antd/es/descriptions";
import Drawer from "antd/es/drawer";
import Empty from "antd/es/empty";
import Flex from "antd/es/flex";
import Input from "antd/es/input";
import Select from "antd/es/select";
import Space from "antd/es/space";
import Switch from "antd/es/switch";
import Tabs from "antd/es/tabs";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import {
  AdminError,
  AdminLoading,
  AdminPage,
} from "@/components/admin/AdminPage";
import { readV2GameRecord } from "@/v2/game-records/api";
import {
  buildV2Timeline,
  formatClock,
  formatDuration,
  groupV2Phases,
  prettyJson,
  type V2TimelineItem,
} from "@/v2/game-records/presentation";
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";
import {
  ReadableModelInput,
  ReadableModelOutput,
  ReadableRawEvents,
} from "@/v2/game-records/request-presentation";
import type { V2GameRecordDetail } from "@/v2/game-records/types";

type CategoryFilter = "all" | "model" | "milestone";
type StatusFilter = "all" | "running" | "succeeded" | "failed";

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
        description={
          isAdminApiError(query.error)
            ? query.error.message
            : "记录服务暂时不可用。"
        }
        title="无法读取 V2 对局"
      />
    );
  }

  return (
    <V2GameRecordWorkspace
      game={query.data}
      onBack={() => navigate("/v2/operations/games")}
    />
  );
}

function V2GameRecordWorkspace({
  game,
  onBack,
}: {
  game: V2GameRecordDetail;
  onBack: () => void;
}) {
  const timeline = useMemo(() => buildV2Timeline(game), [game]);
  const phases = useMemo(
    () => groupV2Phases(timeline, game.phase_id),
    [game.phase_id, timeline],
  );
  const [selectedId, setSelectedId] = useState("");
  const [phaseFilter, setPhaseFilter] = useState("all");
  const [actorFilter, setActorFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] =
    useState<CategoryFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [modelOnly, setModelOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [rawDataOpen, setRawDataOpen] = useState(false);
  const [requestDrawerOpen, setRequestDrawerOpen] = useState(false);

  const actorOptions = useMemo(
    () => [
      { label: "全部演员", value: "all" },
      ...Array.from(
        new Map(
          timeline.map((item) => [
            `${item.actorKind}:${item.actorId}`,
            item.actorLabel,
          ]),
        ),
      ).map(([value, label]) => ({ label, value })),
    ],
    [timeline],
  );
  const filteredItems = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return timeline.filter((item) => {
      if (phaseFilter !== "all" && item.phaseId !== phaseFilter) return false;
      if (
        actorFilter !== "all" &&
        `${item.actorKind}:${item.actorId}` !== actorFilter
      ) {
        return false;
      }
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (categoryFilter === "model" && !item.modelRequest) return false;
      if (categoryFilter === "milestone" && item.kind !== "milestone") {
        return false;
      }
      if (modelOnly && !item.modelRequest) return false;
      if (!normalizedSearch) return true;
      return [
        item.label,
        item.actionId,
        item.actorLabel,
        item.modelRequest?.attempt_id,
        item.modelRequest?.provider_request_id,
        item.modelRequest?.model_id,
      ]
        .filter(Boolean)
        .some((value) =>
          String(value).toLowerCase().includes(normalizedSearch),
        );
    });
  }, [
    actorFilter,
    categoryFilter,
    modelOnly,
    phaseFilter,
    search,
    statusFilter,
    timeline,
  ]);
  const visiblePhases = useMemo(
    () => groupV2Phases(filteredItems, game.phase_id),
    [filteredItems, game.phase_id],
  );
  const selected = timeline.find((item) => item.id === selectedId) ?? null;

  const run = game.runs.find((item) => item.run_id === game.current_run_id);
  const duration = run?.started_at
    ? Math.max(
        0,
        Date.parse(run.completed_at ?? game.updated_at) -
          Date.parse(run.started_at),
      )
    : null;
  const failureCount = game.model_requests.filter(
    (item) => item.status === "failed",
  ).length;

  return (
    <AdminPage className="v2-game-record-detail-page">
      <header className="v2-record-heading">
        <div>
          <Typography.Text className="ant-admin-page-kicker">
            LIVE V2 RECORD
          </Typography.Text>
          <Flex align="center" gap={8}>
            <Typography.Title level={1}>{game.title}</Typography.Title>
            <Tag color={statusColor(game.status)}>
              {statusLabel(game.status)}
            </Tag>
          </Flex>
          <Typography.Paragraph>
            {game.game_id} · {game.current_run_id}
          </Typography.Paragraph>
        </div>
        <section aria-label="对局摘要" className="v2-record-heading-metrics">
          <SummaryMetric label="总时长" value={formatDuration(duration)} />
          <SummaryMetric
            label="模型请求"
            value={String(game.model_requests.length)}
          />
          <SummaryMetric label="失败" value={String(failureCount)} />
          <SummaryMetric
            label="当前阶段"
            value={
              phases.find((phase) => phase.phaseId === game.phase_id)?.label ??
              game.phase_id
            }
          />
        </section>
        <Button onClick={onBack}>返回列表</Button>
      </header>

      <section aria-label="流程筛选" className="v2-record-toolbar">
        <Select
          aria-label="筛选阶段"
          onChange={setPhaseFilter}
          options={[
            { label: "全部阶段", value: "all" },
            ...phases.map((phase) => ({
              label: phase.label,
              value: phase.phaseId,
            })),
          ]}
          value={phaseFilter}
        />
        <Select
          aria-label="筛选演员"
          onChange={setActorFilter}
          options={actorOptions}
          value={actorFilter}
        />
        <Select<CategoryFilter>
          aria-label="筛选事件类别"
          onChange={setCategoryFilter}
          options={[
            { label: "全部类别", value: "all" },
            { label: "模型调用", value: "model" },
            { label: "流程里程碑", value: "milestone" },
          ]}
          value={categoryFilter}
        />
        <Select<StatusFilter>
          aria-label="筛选状态"
          onChange={setStatusFilter}
          options={[
            { label: "全部状态", value: "all" },
            { label: "进行中", value: "running" },
            { label: "成功", value: "succeeded" },
            { label: "失败", value: "failed" },
          ]}
          value={statusFilter}
        />
        <Flex align="center" className="v2-model-only-filter" gap={8}>
          <Switch
            aria-label="仅看模型请求"
            checked={modelOnly}
            onChange={setModelOnly}
          />
          <Typography.Text>仅看模型请求</Typography.Text>
        </Flex>
        <Input
          allowClear
          aria-label="搜索流程"
          onChange={(event) => setSearch(event.target.value)}
          placeholder="搜索动作 / 请求 ID / 内容关键词"
          prefix={<SearchOutlined />}
          value={search}
        />
        <Button
          icon={<DatabaseOutlined />}
          onClick={() => setRawDataOpen(true)}
        >
          底层数据
        </Button>
      </section>

      <section className="v2-record-workspace">
        <PhaseRail
          onSelect={(phaseId) =>
            setPhaseFilter((current) =>
              current === phaseId ? "all" : phaseId,
            )
          }
          phases={phases}
          selectedPhaseId={phaseFilter}
        />
        <ActionTimeline
          items={filteredItems}
          onSelect={(id) => {
            setSelectedId(id);
            setRequestDrawerOpen(true);
          }}
          phases={visiblePhases}
          selectedId={selected?.id ?? ""}
        />
      </section>

      <RequestDetailsDrawer
        item={selected}
        onClose={() => setRequestDrawerOpen(false)}
        open={requestDrawerOpen}
      />
      <RawDataDrawer
        game={game}
        onClose={() => setRawDataOpen(false)}
        open={rawDataOpen}
      />
    </AdminPage>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <span className="v2-record-summary-metric">
      <Typography.Text type="secondary">{label}</Typography.Text>
      <Typography.Text strong>{value}</Typography.Text>
    </span>
  );
}

function PhaseRail({
  phases,
  selectedPhaseId,
  onSelect,
}: {
  phases: ReturnType<typeof groupV2Phases>;
  selectedPhaseId: string;
  onSelect: (phaseId: string) => void;
}) {
  return (
    <aside className="v2-phase-rail">
      <Typography.Title level={5}>阶段进度</Typography.Title>
      <nav aria-label="对局阶段">
        {phases.map((phase) => (
          <button
            aria-current={
              selectedPhaseId === phase.phaseId ? "location" : undefined
            }
            className={
              selectedPhaseId === phase.phaseId
                ? "v2-phase-button is-selected"
                : "v2-phase-button"
            }
            key={phase.phaseId}
            onClick={() => onSelect(phase.phaseId)}
            type="button"
          >
            <span>
              <span
                className={`v2-phase-status is-${phaseStatus(
                  phase.failureCount,
                  phase.isCurrent,
                )}`}
              >
                <StatusIcon
                  status={phaseStatus(phase.failureCount, phase.isCurrent)}
                />
              </span>
              <strong>{phase.label}</strong>
            </span>
            <small>
              {phase.items.length} 步 · {phase.modelRequestCount} 次模型
            </small>
          </button>
        ))}
      </nav>
    </aside>
  );
}

function ActionTimeline({
  items,
  phases,
  selectedId,
  onSelect,
}: {
  items: V2TimelineItem[];
  phases: ReturnType<typeof groupV2Phases>;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <main className="v2-action-timeline">
      <header>
        <Typography.Title level={5}>动作时间线（按阶段）</Typography.Title>
        <Typography.Text type="secondary">
          {items.length} 个可读步骤
        </Typography.Text>
      </header>
      <div className="v2-action-table-header" aria-hidden="true">
        <span>时间</span>
        <span>演员 / 角色</span>
        <span>动作</span>
        <span>受众</span>
        <span>结果</span>
        <span>模型</span>
        <span>耗时</span>
      </div>
      {phases.length ? (
        phases.map((phase) => (
          <section className="v2-action-phase" key={phase.phaseId}>
            <header>
              <strong>{phase.label}</strong>
              <Typography.Text type="secondary">
                {phase.items.length} 步
              </Typography.Text>
            </header>
            <ol>
              {phase.items.map((item) => (
                <li className={item.id === selectedId ? "is-selected" : ""} key={item.id}>
                  <button
                    aria-label={`查看 ${item.actorLabel} ${item.label}`}
                    className="v2-action-row"
                    onClick={() => onSelect(item.id)}
                    type="button"
                  >
                    <time>{formatClock(item.startedAt)}</time>
                    <span>{item.actorLabel}</span>
                    <strong>{item.label}</strong>
                    <span>{audienceLabel(item.audience)}</span>
                    <span className={`is-${item.status}`}>
                      <StatusIcon status={item.status} />
                      {statusLabel(item.status)}
                    </span>
                    <span>{item.modelRequest?.model_id ?? "—"}</span>
                    <span>{formatDuration(item.durationMs)}</span>
                  </button>
                  {item.id === selectedId ? (
                    <LifecycleStrip item={item} />
                  ) : null}
                </li>
              ))}
            </ol>
          </section>
        ))
      ) : (
        <Empty
          description="没有符合筛选条件的流程步骤"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      )}
    </main>
  );
}

function LifecycleStrip({ item }: { item: V2TimelineItem }) {
  const requestStarted = item.events.find(
    (event) => event.event_type === "model_request_started",
  );
  const response = item.events.find(
    (event) =>
      event.event_type === "model_response_received" ||
      event.event_type === "model_first_token_received",
  );
  const presentation = item.events.find(
    (event) => event.event_type === "speech_segment_committed",
  );
  const steps = [
    {
      label: "动作上下文",
      at: item.startedAt,
      detail: `事实 #${item.firstRecordSeq}`,
    },
    requestStarted
      ? {
          label: "模型请求",
          at: requestStarted.created_at,
          detail: item.modelRequest?.attempt_id ?? "已发起",
        }
      : null,
    response
      ? {
          label: "模型响应",
          at: response.created_at,
          detail: formatDuration(item.modelRequest?.first_token_ms ?? null),
        }
      : null,
    presentation
      ? {
          label: "展示 / 语音",
          at: presentation.created_at,
          detail: item.voiceAsset?.state ?? item.presentation?.state ?? "已提交",
        }
      : null,
  ].filter(Boolean) as Array<{ label: string; at: string; detail: string }>;

  return (
    <div aria-label="动作生命周期" className="v2-lifecycle-strip">
      {steps.map((step) => (
        <div className="v2-lifecycle-step" key={step.label}>
          <Typography.Text strong>{step.label}</Typography.Text>
          <time>{formatClock(step.at)}</time>
          <Typography.Text ellipsis type="secondary">
            {step.detail}
          </Typography.Text>
        </div>
      ))}
    </div>
  );
}

function RequestDetailsDrawer({
  item,
  open,
  onClose,
}: {
  item: V2TimelineItem | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer
      onClose={onClose}
      open={open && item !== null}
      rootClassName="v2-request-drawer"
      size="large"
      title={
        item ? (
          <div className="v2-request-drawer-title">
            <Space size={8} wrap>
              <Typography.Text strong>{item.label}</Typography.Text>
              <Tag color={statusColor(item.status)}>
                {statusLabel(item.status)}
              </Tag>
            </Space>
            <Typography.Text
              className="v2-request-drawer-id"
              copyable
              type="secondary"
            >
              {item.modelRequest?.attempt_id ?? item.actionId ?? item.id}
            </Typography.Text>
          </div>
        ) : (
          "请求详情"
        )
      }
    >
      {item ? (
        <div className="v2-request-drawer-content">
          <Tabs
            items={[
              {
                children: <InspectorOverview item={item} />,
                key: "overview",
                label: "概览",
              },
              {
                children: (
                  <ReadableModelInput request={item.modelRequest} />
                ),
                key: "input",
                label: "模型输入",
              },
              {
                children: (
                  <ReadableModelOutput request={item.modelRequest} />
                ),
                key: "output",
                label: "模型输出",
              },
              {
                children: <ReadableRawEvents events={item.events} />,
                key: "events",
                label: `原始事件 (${item.events.length})`,
              },
            ]}
            key={item.id}
          />
        </div>
      ) : null}
    </Drawer>
  );
}

function InspectorOverview({ item }: { item: V2TimelineItem }) {
  const request = item.modelRequest;
  return (
    <div className="v2-inspector-panel">
      <Descriptions
        column={2}
        items={[
          { key: "model", label: "模型", children: request?.model_id ?? "—" },
          {
            key: "provider",
            label: "提供商",
            children: request?.model_provider ?? "—",
          },
          {
            key: "status",
            label: "状态",
            children: statusLabel(request?.status ?? item.status),
          },
          {
            key: "privacy",
            label: "隐私级别",
            children: audienceLabel(item.audience),
          },
          {
            key: "first-token",
            label: "首 Token",
            children: formatDuration(request?.first_token_ms ?? null),
          },
          {
            key: "total",
            label: "模型总耗时",
            children: formatDuration(request?.completed_ms ?? null),
          },
          {
            key: "provider-request",
            label: "供应商请求 ID",
            span: 2,
            children: request?.provider_request_id ? (
              <Typography.Text copyable>
                {request.provider_request_id}
              </Typography.Text>
            ) : (
              "—"
            ),
          },
          {
            key: "action",
            label: "动作 ID",
            span: 2,
            children: item.actionId ? (
              <Typography.Text copyable>{item.actionId}</Typography.Text>
            ) : (
              "—"
            ),
          },
          {
            key: "actor",
            label: "演员",
            children: item.actorLabel,
          },
          {
            key: "type",
            label: "动作",
            children: item.label,
          },
        ]}
        size="small"
      />
      {item.objective ? (
        <section>
          <Typography.Text strong>动作目标</Typography.Text>
          <Typography.Paragraph>{item.objective}</Typography.Paragraph>
        </section>
      ) : null}
      {item.presentation ? (
        <section>
          <Typography.Text strong>展示结果</Typography.Text>
          <Typography.Paragraph className="v2-result-copy">
            {item.presentation.subtitle_text}
          </Typography.Paragraph>
        </section>
      ) : null}
      {item.voiceAsset?.audio_url ? (
        <section>
          <Typography.Text strong>
            <SoundOutlined /> 保存语音
          </Typography.Text>
          <audio controls preload="none" src={item.voiceAsset.audio_url}>
            当前浏览器不支持播放 V2 保存语音。
          </audio>
        </section>
      ) : null}
      {request?.failure_code ? (
        <Alert
          description={request.failure_code}
          showIcon
          title={request.failure_kind ?? "模型请求失败"}
          type="error"
        />
      ) : null}
    </div>
  );
}

function RawDataDrawer({
  game,
  open,
  onClose,
}: {
  game: V2GameRecordDetail;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer
      onClose={onClose}
      open={open}
      size="large"
      title="V2 底层数据"
    >
      <Tabs
        items={[
          {
            children: (
              <>
                <RecordSection
                  label="冻结能力快照"
                  records={[game.ability_snapshot]}
                />
                <RecordSection
                  label="整局状态"
                  records={game.match_state ? [game.match_state] : []}
                />
                <RecordSection
                  label="行动窗口"
                  records={game.action_windows}
                />
                <RecordSection
                  label="能力实例"
                  records={game.ability_instances}
                />
                <RecordSection
                  label="能力激活与决策"
                  records={game.ability_activations}
                />
                <RecordSection
                  label="效果意图"
                  records={game.effect_intents}
                />
                <RecordSection
                  label="私密知识"
                  records={game.knowledge_facts}
                />
                <RecordSection
                  label="玩家状态"
                  records={game.player_states}
                />
              </>
            ),
            key: "runtime",
            label: "能力运行时",
          },
          {
            children: (
              <>
                <RecordSection
                  label="规则快照"
                  records={[game.rule_snapshot]}
                />
                <RecordSection
                  label="玩家快照"
                  records={game.players_snapshot}
                />
              </>
            ),
            key: "snapshots",
            label: "冻结快照",
          },
          {
            children: (
              <RecordSection label="保存语音" records={game.voice_assets} />
            ),
            key: "voices",
            label: `保存语音 (${game.voice_assets.length})`,
          },
        ]}
      />
    </Drawer>
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
    <section className="v2-raw-record-section">
      <Typography.Title level={5}>
        {label} ({records.length})
      </Typography.Title>
      {records.length ? (
        records.map((record, index) => (
          <pre key={`${label}-${index}`}>{prettyJson(record)}</pre>
        ))
      ) : (
        <Typography.Text type="secondary">暂无记录</Typography.Text>
      )}
    </section>
  );
}

function StatusIcon({
  status,
}: {
  status: "running" | "succeeded" | "failed";
}) {
  if (status === "failed") return <CloseCircleFilled />;
  if (status === "running") return <LoadingOutlined spin />;
  return <CheckCircleFilled />;
}

function audienceLabel(audience: string) {
  if (audience === "all" || audience === "public") return "公开";
  if (audience === "god_view") return "上帝视角";
  return "私密";
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    waiting_to_start: "等待开始",
    ready: "就绪",
    generating: "生成中",
    broadcasting: "播报中",
    finalizing: "收尾中",
    awaiting_observation: "等待观察",
    running: "进行中",
    succeeded: "成功",
    failed: "失败",
  };
  return labels[status] ?? status;
}

function statusColor(status: string) {
  if (status === "failed") return "error";
  if (
    status === "generating" ||
    status === "broadcasting" ||
    status === "finalizing" ||
    status === "running"
  ) {
    return "processing";
  }
  if (status === "succeeded" || status === "awaiting_observation") {
    return "success";
  }
  return "default";
}

function phaseStatus(
  failureCount: number,
  isCurrent: boolean,
): "running" | "succeeded" | "failed" {
  if (failureCount > 0) return "failed";
  return isCurrent ? "running" : "succeeded";
}
