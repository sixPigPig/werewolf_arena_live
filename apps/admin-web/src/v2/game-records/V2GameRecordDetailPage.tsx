import {
  CheckCircleFilled,
  CloseCircleFilled,
  DatabaseOutlined,
  EyeOutlined,
  LoadingOutlined,
  SearchOutlined,
  SoundOutlined,
  SyncOutlined,
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
import Switch from "antd/es/switch";
import Tabs from "antd/es/tabs";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type UIEvent,
} from "react";
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
  type V2RoundSummary,
  type V2TimelineItem,
} from "@/v2/game-records/presentation";
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";
import {
  listV2GameEvents,
  listV2ModelRequests,
  readV2GameRecordSummary,
  readV2ModelRequest,
  stopV2Game,
} from "@/v2/game-records/api";
import { adminOperationErrorDescription } from "@/lib/admin-notification";
import type {
  V2GameRecordEvent,
  V2GameRecordDetail,
  V2ModelRequest,
  V2ModelRequestSummary,
  V2PlayerIdentity,
} from "@/v2/game-records/types";
import {
  ReadableModelInput,
  ReadableModelOutput,
  ReadableRawEvents,
} from "@/v2/game-records/request-presentation";

type CategoryFilter = "all" | "model" | "template" | "milestone";
type StatusFilter = "all" | "running" | "succeeded" | "failed";
const DEFAULT_STOP_REASON = "人工打断异常对局，避免继续消耗 API 额度";

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
  const visiblePhases = useMemo(
    () => groupV2Phases(filteredItems, game.phase_id),
    [filteredItems, game.phase_id],
  );
  const selected = timeline.find((item) => item.id === selectedId) ?? null;

  const run = game.runs.find((item) => item.run_id === game.current_run_id);
  const canControl =
    session?.permissions.includes("*") ||
    session?.permissions.includes("runs.control");
  const canStop =
    canControl &&
    isLiveV2StatusActive(game.status) &&
    run?.stop_requested_at === null;
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

      <RoundSummaryPanel summaries={roundSummaries} />

      <OmniscientLivePanel
        game={game}
        isRefreshing={isRefreshing}
        refreshedAt={refreshedAt}
        timeline={timeline}
      />

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

function RoundSummaryPanel({
  summaries,
}: {
  summaries: V2RoundSummary[];
}) {
  return (
    <section aria-label="对局轮次摘要" className="v2-round-summary-panel">
      <header>
        <div>
          <Typography.Text className="ant-admin-page-kicker">
            ROUND DIGEST
          </Typography.Text>
          <Typography.Title level={4}>对局轮次摘要</Typography.Title>
          <Typography.Paragraph>
            由事实序列确定性聚合，快速查看每轮夜间、放逐与特殊结算。
          </Typography.Paragraph>
        </div>
        <Tag color="blue">{summaries.length} 轮</Tag>
      </header>
      {summaries.length ? (
        <div className="v2-round-summary-grid">
          {summaries.map((summary) => (
            <article
              className={`v2-round-summary-card is-${summary.status}`}
              key={summary.roundNo}
            >
              <header>
                <div>
                  <Typography.Text type="secondary">
                    NIGHT {summary.roundNo} → DAY {summary.roundNo}
                  </Typography.Text>
                  <Typography.Title level={5}>
                    第 {summary.roundNo} 轮
                  </Typography.Title>
                </div>
                <Tag color={statusColor(summary.status)}>
                  {statusLabel(summary.status)}
                </Tag>
              </header>
              {summary.highlights.length ? (
                <ol>
                  {summary.highlights.map((highlight) => (
                    <li className={`is-${highlight.tone}`} key={highlight.id}>
                      <span aria-hidden="true" />
                      <Typography.Text>{highlight.label}</Typography.Text>
                    </li>
                  ))}
                </ol>
              ) : (
                <Typography.Text className="v2-round-summary-empty" type="secondary">
                  本轮正在进行，关键结算尚未产生。
                </Typography.Text>
              )}
              <footer>
                <Typography.Text type="secondary">
                  {formatClock(summary.startedAt)} →{" "}
                  {summary.endedAt ? formatClock(summary.endedAt) : "进行中"}
                </Typography.Text>
                <Typography.Text type="secondary">
                  事实 #{summary.firstRecordSeq}–#{summary.lastRecordSeq}
                </Typography.Text>
              </footer>
            </article>
          ))}
        </div>
      ) : (
        <Empty
          description="首夜开始后将生成第一轮摘要"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      )}
    </section>
  );
}

function OmniscientLivePanel({
  game,
  isRefreshing,
  refreshedAt,
  timeline,
}: {
  game: V2GameRecordDetail;
  isRefreshing: boolean;
  refreshedAt: number;
  timeline: V2TimelineItem[];
}) {
  const identities = game.player_identities;
  const identityById = new Map(
    identities.map((identity) => [identity.player_id, identity]),
  );
  const currentAction =
    [...timeline].reverse().find((item) => item.kind === "action") ?? null;
  const latestPresentation = game.presentations.at(-1) ?? null;
  const latestWindow =
    [...game.action_windows]
      .reverse()
      .find((item) => recordText(item.window_type) === "night") ?? null;
  const latestWindowId = recordText(latestWindow?.window_id);
  const abilityByInstance = new Map(
    game.ability_instances.map((item) => [
      recordText(item.ability_instance_id),
      {
        abilityId: recordText(item.ability_id) ?? "unknown",
        ownerId: recordText(item.owner_id),
      },
    ]),
  );
  const recentActivations = game.ability_activations
    .filter(
      (item) =>
        latestWindowId === null ||
        recordText(item.window_id) === latestWindowId,
    )
    .slice(-6)
    .reverse();
  const phaseLabel =
    groupV2Phases(timeline, game.phase_id).find(
      (phase) => phase.phaseId === game.phase_id,
    )?.label ?? game.phase_id;
  const currentActorId =
    latestPresentation?.actor_kind === "player"
      ? latestPresentation.actor_id
      : currentAction?.actorKind === "player"
        ? currentAction.actorId
        : null;
  const currentActor =
    (currentActorId ? identityById.get(currentActorId)?.display_name : null) ??
    (latestPresentation?.actor_kind === "judge" ? "法官" : null) ??
    currentAction?.actorLabel ??
    "等待下一位行动者";
  const active = isLiveV2StatusActive(game.status);

  return (
    <section aria-label="实时全知态势" className="v2-omniscient-panel">
      <header className="v2-omniscient-heading">
        <div>
          <Typography.Text className="ant-admin-page-kicker">
            OMNISCIENT OPERATIONS
          </Typography.Text>
          <Typography.Title level={4}>
            <EyeOutlined /> 实时全知态势
          </Typography.Title>
          <Typography.Paragraph>
            身份、当前场景和私密行动仅向具备 V2 对局读取权限的后台用户展示。
          </Typography.Paragraph>
        </div>
        <Space size={8}>
          <Tag
            color={isRefreshing ? "processing" : active ? "blue" : "default"}
            icon={isRefreshing ? <SyncOutlined spin /> : undefined}
          >
            {isRefreshing
              ? "正在同步"
              : active
                ? "每 2 秒自动更新"
                : "终态数据"}
          </Tag>
          <Typography.Text type="secondary">
            更新于 {formatClock(new Date(refreshedAt).toISOString())}
          </Typography.Text>
        </Space>
      </header>

      <div className="v2-live-overview-grid">
        <LiveOverviewCard
          detail={`${phaseLabel} · ${phaseStateLabel(game.phase_state)}`}
          label="当前场景"
          value={sceneLabel(game.phase_id, currentAction?.actionType ?? null)}
        />
        <LiveOverviewCard
          detail={
            currentAction
              ? `${currentAction.label} · ${audienceLabel(currentAction.audience)}`
              : "等待动作进入时间线"
          }
          label="当前行动者"
          value={currentActor}
        />
        <LiveOverviewCard
          detail={nightResolutionSummary(latestWindow, identityById)}
          label="最近夜间结算"
          value={nightWindowLabel(latestWindow)}
        />
      </div>

      <div className="v2-live-detail-grid">
        <section className="v2-live-identity-section">
          <header>
            <Typography.Title level={5}>完整身份总览</Typography.Title>
            <Typography.Text type="secondary">
              {identities.length
                ? `${identities.filter((item) => item.alive).length}/${identities.length} 人存活`
                : "身份尚未分配"}
            </Typography.Text>
          </header>
          {identities.length ? (
            <div className="v2-identity-table-wrap">
              <table className="v2-identity-table">
                <thead>
                  <tr>
                    <th>座位</th>
                    <th>玩家</th>
                    <th>身份</th>
                    <th>阵营</th>
                    <th>状态</th>
                    <th>出局原因</th>
                  </tr>
                </thead>
                <tbody>
                  {identities.map((identity) => (
                    <tr key={identity.player_id}>
                      <td>{identity.seat} 号</td>
                      <td>
                        <strong>{identity.display_name}</strong>
                        <small>{identity.player_id}</small>
                      </td>
                      <td>
                        <Tag color={roleColor(identity.role)}>
                          {roleLabel(identity.role)}
                        </Tag>
                      </td>
                      <td>{teamLabel(identity.team)}</td>
                      <td>
                        <span
                          className={
                            identity.alive
                              ? "v2-player-life is-alive"
                              : "v2-player-life is-dead"
                          }
                        >
                          {identity.alive ? "存活" : "已出局"}
                        </span>
                      </td>
                      <td>{deathCauseLabel(identity.death_cause)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              description="当前记录没有可展示的身份分配"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          )}
        </section>

        <section className="v2-live-private-section">
          <header>
            <Typography.Title level={5}>最近私密行动</Typography.Title>
            <Typography.Text type="secondary">
              {latestWindow
                ? `${nightWindowLabel(latestWindow)} · ${windowStateLabel(
                    recordText(latestWindow.state),
                  )}`
                : "尚无夜间行动窗口"}
            </Typography.Text>
          </header>
          {recentActivations.length ? (
            <ol className="v2-private-action-list">
              {recentActivations.map((activation, index) => {
                const ability =
                  abilityByInstance.get(
                    recordText(activation.ability_instance_id),
                  ) ?? { abilityId: "unknown", ownerId: null };
                const actorId =
                  recordText(activation.actor_player_id) ?? ability.ownerId;
                const decision = recordObject(activation.decision);
                const targetId = recordText(decision.target_player_id);
                return (
                  <li
                    key={
                      recordText(activation.activation_id) ??
                      `${ability.abilityId}-${index}`
                    }
                  >
                    <span>
                      <strong>{abilityLabel(ability.abilityId)}</strong>
                      <small>
                        {playerLabel(actorId, identityById)}
                        {" → "}
                        {targetId
                          ? playerLabel(targetId, identityById)
                          : "未选择目标"}
                      </small>
                    </span>
                    <Tag
                      color={
                        recordText(activation.status) === "completed"
                          ? "success"
                          : recordText(activation.status) === "open"
                            ? "processing"
                            : "default"
                      }
                    >
                      {activationResultLabel(activation)}
                    </Tag>
                  </li>
                );
              })}
            </ol>
          ) : (
            <Empty
              description="等待首个私密行动"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          )}
          <div className="v2-current-subtitle">
            <Typography.Text type="secondary">最近现场发言</Typography.Text>
            <Typography.Paragraph>
              {latestPresentation
                ? displaySubtitleText(latestPresentation.subtitle_text)
                : "暂无已保存发言"}
            </Typography.Paragraph>
            {latestPresentation ? (
              <Typography.Text type="secondary">
                {latestPresentation.actor_kind === "judge"
                  ? "法官"
                  : playerLabel(latestPresentation.actor_id, identityById)}
                {" · "}
                {audienceLabel(latestPresentation.audience)}
              </Typography.Text>
            ) : null}
          </div>
        </section>
      </div>
    </section>
  );
}

function LiveOverviewCard({
  detail,
  label,
  value,
}: {
  detail: string;
  label: string;
  value: string;
}) {
  return (
    <article className="v2-live-overview-card">
      <Typography.Text type="secondary">{label}</Typography.Text>
      <Typography.Text strong>{value}</Typography.Text>
      <Typography.Text type="secondary">{detail}</Typography.Text>
    </article>
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
  const [scrollTop, setScrollTop] = useState(0);
  const viewportHeight = 680;
  const overscan = 360;
  const layout = useMemo(() => {
    const rows: Array<
      | {
          kind: "phase";
          key: string;
          label: string;
          count: number;
          height: number;
        }
      | {
          kind: "action";
          key: string;
          item: V2TimelineItem;
          height: number;
        }
    > = [];
    for (const phase of phases) {
      rows.push({
        count: phase.items.length,
        height: 42,
        key: `phase:${phase.phaseId}`,
        kind: "phase",
        label: phase.label,
      });
      for (const item of phase.items) {
        rows.push({
          height: item.id === selectedId ? 250 : 48,
          item,
          key: `action:${item.id}`,
          kind: "action",
        });
      }
    }
    let top = 0;
    const positioned = rows.map((row) => {
      const positionedRow = { ...row, top };
      top += row.height;
      return positionedRow;
    });
    return { rows: positioned, totalHeight: top };
  }, [phases, selectedId]);
  const visibleRows = layout.rows.filter(
    (row) =>
      row.top + row.height >= scrollTop - overscan &&
      row.top <= scrollTop + viewportHeight + overscan,
  );

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
        <span>内容来源</span>
        <span>耗时</span>
      </div>
      {phases.length ? (
        <div
          className="v2-action-virtual-viewport"
          onScroll={(event: UIEvent<HTMLDivElement>) =>
            setScrollTop(event.currentTarget.scrollTop)
          }
        >
          <div
            className="v2-action-virtual-canvas"
            style={{ height: layout.totalHeight }}
          >
            {visibleRows.map((row) => (
              <div
                className="v2-action-virtual-row"
                key={row.key}
                style={{ height: row.height, transform: `translateY(${row.top}px)` }}
              >
                {row.kind === "phase" ? (
                  <header className="v2-action-phase-header">
                    <strong>{row.label}</strong>
                    <Typography.Text type="secondary">
                      {row.count} 步
                    </Typography.Text>
                  </header>
                ) : (
                  <div
                    className={
                      row.item.id === selectedId
                        ? "v2-action-item is-selected"
                        : "v2-action-item"
                    }
                  >
                    <button
                      aria-label={`查看 ${row.item.actorLabel} ${row.item.label}`}
                      className="v2-action-row"
                      onClick={() => onSelect(row.item.id)}
                      type="button"
                    >
                      <time>{formatClock(row.item.startedAt)}</time>
                      <span>{row.item.actorLabel}</span>
                      <strong>{row.item.label}</strong>
                      <span>{audienceLabel(row.item.audience)}</span>
                      <span className={`is-${row.item.status}`}>
                        <StatusIcon status={row.item.status} />
                        {statusLabel(row.item.status)}
                      </span>
                      <span>
                        {row.item.templateRender
                          ? "系统模板"
                          : `${row.item.modelRequest?.model_id ?? "—"}${
                              row.item.modelRequests.length > 1
                                ? ` · 重试 ${
                                    row.item.modelRequests.length - 1
                                  } 次`
                                : ""
                            }`}
                      </span>
                      <span>{formatDuration(row.item.durationMs)}</span>
                    </button>
                    {row.item.id === selectedId ? (
                      <LifecycleStrip item={row.item} />
                    ) : null}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
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
                    第 {attempt.attempt_no} 次 · {statusLabel(attempt.status)}
                  </Tag>
                  <Typography.Text copyable>
                    {attempt.attempt_id}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    {attempt.failure_code ??
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
    canceled: "已中止",
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

function sceneLabel(phaseId: string, actionType: string | null): string {
  const action = (actionType ?? "").toLowerCase();
  if (action.includes("game_completed")) return "终局舞台";
  if (action.includes("werewolf")) return "狼人房间";
  if (action.includes("guard")) return "守卫行动";
  if (action.includes("seer")) return "预言家查验";
  if (action.includes("witch")) return "女巫用药";
  if (action.includes("hunter")) return "猎人行动";
  if (action.includes("dawn")) return "黎明公布";
  if (phaseId === "first_night" || phaseId.startsWith("night_")) {
    return "夜间行动";
  }
  if (phaseId.startsWith("day_")) return "公共舞台";
  return "开幕舞台";
}

function phaseStateLabel(state: string): string {
  const labels: Record<string, string> = {
    opening_ready: "等待开幕",
    opening_completed: "开幕完成",
    nightfall_ready: "等待入夜",
    nightfall_announced: "夜幕已宣布",
    night_running: "夜间行动中",
    dawn_announcement_ready: "等待天亮播报",
    dawn_announced: "天亮已公布",
    dawn_reactions_ready: "黎明技能处理中",
    sheriff_election_ready: "等待警长竞选",
    public_day_ready: "等待白天流程",
    public_discussion_open: "白天讨论中",
    public_discussion_completed: "白天讨论完成",
    exile_vote_open: "放逐投票中",
    exile_resolved: "放逐已结算",
    game_completed: "对局结束",
    failed: "运行失败",
    canceled: "已中止",
  };
  return labels[state] ?? state;
}

function nightWindowLabel(
  window: Record<string, unknown> | null,
): string {
  if (!window) return "尚未开始";
  const sequence = recordNumber(window.window_seq);
  return sequence === null ? "夜间行动窗口" : `第 ${sequence} 个夜间窗口`;
}

function nightResolutionSummary(
  window: Record<string, unknown> | null,
  identities: Map<string, V2PlayerIdentity>,
): string {
  if (!window) return "等待夜间行动开始";
  if (recordText(window.state) === "open") return "行动仍在进行，结算尚未产生";
  const result = recordObject(window.result);
  if (result.peaceful === true) {
    const preventedBy = recordText(result.attack_prevented_by);
    return preventedBy
      ? `平安夜 · 袭击被${preventionLabel(preventedBy)}阻止`
      : "平安夜";
  }
  const deaths = Array.isArray(result.deaths)
    ? result.deaths
        .map(recordObject)
        .map((death) => {
          const playerId = recordText(death.player_id);
          if (!playerId) return null;
          const cause = deathCauseLabel(recordText(death.cause));
          return `${playerLabel(playerId, identities)}（${cause}）`;
        })
        .filter((item): item is string => item !== null)
    : [];
  return deaths.length ? `出局：${deaths.join("、")}` : "窗口已关闭，暂无死亡记录";
}

function preventionLabel(value: string): string {
  const labels: Record<string, string> = {
    guard: "守卫",
    protect: "守卫",
    heal: "女巫解药",
    guard_and_heal: "同守同救",
  };
  return labels[value] ?? value;
}

function windowStateLabel(state: string | null): string {
  if (state === "open") return "进行中";
  if (state === "closed") return "已结算";
  return state ?? "未知状态";
}

function abilityLabel(value: string): string {
  const labels: Record<string, string> = {
    "werewolf.attack": "狼人袭击",
    "guard.protect": "守卫守护",
    "seer.investigate": "预言家查验",
    "witch.heal": "女巫解药",
    "witch.poison": "女巫毒药",
    "hunter.death_shot": "猎人开枪",
  };
  return labels[value] ?? value;
}

function activationResultLabel(activation: Record<string, unknown>): string {
  const status = recordText(activation.status);
  if (status === "open") return "进行中";
  if (status === "skipped") {
    const reason = recordText(activation.skip_reason);
    return reason ? `跳过 · ${skipReasonLabel(reason)}` : "已跳过";
  }
  const result = recordObject(activation.result);
  const alignment = recordText(result.alignment);
  if (alignment) return `查验为${teamLabel(alignment)}`;
  if (result.consensus_reached === true) return "已达成袭击共识";
  if (result.consensus_reached === false) return "未达成袭击共识";
  if (result.heal_used === true) return "已使用解药";
  if (result.heal_used === false) return "未使用解药";
  if (result.poison_used === true) return "已使用毒药";
  if (result.poison_used === false) return "未使用毒药";
  if (result.shot_used === true) return "已发动技能";
  if (result.shot_used === false) return "放弃发动";
  if (result.effect === "protect_registered") return "守护已登记";
  return status === "completed" ? "已完成" : status ?? "未知";
}

function skipReasonLabel(value: string): string {
  const labels: Record<string, string> = {
    owner_not_alive: "角色已出局",
    heal_already_used: "解药已使用",
    poison_already_used: "毒药已使用",
    heal_poison_mutually_exclusive: "同夜不可同时用药",
    no_eligible_target: "没有合法目标",
  };
  return labels[value] ?? value;
}

function playerLabel(
  playerId: string | null,
  identities: Map<string, V2PlayerIdentity>,
): string {
  if (!playerId) return "系统";
  const identity = identities.get(playerId);
  return identity
    ? `${identity.seat}号 ${identity.display_name}`
    : playerId;
}

function roleLabel(value: string): string {
  const labels: Record<string, string> = {
    werewolf: "狼人",
    villager: "村民",
    seer: "预言家",
    guard: "守卫",
    witch: "女巫",
    hunter: "猎人",
    idiot: "白痴",
  };
  return labels[value] ?? value;
}

function roleColor(value: string): string {
  if (value === "werewolf") return "red";
  if (value === "villager") return "default";
  return "blue";
}

function teamLabel(value: string | null): string {
  const labels: Record<string, string> = {
    werewolf: "狼人阵营",
    werewolves: "狼人阵营",
    village: "好人阵营",
    villagers: "好人阵营",
  };
  return value ? (labels[value] ?? value) : "未记录";
}

function deathCauseLabel(value: string | null): string {
  const labels: Record<string, string> = {
    werewolf_attack: "狼人袭击",
    poison: "女巫毒杀",
    exile: "投票放逐",
    hunter_shot: "猎人带走",
    self_explosion: "狼人自爆",
  };
  return value ? (labels[value] ?? value) : "—";
}

function recordObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function recordText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function recordNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function displaySubtitleText(value: string): string {
  const trimmed = value.trim();
  const fenced =
    /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(trimmed)?.[1] ?? trimmed;
  try {
    const parsed: unknown = JSON.parse(fenced);
    if (
      parsed &&
      typeof parsed === "object" &&
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
