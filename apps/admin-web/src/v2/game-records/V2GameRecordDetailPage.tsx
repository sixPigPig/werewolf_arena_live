import {
  CheckCircleFilled,
  CloseCircleFilled,
  DatabaseOutlined,
  LoadingOutlined,
  MinusCircleFilled,
  SearchOutlined,
  SoundOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import AntApp from "antd/es/app";
import Button from "antd/es/button";
import Collapse from "antd/es/collapse";
import Descriptions from "antd/es/descriptions";
import Drawer from "antd/es/drawer";
import Empty from "antd/es/empty";
import Flex from "antd/es/flex";
import Input from "antd/es/input";
import Modal from "antd/es/modal";
import Select from "antd/es/select";
import Space from "antd/es/space";
import Steps, { type StepsProps } from "antd/es/steps";
import Switch from "antd/es/switch";
import Table, { type ColumnsType } from "antd/es/table";
import Tabs from "antd/es/tabs";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import {
  AdminError,
  AdminLoading,
  AdminPage,
} from "@/components/admin/AdminPage";
import { useAdminSession } from "@/features/auth/session-context";
import {
  isLiveV2StatusActive,
  liveRefreshInterval,
} from "@/v2/game-records/live-refresh";
import {
  buildV2RoundSummaries,
  buildV2Timeline,
  formatClock,
  formatDuration,
  groupV2Phases,
  prettyJson,
  type V2TimelineItem,
} from "@/v2/game-records/presentation";
import { V2OmniscientSituationPanel } from "@/v2/game-records/V2OmniscientSituationPanel";
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";
import {
  listV2GameEvents,
  listV2ModelRequests,
  readV2GameRecordSummary,
  readV2ModelRequest,
  retryV2ModelAction,
  stopV2Game,
} from "@/v2/game-records/api";
import { adminOperationErrorDescription } from "@/lib/admin-notification";
import type {
  V2GameRecordEvent,
  V2GameRecordDetail,
  V2ModelRequest,
  V2ModelRequestSummary,
} from "@/v2/game-records/types";
import {
  ReadableModelInput,
  ReadableModelOutput,
  ReadableRawEvents,
} from "@/v2/game-records/request-presentation";

type CategoryFilter = "all" | "model" | "template" | "milestone";
type StatusFilter = "all" | "running" | "succeeded" | "failed";
const DEFAULT_STOP_REASON = "人工打断异常对局，避免继续消耗 API 额度";
const DEFAULT_RETRY_REASON = "模型链路已恢复，继续执行同一冻结动作";

export default function V2GameRecordDetailPage() {
  const navigate = useNavigate();
  const { gameId = "" } = useParams();
  const queryClient = useQueryClient();
  const query = useQuery({
    enabled: Boolean(gameId),
    queryFn: ({ signal }) => readV2GameRecordSummary(gameId, signal),
    queryKey: v2GameRecordKeys.detail(gameId),
    refetchInterval: (currentQuery) =>
      liveRefreshInterval(currentQuery.state.data?.status),
    refetchIntervalInBackground: false,
  });
  const timeline = useIncrementalTimeline(
    gameId,
    query.data?.last_record_seq ?? 0,
    query.data !== undefined,
  );
  const game = useMemo<V2GameRecordDetail | null>(
    () =>
      query.data
        ? {
            ...query.data,
            events: timeline.events,
            model_requests: timeline.modelRequests,
          }
        : null,
    [query.data, timeline.events, timeline.modelRequests],
  );

  useEffect(
    () => () => {
      queryClient.removeQueries({
        queryKey: v2GameRecordKeys.detail(gameId),
      });
    },
    [gameId, queryClient],
  );

  if (query.isPending || timeline.isInitialLoading) {
    return <AdminLoading message="正在读取 V2 对局记录..." />;
  }
  if (query.isError || timeline.error) {
    const error = query.error ?? timeline.error;
    return (
      <AdminError
        description={
          isAdminApiError(error)
            ? error.message
            : "记录服务暂时不可用。"
        }
        title="无法读取 V2 对局"
      />
    );
  }
  if (game === null) {
    return <AdminLoading message="正在读取 V2 对局记录..." />;
  }

  return (
    <V2GameRecordWorkspace
      game={game}
      isRefreshing={query.isFetching || timeline.isFetching}
      onBack={() => navigate("/v2/operations/games")}
      refreshedAt={query.dataUpdatedAt}
    />
  );
}

function useIncrementalTimeline(
  gameId: string,
  targetRecordSeq: number,
  enabled: boolean,
) {
  const [state, setState] = useState(() => emptyTimelineState(gameId));
  const cursors = useRef({
    event: 0,
    gameId,
    modelRequest: 0,
  });
  const current =
    state.gameId === gameId ? state : emptyTimelineState(gameId);

  useEffect(() => {
    if (!gameId) return;
    if (!enabled) return;
    if (cursors.current.gameId !== gameId) {
      cursors.current = { event: 0, gameId, modelRequest: 0 };
    }
    const controller = new AbortController();
    let active = true;

    async function loadEvents() {
      let cursor = cursors.current.event;
      while (active && cursor < targetRecordSeq) {
        const page = await listV2GameEvents(
          gameId,
          cursor,
          controller.signal,
        );
        if (!active || cursors.current.gameId !== gameId) return;
        if (page.items.length) {
          setState((existing) => {
            const base =
              existing.gameId === gameId
                ? existing
                : emptyTimelineState(gameId);
            return {
              ...base,
              events: mergeEvents(base.events, page.items),
            };
          });
        }
        if (page.next_after_record_seq <= cursor) break;
        cursor = page.next_after_record_seq;
        cursors.current.event = cursor;
        if (!page.has_more && cursor >= targetRecordSeq) break;
      }
    }

    async function loadModelRequests() {
      let cursor = cursors.current.modelRequest;
      while (active && cursor < targetRecordSeq) {
        const page = await listV2ModelRequests(
          gameId,
          cursor,
          controller.signal,
        );
        if (!active || cursors.current.gameId !== gameId) return;
        if (page.items.length) {
          setState((existing) => {
            const base =
              existing.gameId === gameId
                ? existing
                : emptyTimelineState(gameId);
            return {
              ...base,
              modelRequests: mergeModelRequests(
                base.modelRequests,
                page.items,
              ),
            };
          });
        }
        if (page.next_after_record_seq <= cursor) break;
        cursor = page.next_after_record_seq;
        cursors.current.modelRequest = cursor;
        if (!page.has_more && cursor >= targetRecordSeq) break;
      }
    }

    void Promise.all([loadEvents(), loadModelRequests()])
      .then(() => {
        if (!active || cursors.current.gameId !== gameId) return;
        setState((existing) => {
          const base =
            existing.gameId === gameId
              ? existing
              : emptyTimelineState(gameId);
          return {
            ...base,
            error: null,
            hydrated: true,
            syncedRecordSeq: Math.max(
              base.syncedRecordSeq,
              targetRecordSeq,
            ),
          };
        });
      })
      .catch((caught: unknown) => {
        if (
          !active ||
          (caught instanceof DOMException && caught.name === "AbortError")
        ) {
          return;
        }
        setState((existing) => {
          const base =
            existing.gameId === gameId
              ? existing
              : emptyTimelineState(gameId);
          return { ...base, error: caught, hydrated: true };
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [enabled, gameId, targetRecordSeq]);

  return {
    error: current.error,
    events: current.events,
    isFetching:
      enabled &&
      current.error === null &&
      current.syncedRecordSeq < targetRecordSeq,
    isInitialLoading: Boolean(gameId) && (!enabled || !current.hydrated),
    modelRequests: current.modelRequests,
  };
}

function emptyTimelineState(gameId: string) {
  return {
    error: null as unknown,
    events: [] as V2GameRecordEvent[],
    gameId,
    hydrated: false,
    modelRequests: [] as V2ModelRequestSummary[],
    syncedRecordSeq: 0,
  };
}

function mergeEvents(
  current: V2GameRecordEvent[],
  incoming: V2GameRecordEvent[],
) {
  const merged = new Map(current.map((item) => [item.event_id, item]));
  for (const item of incoming) merged.set(item.event_id, item);
  return [...merged.values()].sort(
    (left, right) => left.record_seq - right.record_seq,
  );
}

function mergeModelRequests(
  current: V2ModelRequestSummary[],
  incoming: V2ModelRequestSummary[],
) {
  const merged = new Map(current.map((item) => [item.attempt_id, item]));
  for (const item of incoming) merged.set(item.attempt_id, item);
  return [...merged.values()].sort(
    (left, right) => left.record_seq - right.record_seq,
  );
}

function V2GameRecordWorkspace({
  game,
  isRefreshing,
  onBack,
  refreshedAt,
}: {
  game: V2GameRecordDetail;
  isRefreshing: boolean;
  onBack: () => void;
  refreshedAt: number;
}) {
  const { notification } = AntApp.useApp();
  const queryClient = useQueryClient();
  const { session } = useAdminSession();
  const timeline = useMemo(() => buildV2Timeline(game), [game]);
  const roundSummaries = useMemo(
    () =>
      buildV2RoundSummaries(
        game.events,
        game.player_identities,
        game.status,
      ),
    [game.events, game.player_identities, game.status],
  );
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
  const [stopDialogOpen, setStopDialogOpen] = useState(false);
  const [stopReason, setStopReason] = useState(DEFAULT_STOP_REASON);
  const [retryDialogOpen, setRetryDialogOpen] = useState(false);
  const [retryReason, setRetryReason] = useState(DEFAULT_RETRY_REASON);
  const stopMutation = useMutation({
    mutationFn: () =>
      stopV2Game(
        game.game_id,
        stopReason.trim(),
        session?.csrf_token ?? "",
      ),
    onError: (error) => {
      notification.error({
        description: adminOperationErrorDescription(
          error,
          "暂时无法打断对局，请稍后重试。",
        ),
        title: "打断 V2 对局失败",
      });
    },
    onSuccess: async () => {
      setStopDialogOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: v2GameRecordKeys.detail(game.game_id),
        }),
        queryClient.invalidateQueries({ queryKey: v2GameRecordKeys.all }),
      ]);
      notification.success({ title: "V2 对局打断请求已提交" });
    },
  });
  const retryMutation = useMutation({
    mutationFn: () =>
      retryV2ModelAction(
        game.game_id,
        retryReason.trim(),
        session?.csrf_token ?? "",
      ),
    onError: (error) => {
      notification.error({
        description: adminOperationErrorDescription(
          error,
          "暂时无法恢复该动作，请确认 API 运行进程仍持有暂停任务。",
        ),
        title: "重试 V2 模型动作失败",
      });
    },
    onSuccess: async () => {
      setRetryDialogOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: v2GameRecordKeys.detail(game.game_id),
        }),
        queryClient.invalidateQueries({ queryKey: v2GameRecordKeys.all }),
      ]);
      notification.success({ title: "已恢复同一冻结动作" });
    },
  });

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
      if (categoryFilter === "template" && !item.templateRender) return false;
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
  const selected = timeline.find((item) => item.id === selectedId) ?? null;
  const selectSituationMoment = (id: string, phaseId: string) => {
    setSelectedId(id);
    setPhaseFilter(phaseId);
  };
  const selectPhase = (phaseId: string, toggle = false) => {
    const nextPhase =
      toggle && phaseFilter === phaseId ? "all" : phaseId;
    setPhaseFilter(nextPhase);
    if (nextPhase === "all") {
      setSelectedId("");
      return;
    }
    const lastItem = phases
      .find((phase) => phase.phaseId === nextPhase)
      ?.items.at(-1);
    if (lastItem) setSelectedId(lastItem.id);
  };

  const run = game.runs.find((item) => item.run_id === game.current_run_id);
  const canControl =
    session?.permissions.includes("*") ||
    session?.permissions.includes("runs.control");
  const canStop =
    canControl &&
    isLiveV2StatusActive(game.status) &&
    run?.stop_requested_at === null;
  const canRetry =
    canControl &&
    game.status === "paused_model_error" &&
    run?.status === "paused_model_error" &&
    run.stop_requested_at === null;
  const duration = run?.started_at
    ? Math.max(
        0,
        Date.parse(run.completed_at ?? game.updated_at) -
          Date.parse(run.started_at),
      )
    : null;
  const failureCount = game.model_requests.filter(
    (item) => item.status === "failed" && item.terminal !== false,
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
          <SummaryMetric
            label="法官音色"
            value={
              recordText(game.judge_voice_snapshot.selected_tts_speaker) ?? "—"
            }
          />
        </section>
        <Space>
          {canRetry ? (
            <Button
              type="primary"
              onClick={() => {
                retryMutation.reset();
                setRetryReason(DEFAULT_RETRY_REASON);
                setRetryDialogOpen(true);
              }}
            >
              重试同一动作
            </Button>
          ) : null}
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
          <Button onClick={onBack}>返回列表</Button>
        </Space>
      </header>

      {game.status === "canceled" || run?.stop_requested_at ? (
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
      {game.status === "paused_model_error" ? (
        <Alert
          description="当前动作、候选目标和请求上下文保持不变。恢复链路后可由管理员重试同一动作，系统不会生成规则兜底结果。"
          showIcon
          title="模型请求重试已耗尽，对局已安全暂停"
          type="warning"
        />
      ) : null}

      <V2OmniscientSituationPanel
        game={game}
        isRefreshing={isRefreshing}
        onOpenDetails={(id) => {
          setSelectedId(id);
          setRequestDrawerOpen(true);
        }}
        onReturnLatest={() => {
          setSelectedId("");
          setPhaseFilter("all");
        }}
        onSelectMoment={selectSituationMoment}
        refreshedAt={refreshedAt}
        roundSummaries={roundSummaries}
        selectedId={selectedId}
        timeline={timeline}
      />

      <section aria-label="流程筛选" className="v2-record-toolbar">
        <Select
          aria-label="筛选阶段"
          onChange={(phaseId) => selectPhase(phaseId)}
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
            { label: "系统模板", value: "template" },
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
          gameStatus={game.status}
          onSelect={(phaseId) => selectPhase(phaseId, true)}
          phases={phases}
          selectedPhaseId={phaseFilter}
        />
        <ActionTimeline
          items={filteredItems}
          onSelect={(id) => {
            setSelectedId(id);
            setRequestDrawerOpen(true);
          }}
          selectedId={selected?.id ?? ""}
        />
      </section>

      <RequestDetailsDrawer
        gameId={game.game_id}
        item={selected}
        onClose={() => setRequestDrawerOpen(false)}
        open={requestDrawerOpen}
      />
      <RawDataDrawer
        game={game}
        onClose={() => setRawDataOpen(false)}
        open={rawDataOpen}
      />
      <Modal
        cancelText="取消"
        confirmLoading={retryMutation.isPending}
        destroyOnHidden
        okButtonProps={{
          disabled: retryReason.trim().length < 3,
        }}
        okText="确认重试"
        onCancel={() => {
          if (!retryMutation.isPending) setRetryDialogOpen(false);
        }}
        onOk={() => retryMutation.mutate()}
        open={retryDialogOpen}
        title="重试同一冻结动作"
      >
        <Typography.Paragraph>
          系统会继续当前 action，复用相同的冻结上下文和请求内容，并为新的模型尝试生成独立
          attempt ID。
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary">
          对局 {game.game_id} · 运行 {game.current_run_id}
        </Typography.Paragraph>
        <Typography.Text strong>操作原因</Typography.Text>
        <Input.TextArea
          aria-label="重试原因"
          disabled={retryMutation.isPending}
          maxLength={500}
          onChange={(event) => setRetryReason(event.target.value)}
          rows={3}
          value={retryReason}
        />
      </Modal>
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
      </Modal>
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
  gameStatus,
  phases,
  selectedPhaseId,
  onSelect,
}: {
  gameStatus: string;
  phases: ReturnType<typeof groupV2Phases>;
  selectedPhaseId: string;
  onSelect: (phaseId: string) => void;
}) {
  const currentPhaseIndex = phases.findIndex((phase) => phase.isCurrent);
  const stepItems: NonNullable<StepsProps["items"]> = phases.map((phase) => {
    const progressStatus = phaseStatus(
      phase.failureCount,
      phase.isCurrent,
      gameStatus,
    );
    return {
      className:
        selectedPhaseId === phase.phaseId ? "is-selected-phase" : undefined,
      content: `${phase.items.length} 步 · ${phase.modelRequestCount} 次模型请求`,
      icon: <StatusIcon status={progressStatus} />,
      key: phase.phaseId,
      status: phaseStepStatus(progressStatus),
      title: phase.label,
    };
  });

  return (
    <aside className="v2-phase-rail">
      <Typography.Title level={5}>阶段进度</Typography.Title>
      <nav aria-label="对局阶段">
        <Steps
          className="v2-phase-steps"
          current={currentPhaseIndex}
          items={stepItems}
          onChange={(index) => {
            const phase = phases[index];
            if (phase) onSelect(phase.phaseId);
          }}
          orientation="vertical"
          size="small"
        />
      </nav>
    </aside>
  );
}

function ActionTimeline({
  items,
  selectedId,
  onSelect,
}: {
  items: V2TimelineItem[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const [expandedRowKeys, setExpandedRowKeys] = useState<string[]>([]);
  const columns = useMemo<ColumnsType<V2TimelineItem>>(
    () => [
      {
        dataIndex: "startedAt",
        render: (value: string) => (
          <time className="v2-action-time">{formatClock(value)}</time>
        ),
        title: "时间",
        width: 80,
      },
      {
        dataIndex: "actorLabel",
        ellipsis: true,
        title: "演员 / 角色",
        width: 130,
      },
      {
        dataIndex: "label",
        render: (value: string, item) => (
          <Button
            aria-label={`查看 ${item.actorLabel} ${value}`}
            className="v2-action-link"
            onClick={(event) => {
              event.stopPropagation();
              onSelect(item.id);
            }}
            type="link"
          >
            {value}
          </Button>
        ),
        title: "动作",
        width: 190,
      },
      {
        dataIndex: "audience",
        render: (value: string) => audienceLabel(value),
        title: "受众",
        width: 72,
      },
      {
        dataIndex: "status",
        render: (value: V2TimelineItem["status"]) => (
          <span className={`v2-action-status is-${value}`}>
            <StatusIcon status={value} />
            {statusLabel(value)}
          </span>
        ),
        title: "结果",
        width: 88,
      },
      {
        key: "source",
        render: (_, item) => (
          <Typography.Text
            ellipsis={{
              tooltip: item.templateRender
                ? "系统模板"
                : item.modelRequest?.model_id ?? "—",
            }}
          >
            {item.templateRender
              ? "系统模板"
              : `${item.modelRequest?.model_id ?? "—"}${
                  item.modelRequests.length > 1
                    ? ` · 重试 ${item.modelRequests.length - 1} 次`
                    : ""
                }`}
          </Typography.Text>
        ),
        title: "内容来源",
        width: 210,
      },
      {
        dataIndex: "durationMs",
        render: (value: number | null) => formatDuration(value),
        title: "耗时",
        width: 72,
      },
    ],
    [onSelect],
  );

  return (
    <main className="v2-action-timeline">
      <header>
        <Typography.Title level={5}>动作时间线（按阶段）</Typography.Title>
        <Typography.Text type="secondary">
          {items.length} 个可读步骤
        </Typography.Text>
      </header>
      {items.length ? (
        <Table<V2TimelineItem>
          className="v2-action-table"
          columns={columns}
          dataSource={items}
          expandable={{
            expandRowByClick: true,
            expandedRowKeys,
            expandedRowRender: (item) => <LifecycleStrip item={item} />,
            onExpandedRowsChange: (keys) =>
              setExpandedRowKeys(keys.map(String)),
          }}
          pagination={false}
          rowClassName={(item) =>
            item.id === selectedId ? "is-selected" : ""
          }
          rowKey="id"
          scroll={{ x: 900, y: 680 }}
          size="small"
        />
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
  const requestStarts = item.events.filter(
    (event) => event.event_type === "model_request_started",
  );
  const requestStarted = requestStarts[0];
  const retryScheduled = item.events.find(
    (event) => event.event_type === "model_retry_scheduled",
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
    item.templateRender
      ? {
          label: "系统模板",
          at: item.templateRender.created_at,
          detail:
            recordText(item.templateRender.payload.template_id) ?? "已渲染",
        }
      : null,
    requestStarted
      ? {
          label: "模型请求",
          at: requestStarted.created_at,
          detail:
            requestStarts.length > 1
              ? `共 ${requestStarts.length} 次尝试`
              : item.modelRequest?.attempt_id ?? "已发起",
        }
      : null,
    retryScheduled
      ? {
          label: "模型重试",
          at: retryScheduled.created_at,
          detail:
            recordText(retryScheduled.payload.failure_code) ??
            "瞬时传输异常",
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
  gameId,
  item,
  open,
  onClose,
}: {
  gameId: string;
  item: V2TimelineItem | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer
      destroyOnHidden
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
      {open && item ? (
        <RequestDetailsContent gameId={gameId} item={item} />
      ) : null}
    </Drawer>
  );
}

function RequestDetailsContent({
  gameId,
  item,
}: {
  gameId: string;
  item: V2TimelineItem;
}) {
  const attemptId = item.modelRequest?.attempt_id ?? "";
  const requestQuery = useQuery({
    enabled: Boolean(attemptId),
    gcTime: 0,
    queryFn: ({ signal }) =>
      readV2ModelRequest(gameId, attemptId, signal),
    queryKey: v2GameRecordKeys.modelRequest(gameId, attemptId),
  });
  const fullRequest = requestQuery.data ?? null;
  return (
    <div className="v2-request-drawer-content">
      <Tabs
        items={[
          {
            children: <InspectorOverview item={item} />,
            key: "overview",
            label: "概览",
          },
          ...(item.templateRender
            ? [
                {
                  children: (
                    <ReadableTemplateRender event={item.templateRender} />
                  ),
                  key: "template",
                  label: "模板详情",
                },
              ]
            : [
                {
                  children: (
                    <ModelRequestPayload
                      error={requestQuery.error}
                      isPending={
                        Boolean(attemptId) && requestQuery.isPending
                      }
                      request={fullRequest}
                      view="input"
                    />
                  ),
                  key: "input",
                  label: "模型输入",
                },
                {
                  children: (
                    <ModelRequestPayload
                      error={requestQuery.error}
                      isPending={
                        Boolean(attemptId) && requestQuery.isPending
                      }
                      request={fullRequest}
                      view="output"
                    />
                  ),
                  key: "output",
                  label: "模型输出",
                },
              ]),
          {
            children: (
              <ReadableRawEvents events={item.events} gameId={gameId} />
            ),
            key: "events",
            label: `原始事件 (${item.events.length})`,
          },
        ]}
        key={item.id}
      />
    </div>
  );
}

function ModelRequestPayload({
  error,
  isPending,
  request,
  view,
}: {
  error: Error | null;
  isPending: boolean;
  request: V2ModelRequest | null;
  view: "input" | "output";
}) {
  if (isPending) {
    return <AdminLoading message="正在按需读取模型请求正文..." />;
  }
  if (error) {
    return (
      <Alert
        description={
          isAdminApiError(error) ? error.message : "模型请求正文暂时不可用。"
        }
        message="无法读取模型请求正文"
        showIcon
        type="error"
      />
    );
  }
  return view === "input" ? (
    <ReadableModelInput request={request} />
  ) : (
    <ReadableModelOutput request={request} />
  );
}

function InspectorOverview({ item }: { item: V2TimelineItem }) {
  const request = item.modelRequest;
  const template = item.templateRender?.payload;
  return (
    <div className="v2-inspector-panel">
      <Descriptions
        column={2}
        items={[
          {
            key: "source",
            label: "内容来源",
            children: item.templateRender
              ? "系统确定性模板"
              : request?.actor_kind === "judge"
                ? "法官模型（历史记录）"
                : request
                  ? "玩家模型"
                  : "无内容生成",
          },
          { key: "model", label: "模型", children: request?.model_id ?? "—" },
          {
            key: "provider",
            label: "提供商",
            children: request?.model_provider ?? "—",
          },
          {
            key: "template",
            label: "模板",
            children: item.templateRender
              ? `${recordText(template?.template_id) ?? "—"} · v${
                  recordNumber(template?.template_version) ?? "—"
                }`
              : "—",
          },
          {
            key: "speaker",
            label: "实际音色",
            children: recordText(template?.tts_speaker) ?? "—",
          },
          {
            key: "status",
            label: "状态",
            children: statusLabel(request?.status ?? item.status),
          },
          {
            key: "attempts",
            label: "请求尝试",
            children:
              item.modelRequests.length > 1
                ? `${item.modelRequests.length} 次（重试 ${
                    item.modelRequests.length - 1
                  } 次后${item.status === "succeeded" ? "成功" : "仍失败"}）`
                : request
                  ? "1 次"
                  : "—",
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
            key: "budget",
            label: "请求 / 动作预算",
            children: request
              ? `${formatDuration(request.attempt_budget_ms)} / ${formatDuration(
                  request.action_budget_ms,
                )}`
              : "—",
          },
          {
            key: "failure-stage",
            label: "失败阶段",
            children: request?.failure_stage ?? "—",
          },
          {
            key: "response-headers",
            label: "已收到响应头",
            children:
              request?.response_headers_seen === null ||
              request?.response_headers_seen === undefined
                ? "—"
                : request.response_headers_seen
                  ? "是"
                  : "否",
          },
          {
            key: "action-remaining",
            label: "失败时动作剩余预算",
            children: formatDuration(request?.action_remaining_ms ?? null),
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
      {item.modelRequests.length > 1 ? (
        <section aria-label="模型请求尝试">
          <Typography.Text strong>模型请求尝试</Typography.Text>
          <ol>
            {item.modelRequests.map((attempt) => (
              <li key={attempt.attempt_id}>
                <Space size={8} wrap>
                  <Tag color={statusColor(attempt.status)}>
                    第 {attempt.attempt_no} 次 · 周期 {attempt.retry_cycle} ·{" "}
                    {statusLabel(attempt.status)}
                  </Tag>
                  <Typography.Text copyable>
                    {attempt.attempt_id}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    {attempt.failure_category
                      ? `${attempt.failure_category} · ${attempt.failure_code ?? "失败"}`
                      : attempt.failure_code ??
                      attempt.provider_request_id ??
                      formatDuration(attempt.completed_ms)}
                  </Typography.Text>
                </Space>
              </li>
            ))}
          </ol>
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
          <Space align="center" size={8}>
            <Typography.Text strong>
              <SoundOutlined /> 保存语音
            </Typography.Text>
            {item.voiceAsset.duration_ms !== null ? (
              <Typography.Text type="secondary">
                时长 {formatDuration(item.voiceAsset.duration_ms)}
              </Typography.Text>
            ) : null}
          </Space>
          <audio
            aria-label={`${item.actorLabel}保存语音`}
            controls
            preload="metadata"
            src={item.voiceAsset.audio_url}
          >
            当前浏览器不支持播放 V2 保存语音。
          </audio>
        </section>
      ) : null}
      {request?.failure_code ? (
        <Alert
          description={
            request.failure_category
              ? `${request.failure_category} · ${request.failure_code}`
              : request.failure_code
          }
          showIcon
          title={request.failure_kind ?? "模型请求失败"}
          type="error"
        />
      ) : null}
      {request?.repair_kind ? (
        <Alert
          description={`原始响应已保留；采用机械修复：${request.repair_kind}`}
          showIcon
          title="模型输出已修复"
          type="info"
        />
      ) : null}
    </div>
  );
}

function ReadableTemplateRender({ event }: { event: V2GameRecordEvent }) {
  const payload = event.payload;
  return (
    <div className="v2-inspector-panel">
      <Descriptions
        column={2}
        items={[
          {
            key: "template",
            label: "模板 ID",
            children: recordText(payload.template_id) ?? "—",
          },
          {
            key: "version",
            label: "模板版本",
            children: recordNumber(payload.template_version) ?? "—",
          },
          {
            key: "mode",
            label: "音色模式",
            children:
              recordText(payload.voice_mode) === "random" ? "每局随机" : "固定音色",
          },
          {
            key: "speaker",
            label: "实际音色",
            children: recordText(payload.tts_speaker) ?? "—",
          },
        ]}
        size="small"
      />
      <section>
        <Typography.Text strong>模板变量</Typography.Text>
        <pre>{prettyJson(payload.variables ?? {})}</pre>
      </section>
      <section>
        <Typography.Text strong>最终播报文本</Typography.Text>
        <Typography.Paragraph className="v2-result-copy">
          {recordText(payload.text) ?? "—"}
        </Typography.Paragraph>
      </section>
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
      destroyOnHidden
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
                  label="法官音色快照"
                  records={[game.judge_voice_snapshot]}
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
  const [activeKeys, setActiveKeys] = useState<string[]>([]);
  return (
    <section className="v2-raw-record-section">
      <Typography.Title level={5}>
        {label} ({records.length})
      </Typography.Title>
      {records.length ? (
        <Collapse
          activeKey={activeKeys}
          items={records.map((record, index) => {
            const key = String(index);
            return {
              children: activeKeys.includes(key) ? (
                <pre>{prettyJson(record)}</pre>
              ) : null,
              key,
              label: `${label} ${index + 1}`,
            };
          })}
          onChange={(keys) =>
            setActiveKeys(
              (Array.isArray(keys) ? keys : [keys]).map(String),
            )
          }
          size="small"
        />
      ) : (
        <Typography.Text type="secondary">暂无记录</Typography.Text>
      )}
    </section>
  );
}

function StatusIcon({
  status,
}: {
  status: "running" | "succeeded" | "failed" | "canceled";
}) {
  if (status === "failed") return <CloseCircleFilled aria-hidden="true" />;
  if (status === "canceled") return <MinusCircleFilled aria-hidden="true" />;
  if (status === "running") {
    return <LoadingOutlined aria-hidden="true" spin />;
  }
  return <CheckCircleFilled aria-hidden="true" />;
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
    paused_model_error: "模型错误暂停",
    awaiting_observation: "等待观察",
    running: "进行中",
    succeeded: "成功",
    failed: "失败",
    canceled: "已中止",
  };
  return labels[status] ?? status;
}

function statusColor(status: string) {
  if (status === "failed") return "error";
  if (status === "paused_model_error") return "warning";
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
  gameStatus: string,
): "running" | "succeeded" | "failed" | "canceled" {
  if (failureCount > 0) return "failed";
  if (!isCurrent) return "succeeded";
  if (gameStatus === "failed") return "failed";
  if (gameStatus === "canceled") return "canceled";
  return isLiveV2StatusActive(gameStatus) ? "running" : "succeeded";
}

function phaseStepStatus(
  status: ReturnType<typeof phaseStatus>,
): "wait" | "process" | "finish" | "error" {
  if (status === "running") return "process";
  if (status === "succeeded") return "finish";
  if (status === "failed") return "error";
  return "wait";
}

function recordText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function recordNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
