import {
  ArrowDownOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  FlagOutlined,
  MessageOutlined,
  MoonOutlined,
  SafetyCertificateOutlined,
  SunOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import Button from "antd/es/button";
import Empty from "antd/es/empty";
import Modal from "antd/es/modal";
import Table, { type ColumnsType } from "antd/es/table";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { Fragment, useMemo, useState, type ReactNode } from "react";

import { readV2ModelRequest } from "@/v2/game-records/api";
import { extractV2ModelInputFacts } from "@/v2/game-records/model-input-facts";
import {
  abilityLabel,
  buildV2HistoricalIdentities,
  formatClock,
  groupV2Phases,
  phaseLabel,
  type V2RoundSummary,
  type V2TimelineItem,
} from "@/v2/game-records/presentation";
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";
import type {
  V2GameRecordDetail,
  V2GameRecordEvent,
  V2PlayerIdentity,
} from "@/v2/game-records/types";

type Props = {
  game: V2GameRecordDetail;
  isRefreshing: boolean;
  onOpenDetails: (id: string) => void;
  onReturnLatest: () => void;
  onSelectMoment: (id: string, phaseId: string) => void;
  refreshedAt: number;
  roundSummaries: V2RoundSummary[];
  selectedId: string;
  timeline: V2TimelineItem[];
};

type SituationStage = {
  item: V2TimelineItem;
  key: string;
  label: string;
};

type SituationPhase = {
  digest: string | null;
  label: string;
  phaseId: string;
  stages: SituationStage[];
};

type IdentityView = "moment" | "final";

type SituationDetail = {
  actorLabel?: string;
  actorSeat?: string | number;
  danger: boolean;
  eventLabel?: string;
  narrative: string | null;
  resultLabel: string;
  targetId: string | null;
  targetLabel: string | null;
};

export function V2OmniscientSituationPanel({
  game,
  isRefreshing,
  onOpenDetails,
  onReturnLatest,
  onSelectMoment,
  refreshedAt,
  roundSummaries,
  selectedId,
  timeline,
}: Props) {
  const [identityView, setIdentityView] = useState<IdentityView>("moment");
  const [privateInfoPlayerId, setPrivateInfoPlayerId] = useState<string | null>(
    null,
  );
  const situationPhases = buildSituationPhases(
    timeline,
    game.phase_id,
    roundSummaries,
  );
  const situationItems = situationPhases.flatMap((phase) =>
    phase.stages.map((stage) => stage.item),
  );
  const latestItem = latestTimelineItem(timeline);
  const selectedItem =
    (selectedId
      ? timeline.find((item) => item.id === selectedId)
      : latestItem) ?? latestItem;
  const followingLatest = selectedId === "";
  const selectedRecordSeq = followingLatest
    ? game.last_record_seq
    : (selectedItem?.lastRecordSeq ?? game.last_record_seq);
  const behindLatest = Math.max(0, game.last_record_seq - selectedRecordSeq);
  const currentIndex = selectedItem
    ? timeline.findIndex((item) => item.id === selectedItem.id)
    : -1;
  const previousItem = currentIndex > 0 ? timeline[currentIndex - 1] : null;
  const nextItem =
    currentIndex >= 0 && currentIndex < timeline.length - 1
      ? timeline[currentIndex + 1]
      : null;
  const identities =
    identityView === "final"
      ? game.player_identities
      : buildV2HistoricalIdentities(
          game.events,
          game.player_identities,
          selectedRecordSeq,
        );
  const fullIdentityById = new Map(
    game.player_identities.map((identity) => [
      identity.player_id,
      identity,
    ]),
  );
  const visibleActivations = activationsAt(
    game,
    identityView === "final" ? game.last_record_seq : selectedRecordSeq,
  );
  const privateInfoByPlayer = privateInformationByPlayer(
    game,
    visibleActivations,
    identityView === "final" ? game.last_record_seq : selectedRecordSeq,
    fullIdentityById,
  );
  const privateInfoIdentity = privateInfoPlayerId
    ? fullIdentityById.get(privateInfoPlayerId) ?? null
    : null;
  const privateInfoItems = privateInfoPlayerId
    ? privateInfoByPlayer.get(privateInfoPlayerId)?.results ?? []
    : [];
  const currentDetail = selectedItem
    ? describeSituationItem(
        game,
        selectedItem,
        selectedRecordSeq,
        fullIdentityById,
      )
    : null;
  const selectedAttemptId = selectedItem?.modelRequest?.attempt_id ?? "";
  const modelRequestQuery = useQuery({
    enabled: Boolean(selectedAttemptId),
    queryFn: ({ signal }) =>
      readV2ModelRequest(game.game_id, selectedAttemptId, signal),
    queryKey: v2GameRecordKeys.modelRequest(
      game.game_id,
      selectedAttemptId,
    ),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const modelInputFacts = useMemo(
    () =>
      extractV2ModelInputFacts(
        modelRequestQuery.data?.request_payload ?? null,
      ),
    [modelRequestQuery.data?.request_payload],
  );
  const publicSpeeches = recentPublicSpeeches(
    game.events,
    selectedRecordSeq,
    fullIdentityById,
    selectedItem?.phaseId ?? game.phase_id,
  );
  const voteSummary = publicVoteSummary(
    game.events,
    selectedRecordSeq,
    fullIdentityById,
    selectedItem?.phaseId ?? game.phase_id,
  );
  const judgeMessages = recentJudgeMessages(
    timeline,
    selectedRecordSeq,
  );
  const currentActorId =
    selectedItem?.actorKind === "player" ? selectedItem.actorId : null;
  const involvedPlayerIds = new Set(
    [currentActorId, currentDetail?.targetId].filter(
      (value): value is string => value !== null && value !== undefined,
    ),
  );
  const rosterColumns: ColumnsType<V2PlayerIdentity> = [
    {
      key: "player",
      render: (_, identity) => (
        <div className="v2-situation-player">
          <span className="v2-situation-seat">{identity.seat}</span>
          <span>
            <strong>{identity.display_name}</strong>
            <small>{identity.player_id}</small>
          </span>
        </div>
      ),
      title: "身份 / 玩家",
      width: "24%",
    },
    {
      dataIndex: "role",
      key: "role",
      render: (role: string) => (
        <Tag color={roleColor(role)}>{roleLabel(role)}</Tag>
      ),
      title: "真身",
      width: "13%",
    },
    {
      dataIndex: "alive",
      key: "alive",
      render: (alive: boolean, identity) => (
        <div className="v2-situation-life-cell">
          <span
            className={
              alive
                ? "v2-situation-life is-alive"
                : "v2-situation-life is-dead"
            }
          >
            {alive ? "存活" : "已出局"}
          </span>
          {!alive ? <small>{deathCauseLabel(identity.death_cause)}</small> : null}
        </div>
      ),
      title: "存活状态",
      width: "16%",
    },
    {
      key: "private-information",
      render: (_, identity) => {
        const information = privateInfoByPlayer.get(identity.player_id);
        if (!information?.results.length) return "暂无私有信息";
        const latestInformation = information.results.at(-1);
        return (
          <div className="v2-situation-private-info">
            <span>{latestInformation}</span>
            <Button
              aria-label={`查看 ${identity.seat}号 ${identity.display_name}的全部私有信息（${information.results.length}条）`}
              onClick={() => setPrivateInfoPlayerId(identity.player_id)}
              size="small"
              type="link"
            >
              查看全部（{information.results.length}）
            </Button>
          </div>
        );
      },
      title: "当前私有信息",
      width: "23%",
    },
    {
      key: "recent-action",
      render: (_, identity) =>
        privateInfoByPlayer.get(identity.player_id)?.action ?? "--",
      title: "最近行动",
      width: "24%",
    },
  ];

  const enterHistory = () => {
    if (!followingLatest || !situationItems.length) return;
    const fallback =
      situationItems.length > 1
        ? situationItems[situationItems.length - 2]
        : situationItems[0];
    onSelectMoment(fallback.id, fallback.phaseId);
  };

  return (
    <section aria-label="全知战局态势" className="v2-situation-panel">
      <header className="v2-situation-heading">
        <div>
          <Typography.Title level={4}>
            <EyeOutlined /> 全知战局态势
          </Typography.Title>
          <Typography.Paragraph>
            在同一条事实时间线上回看私密行动、公开进展与当时的玩家状态。
          </Typography.Paragraph>
        </div>
        <div className="v2-situation-heading-actions">
          <div aria-label="态势查看模式" className="v2-situation-mode" role="group">
            <button
              aria-pressed={followingLatest}
              className={followingLatest ? "is-active" : ""}
              onClick={onReturnLatest}
              type="button"
            >
              跟随实时
            </button>
            <button
              aria-pressed={!followingLatest}
              className={!followingLatest ? "is-active" : ""}
              onClick={enterHistory}
              type="button"
            >
              历史回看
            </button>
          </div>
          <Typography.Text className="v2-situation-sync" type="secondary">
            {isRefreshing ? (
              <>
                <SyncOutlined spin /> 正在同步
              </>
            ) : followingLatest ? (
              <>更新于 {formatClock(new Date(refreshedAt).toISOString())}</>
            ) : (
              <>距最新 {behindLatest} 条事实</>
            )}
          </Typography.Text>
        </div>
      </header>

      {selectedItem ? (
        <>
          <div className="v2-situation-scrubber">
            <div className="v2-situation-phases">
              {situationPhases.map((phase) => (
                <section
                  aria-label={`${phase.label}时间点`}
                  className="v2-situation-phase"
                  key={phase.phaseId}
                >
                  <header>
                    <strong>{phase.label}</strong>
                    {phase.digest ? (
                      <span title={phase.digest}>{phase.digest}</span>
                    ) : null}
                  </header>
                  <div className="v2-situation-stage-list">
                    {phase.stages.map((stage) => {
                      const active = stage.item.id === selectedItem.id;
                      return (
                        <button
                          aria-current={active ? "step" : undefined}
                          aria-label={`回看${phase.label}${stage.label}`}
                          className={active ? "is-active" : ""}
                          key={stage.key}
                          onClick={() =>
                            onSelectMoment(stage.item.id, phase.phaseId)
                          }
                          title={`${stage.item.actorLabel} · ${stage.item.label} · 事实 #${stage.item.lastRecordSeq}`}
                          type="button"
                        >
                          <StageIcon stage={stage.key} />
                          <span>{stage.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
            <div className="v2-situation-cursor">
              <ClockCircleOutlined />
              <strong>{phaseLabel(selectedItem.phaseId)}</strong>
              <span>{formatClock(selectedItem.startedAt)}</span>
              <span>事实 #{selectedRecordSeq}</span>
              {!followingLatest ? <Tag color="blue">历史状态</Tag> : null}
            </div>
          </div>

          <div className="v2-situation-main-grid">
            <section className="v2-situation-now">
              <header>
                <Typography.Title level={5}>此刻发生了什么</Typography.Title>
              </header>

              <article className="v2-situation-event">
                <div className="v2-situation-event-title">
                  <span aria-hidden="true" className="v2-situation-actor-mark">
                    {currentDetail?.actorSeat ??
                      (selectedItem.actorKind === "player"
                        ? fullIdentityById.get(selectedItem.actorId)?.seat ?? "P"
                        : selectedItem.actorKind === "judge"
                          ? "J"
                          : "S")}
                  </span>
                  <div>
                    <Typography.Text strong>
                      {currentDetail?.actorLabel ?? selectedItem.actorLabel} ·{" "}
                      {currentDetail?.eventLabel ?? selectedItem.label}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {selectedItem.objective ?? currentDetail?.narrative ?? "事实已记录"}
                    </Typography.Text>
                  </div>
                </div>

                {currentDetail?.targetLabel || currentDetail?.resultLabel ? (
                  <div className="v2-situation-event-result">
                    <div>
                      <Typography.Text type="secondary">行动目标</Typography.Text>
                      <Typography.Text strong>
                        {currentDetail.targetLabel ?? "无需选择目标"}
                      </Typography.Text>
                    </div>
                    <ArrowRightOutlined aria-hidden="true" />
                    <div>
                      <Typography.Text type="secondary">权威结果</Typography.Text>
                      <Typography.Text
                        className={
                          currentDetail.danger ? "is-danger" : "is-result"
                        }
                        strong
                      >
                        {currentDetail.resultLabel ?? "动作已记录"}
                      </Typography.Text>
                    </div>
                  </div>
                ) : null}

                {currentDetail?.narrative ? (
                  <Typography.Paragraph className="v2-situation-event-copy">
                    {currentDetail.narrative}
                  </Typography.Paragraph>
                ) : null}

                <footer>
                  <span>
                    <ClockCircleOutlined /> {formatClock(selectedItem.startedAt)}
                  </span>
                  <span>{audienceLabel(selectedItem.audience)}</span>
                  <span>{authorityLabel(selectedItem)}</span>
                  <Button
                    onClick={() => onOpenDetails(selectedItem.id)}
                    size="small"
                    type="link"
                  >
                    定位到技术事件 <ArrowRightOutlined />
                  </Button>
                </footer>
              </article>

              <div className="v2-situation-neighbors">
                <NeighborButton
                  direction="previous"
                  item={previousItem}
                  onSelect={onSelectMoment}
                />
                <NeighborButton
                  direction="next"
                  item={nextItem}
                  onSelect={onSelectMoment}
                />
              </div>

              <div className="v2-situation-cause">
                <header>
                  <div>
                    <Typography.Text strong>因果链路</Typography.Text>
                    <Typography.Text type="secondary">
                      当前模型请求实际收到的全部公开事实
                    </Typography.Text>
                  </div>
                  {selectedAttemptId && modelInputFacts.length ? (
                    <Tag color="blue">{modelInputFacts.length} 条</Tag>
                  ) : null}
                </header>
                <div
                  aria-label="传给模型的全部事实"
                  className="v2-situation-cause-list"
                >
                  {modelRequestQuery.isPending && selectedAttemptId ? (
                    <Typography.Text type="secondary">
                      正在读取持久化模型输入…
                    </Typography.Text>
                  ) : modelRequestQuery.isError && selectedAttemptId ? (
                    <Typography.Text type="danger">
                      模型输入读取失败，无法确认传输事实
                    </Typography.Text>
                  ) : modelInputFacts.length ? (
                    modelInputFacts.map((fact, index) => (
                      <Fragment key={`${fact.id}-${index}`}>
                        {index > 0 ? (
                          <span
                            aria-hidden="true"
                            className="v2-situation-cause-connector"
                          >
                            <ArrowDownOutlined />
                          </span>
                        ) : null}
                        <article
                          className="v2-situation-cause-step"
                          data-kind={fact.kind}
                        >
                          <header>
                            <span>
                              {fact.recordSeq !== null
                                ? `#${fact.recordSeq}`
                                : `事实 ${index + 1}`}
                            </span>
                            <strong>{fact.title}</strong>
                            {fact.context ? <small>{fact.context}</small> : null}
                          </header>
                          {fact.summary ? <p>{fact.summary}</p> : null}
                          <small>{modelFactAuthorityLabel(fact.authority)}</small>
                        </article>
                      </Fragment>
                    ))
                  ) : selectedAttemptId ? (
                    <Typography.Text type="secondary">
                      该请求没有可识别的公开事实时间线
                    </Typography.Text>
                  ) : (
                    <Typography.Text type="secondary">
                      当前事件没有调用模型，因此不存在模型输入事实
                    </Typography.Text>
                  )}
                </div>
              </div>
            </section>

            <section className="v2-situation-state">
              <header>
                <div>
                  <Typography.Title level={5}>此刻全知状态</Typography.Title>
                  <Typography.Text type="secondary">
                    {identities.filter((item) => item.alive).length}/
                    {identities.length} 人存活
                  </Typography.Text>
                </div>
                <div className="v2-situation-state-controls">
                  <div
                    aria-label="玩家状态时间口径"
                    className="v2-situation-mode is-compact"
                    role="group"
                  >
                    <button
                      aria-pressed={identityView === "moment"}
                      className={identityView === "moment" ? "is-active" : ""}
                      onClick={() => setIdentityView("moment")}
                      type="button"
                    >
                      当时
                    </button>
                    <button
                      aria-pressed={identityView === "final"}
                      className={identityView === "final" ? "is-active" : ""}
                      onClick={() => setIdentityView("final")}
                      type="button"
                    >
                      最终
                    </button>
                  </div>
                  <Typography.Text type="secondary">
                    {identityView === "moment"
                      ? "避免最终结果泄露"
                      : "终局身份状态"}
                  </Typography.Text>
                </div>
              </header>

              <div className="v2-situation-roster-wrap">
                <Table<V2PlayerIdentity>
                  className="v2-situation-roster-table"
                  columns={rosterColumns}
                  dataSource={identities}
                  pagination={false}
                  rowClassName={(identity) =>
                    involvedPlayerIds.has(identity.player_id)
                      ? "is-involved"
                      : ""
                  }
                  rowKey="player_id"
                  size="small"
                  tableLayout="fixed"
                />
              </div>
            </section>
          </div>

          <section className="v2-situation-public">
            <header>
              <Typography.Title level={5}>本轮已知公开信息</Typography.Title>
              <Typography.Text type="secondary">截至当前游标</Typography.Text>
            </header>
            <div className="v2-situation-public-grid">
              <article className="v2-situation-public-speeches">
                <header>
                  <MessageOutlined />
                  <strong>公开发言（最近 2 条）</strong>
                </header>
                {publicSpeeches.length ? (
                  <ol>
                    {publicSpeeches.map((speech) => (
                      <li key={speech.id}>
                        <time>{speech.time}</time>
                        <span>{speech.speaker}：{speech.text}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Typography.Text type="secondary">尚无公开发言</Typography.Text>
                )}
              </article>
              <article>
                <header>
                  <FlagOutlined />
                  <strong>投票进展</strong>
                </header>
                <div className="v2-situation-vote">
                  <span>已记录</span>
                  <strong>{voteSummary.count} 票</strong>
                  <ArrowRightOutlined />
                  <span>{voteSummary.leader}</span>
                </div>
                <Typography.Text type="secondary">
                  {voteSummary.detail}
                </Typography.Text>
              </article>
              <article>
                <header>
                  <SafetyCertificateOutlined />
                  <strong>公开系统消息（最近 2 条）</strong>
                </header>
                {judgeMessages.length ? (
                  <ol>
                    {judgeMessages.map((message) => (
                      <li key={message.id}>
                        <time>{message.time}</time>
                        <span>{message.text}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Typography.Text type="secondary">尚无公开系统消息</Typography.Text>
                )}
              </article>
            </div>
          </section>

          <button
            className="v2-situation-diagnostics"
            onClick={() => onOpenDetails(selectedItem.id)}
            type="button"
          >
            <ThunderboltOutlined />
            展开诊断详情（模型请求 / 状态变更 / 原始日志）
            <ArrowRightOutlined />
          </button>
        </>
      ) : (
        <Empty
          description="首个事实动作产生后即可查看全知战局态势"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      )}
      <Modal
        footer={null}
        onCancel={() => setPrivateInfoPlayerId(null)}
        open={Boolean(privateInfoIdentity)}
        title={
          privateInfoIdentity
            ? `${privateInfoIdentity.seat}号 ${privateInfoIdentity.display_name} · 全部私有信息`
            : "全部私有信息"
        }
        width={520}
      >
        <ol className="v2-situation-private-info-list">
          {privateInfoItems.map((item, index) => (
            <li key={`${index}-${item}`}>
              <span>{index + 1}</span>
              <Typography.Text>{item}</Typography.Text>
            </li>
          ))}
        </ol>
      </Modal>
    </section>
  );
}

function NeighborButton({
  direction,
  item,
  onSelect,
}: {
  direction: "previous" | "next";
  item: V2TimelineItem | null;
  onSelect: (id: string, phaseId: string) => void;
}) {
  const previous = direction === "previous";
  return (
    <button
      aria-label={previous ? "查看上一事件" : "查看下一事件"}
      disabled={!item}
      onClick={() => {
        if (item) onSelect(item.id, item.phaseId);
      }}
      type="button"
    >
      <span>{previous ? "上一条事实" : "下一条事实"}</span>
      <strong>{item ? `${item.actorLabel} · ${item.label}` : "没有更多事件"}</strong>
      {previous ? <ArrowLeftOutlined /> : <ArrowRightOutlined />}
    </button>
  );
}

function StageIcon({ stage }: { stage: string }): ReactNode {
  if (stage === "night" || stage === "attack") return <MoonOutlined />;
  if (stage === "dawn" || stage === "day") return <SunOutlined />;
  if (stage === "speech") return <MessageOutlined />;
  if (stage === "vote" || stage === "exile") return <FlagOutlined />;
  if (stage === "guard" || stage === "investigate") {
    return <SafetyCertificateOutlined />;
  }
  if (stage === "result") return <EyeOutlined />;
  return <UserOutlined />;
}

function buildSituationPhases(
  timeline: V2TimelineItem[],
  currentPhaseId: string,
  summaries: V2RoundSummary[],
): SituationPhase[] {
  const groups = groupV2Phases(timeline, currentPhaseId);
  const visibleGroups =
    groups.some((group) => group.phaseId !== "opening")
      ? groups.filter((group) => group.phaseId !== "opening")
      : groups;
  return visibleGroups.flatMap((group) => {
    const stages = new Map<string, SituationStage>();
    for (const item of group.items) {
      const meta = stageMeta(item);
      if (!meta) continue;
      const previous = stages.get(meta.key);
      const priority = situationItemPriority(item);
      const previousPriority = previous
        ? situationItemPriority(previous.item)
        : null;
      if (
        !previous ||
        previousPriority === null ||
        priority > previousPriority ||
        (priority === previousPriority &&
          isLaterTimelineItem(item, previous.item))
      ) {
        stages.set(meta.key, { ...meta, item });
      }
    }
    if (!stages.size && group.items.length) {
      const item = group.items[group.items.length - 1];
      stages.set("progress", { item, key: "progress", label: "进度" });
    }
    if (!stages.size) return [];
    return [
      {
        digest: phaseDigest(group.phaseId, summaries),
        label: group.label,
        phaseId: group.phaseId,
        stages: [...stages.values()].sort(
          (left, right) =>
            situationStageOrder.indexOf(left.key) -
            situationStageOrder.indexOf(right.key),
        ),
      },
    ];
  });
}

function latestTimelineItem(
  timeline: V2TimelineItem[],
): V2TimelineItem | null {
  return timeline.reduce<V2TimelineItem | null>(
    (latest, item) =>
      latest === null || isLaterTimelineItem(item, latest) ? item : latest,
    null,
  );
}

function isLaterTimelineItem(
  candidate: V2TimelineItem,
  current: V2TimelineItem,
): boolean {
  if (candidate.lastRecordSeq !== current.lastRecordSeq) {
    return candidate.lastRecordSeq > current.lastRecordSeq;
  }
  return candidate.firstRecordSeq > current.firstRecordSeq;
}

function situationItemPriority(item: V2TimelineItem): number {
  const actionType = item.actionType.toLowerCase();
  if (actionType.includes("result")) return 11;
  if (item.actorKind === "player" && item.modelRequest) return 10;
  if (actionType.includes("decision")) return 9;
  if (actionType.includes("announcement")) return 5;
  if (actionType.includes("wake")) return 2;
  if (actionType.includes("sleep")) return 1;
  return 4;
}

const situationStageOrder = [
  "opening",
  "night",
  "attack",
  "guard",
  "investigate",
  "medicine",
  "dawn",
  "sheriff",
  "speech",
  "vote",
  "exile",
  "result",
  "progress",
];

function stageMeta(
  item: V2TimelineItem,
): { key: string; label: string } | null {
  const value = item.actionType.toLowerCase();
  if (value.includes("game_completed")) return { key: "result", label: "结算" };
  if (value.includes("werewolf") && value.includes("attack")) {
    return { key: "attack", label: "袭击" };
  }
  if (value.includes("guard") || value.includes("protect")) {
    return { key: "guard", label: "守护" };
  }
  if (value.includes("seer") || value.includes("investigate")) {
    return { key: "investigate", label: "查验" };
  }
  if (value.includes("witch") || value.includes("heal") || value.includes("poison")) {
    return { key: "medicine", label: "用药" };
  }
  if (value.includes("nightfall")) return { key: "night", label: "入夜" };
  if (value.includes("dawn")) return { key: "dawn", label: "天亮" };
  if (value.includes("sheriff")) return { key: "sheriff", label: "竞选" };
  if (value.includes("speech") || value.includes("discussion")) {
    return { key: "speech", label: "发言" };
  }
  if (value.includes("vote")) return { key: "vote", label: "投票" };
  if (value.includes("exile")) return { key: "exile", label: "放逐" };
  if (value.includes("opening")) return { key: "opening", label: "开场" };
  return null;
}

function phaseDigest(
  phaseId: string,
  summaries: V2RoundSummary[],
): string | null {
  const roundNo = roundFromPhase(phaseId);
  if (roundNo === null) return null;
  const summary = summaries.find((item) => item.roundNo === roundNo);
  if (!summary) return null;
  const isNight = phaseId === "first_night" || phaseId.startsWith("night_");
  const highlights = summary.highlights.filter((highlight) =>
    isNight
      ? highlight.kind === "night" || highlight.kind === "ability"
      : highlight.kind !== "night",
  );
  return highlights[0]?.label ?? (summary.status === "running" ? "进行中" : null);
}

function describeSituationItem(
  game: V2GameRecordDetail,
  item: V2TimelineItem,
  recordSeq: number,
  identities: Map<string, V2PlayerIdentity>,
): SituationDetail {
  const activation = activationForItem(game, item, recordSeq);
  if (activation) {
    const decision = recordObject(activation.decision);
    const actorId = recordText(activation.actor_player_id);
    const abilityId = abilityIdForActivation(game, activation);
    const targetId = recordText(decision.target_player_id);
    return {
      actorLabel: actorId ? playerLabel(actorId, identities) : undefined,
      actorSeat: actorId ? identities.get(actorId)?.seat : undefined,
      danger:
        recordText(recordObject(activation.result).alignment) === "werewolves",
      eventLabel: `${abilityLabel(abilityId)}完成`,
      narrative: activationNarrative(activation),
      resultLabel: activationResultLabel(activation),
      targetId,
      targetLabel: targetId ? playerLabel(targetId, identities) : null,
    };
  }

  const vote = [...item.events]
    .reverse()
    .find((event) => event.event_type === "day_vote_committed");
  if (vote) {
    const targetId = recordText(vote.payload.target_player_id);
    return {
      danger: false,
      narrative:
        recordText(vote.payload.reason) ??
        item.presentation?.subtitle_text ??
        item.objective,
      resultLabel: "投票已记录",
      targetId,
      targetLabel: targetId ? playerLabel(targetId, identities) : null,
    };
  }

  const completed = [...item.events]
    .reverse()
    .find((event) => event.event_type === "game_completed");
  if (completed) {
    const winner = winnerLabel(recordText(completed.payload.winner));
    return {
      danger: false,
      narrative: `${winner}获胜`,
      resultLabel: "对局已结算",
      targetId: null,
      targetLabel: null,
    };
  }

  const speech = [...item.events]
    .reverse()
    .find((event) => event.event_type === "day_speech_committed");
  const narrative =
    recordText(speech?.payload.speech) ??
    (item.presentation
      ? displaySubtitleText(item.presentation.subtitle_text)
      : null) ??
    item.objective;
  return {
    danger: item.status === "failed",
    narrative,
    resultLabel:
      item.status === "failed"
        ? "动作失败"
        : item.status === "running"
          ? "执行中"
          : "动作成功",
    targetId: null,
    targetLabel: null,
  };
}

function activationForItem(
  game: V2GameRecordDetail,
  item: V2TimelineItem,
  recordSeq: number,
) {
  const opened = item.events.find((event) => event.event_type === "action_opened");
  const context = recordObject(opened?.payload.context);
  const activationId = recordText(context.activation_id);
  const visibleActivations = activationsAt(game, recordSeq);
  if (activationId) {
    return (
      visibleActivations.find(
        (activation) => recordText(activation.activation_id) === activationId,
      ) ?? null
    );
  }

  const actionType = item.actionType.toLowerCase();
  const abilityPrefix = actionType.includes("seer")
    ? "seer."
    : actionType.includes("guard")
      ? "guard."
      : actionType.includes("werewolf")
        ? "werewolf."
        : actionType.includes("witch")
          ? "witch."
          : null;
  if (!abilityPrefix) return null;
  return (
    [...visibleActivations]
      .reverse()
      .find((activation) =>
        abilityIdForActivation(game, activation).startsWith(abilityPrefix),
      ) ?? null
  );
}

function activationsAt(game: V2GameRecordDetail, recordSeq: number) {
  const latestEventSeq = game.events.reduce(
    (latest, event) => Math.max(latest, event.record_seq),
    0,
  );
  const terminalByActivation = new Map<string, number>();
  for (const event of game.events) {
    if (
      event.event_type !== "ability_activation_completed" &&
      event.event_type !== "ability_activation_skipped"
    ) {
      continue;
    }
    const activationId = recordText(event.payload.activation_id);
    if (activationId) terminalByActivation.set(activationId, event.record_seq);
  }
  return game.ability_activations.filter((activation) => {
    const activationId = recordText(activation.activation_id);
    if (!activationId) return false;
    const terminalSeq = terminalByActivation.get(activationId);
    return terminalSeq === undefined
      ? recordSeq >= latestEventSeq
      : terminalSeq <= recordSeq;
  });
}

function privateInformationByPlayer(
  game: V2GameRecordDetail,
  activations: Array<Record<string, unknown>>,
  recordSeq: number,
  identities: Map<string, V2PlayerIdentity>,
) {
  const abilityByInstance = new Map(
    game.ability_instances.map((instance) => [
      recordText(instance.ability_instance_id),
      recordText(instance.ability_id) ?? "unknown",
    ]),
  );
  const collected = new Map<
    string,
    { action?: string; results: string[] }
  >();
  const addInformation = (
    playerId: string,
    information: string,
  ) => {
    const current = collected.get(playerId) ?? { results: [] };
    if (!current.results.includes(information)) {
      current.results.push(information);
    }
    collected.set(playerId, current);
  };
  const visibleActivationIds = new Set(
    activations
      .map((activation) => recordText(activation.activation_id))
      .filter((value): value is string => Boolean(value)),
  );
  const knowledgeRecordSeqById = new Map(
    game.events
      .filter((event) => event.event_type === "private_knowledge_recorded")
      .map((event) => [
        recordText(event.payload.knowledge_fact_id),
        event.record_seq,
      ])
      .filter(
        (entry): entry is [string, number] =>
          entry[0] !== null,
      ),
  );

  for (const fact of game.knowledge_facts) {
    if (recordText(fact.owner_scope) !== "player") continue;
    const ownerId = recordText(fact.owner_id);
    if (!ownerId) continue;
    const factId = recordText(fact.knowledge_fact_id);
    const factRecordSeq = factId
      ? knowledgeRecordSeqById.get(factId)
      : undefined;
    if (factRecordSeq !== undefined && factRecordSeq > recordSeq) continue;
    const sourceActivationId = recordText(fact.source_activation_id);
    if (
      sourceActivationId &&
      !visibleActivationIds.has(sourceActivationId)
    ) {
      continue;
    }
    if (
      factRecordSeq === undefined &&
      !sourceActivationId &&
      recordSeq < game.last_record_seq
    ) {
      continue;
    }
    const information = privateKnowledgeFactLabel(fact, identities);
    if (information) addInformation(ownerId, information);
  }

  for (const activation of activations) {
    const actorId = recordText(activation.actor_player_id);
    if (!actorId) continue;
    const abilityId =
      abilityByInstance.get(recordText(activation.ability_instance_id)) ??
      "unknown";
    const decision = recordObject(activation.decision);
    const targetId = recordText(decision.target_player_id);
    const current = collected.get(actorId) ?? { results: [] };
    current.action = `${abilityLabel(abilityId)}${
      targetId ? ` → ${playerLabel(targetId, identities)}` : ""
    }`;
    collected.set(actorId, current);
  }
  return new Map(
    [...collected].map(([playerId, information]) => [
      playerId,
      {
        action: information.action,
        results: information.results,
      },
    ]),
  );
}

function privateKnowledgeFactLabel(
  fact: Record<string, unknown>,
  identities: Map<string, V2PlayerIdentity>,
): string | null {
  const factType = recordText(fact.fact_type);
  const payload = recordObject(fact.payload);
  const nightNo = recordNumber(payload.night_no);
  const nightPrefix = nightNo === null ? "" : `第${nightNo}夜`;

  if (factType === "investigation_alignment") {
    const targetId = recordText(payload.target_player_id);
    const alignment = recordText(payload.alignment);
    if (!targetId || !alignment) return null;
    return `${nightPrefix}查验：${playerLabel(
      targetId,
      identities,
    )}为${teamLabel(alignment)}`;
  }
  if (factType === "werewolf_attack_resolved") {
    const targetId = recordText(payload.final_target_player_id);
    if (!targetId) return null;
    return `${nightPrefix}袭击目标：${playerLabel(targetId, identities)}`;
  }
  if (factType === "witch_attack_observation") {
    const targetId = recordText(payload.attacked_player_id);
    if (!targetId) return null;
    return `${nightPrefix}获知：${playerLabel(targetId, identities)}被袭击`;
  }
  return null;
}

function recentPublicSpeeches(
  events: V2GameRecordEvent[],
  recordSeq: number,
  identities: Map<string, V2PlayerIdentity>,
  phaseId: string,
) {
  const roundNo = roundFromPhase(phaseId);
  return events
    .filter(
      (event) =>
        event.event_type === "day_speech_committed" &&
        event.record_seq <= recordSeq &&
        (roundNo === null || recordNumber(event.payload.round_no) === roundNo),
    )
    .slice(-2)
    .map((event) => ({
      id: event.event_id,
      speaker: playerLabel(recordText(event.payload.player_id), identities),
      text: recordText(event.payload.speech) ?? "发言已记录",
      time: formatClock(event.created_at),
    }));
}

function publicVoteSummary(
  events: V2GameRecordEvent[],
  recordSeq: number,
  identities: Map<string, V2PlayerIdentity>,
  phaseId: string,
) {
  const roundNo = roundFromPhase(phaseId);
  const votes = events.filter(
    (event) =>
      event.event_type === "day_vote_committed" &&
      event.record_seq <= recordSeq &&
      (roundNo === null || recordNumber(event.payload.round_no) === roundNo),
  );
  const totals = new Map<string, number>();
  for (const vote of votes) {
    const targetId = recordText(vote.payload.target_player_id);
    if (targetId) totals.set(targetId, (totals.get(targetId) ?? 0) + 1);
  }
  const [leaderId, leaderCount] =
    [...totals.entries()].sort((left, right) => right[1] - left[1])[0] ?? [];
  return {
    count: votes.length,
    detail: votes.length
      ? `当前最高 ${leaderCount ?? 0} 票`
      : "投票开始后将实时累计",
    leader: leaderId
      ? `${playerLabel(leaderId, identities)}领先`
      : "尚无人被投",
  };
}

function recentJudgeMessages(
  timeline: V2TimelineItem[],
  recordSeq: number,
) {
  return timeline
    .filter(
      (item) =>
        item.actorKind === "judge" &&
        item.presentation &&
        item.lastRecordSeq <= recordSeq &&
        item.audience === "all",
    )
    .slice(-2)
    .map((item) => ({
      id: item.id,
      text: truncate(
        displaySubtitleText(item.presentation?.subtitle_text ?? item.label),
        52,
      ),
      time: formatClock(item.startedAt),
    }));
}

function abilityIdForActivation(
  game: V2GameRecordDetail,
  activation: Record<string, unknown>,
) {
  const instanceId = recordText(activation.ability_instance_id);
  const instance = game.ability_instances.find(
    (candidate) => recordText(candidate.ability_instance_id) === instanceId,
  );
  return recordText(instance?.ability_id) ?? "unknown";
}

function activationNarrative(activation: Record<string, unknown>): string | null {
  const decision = recordObject(activation.decision);
  return recordText(decision.speech);
}

function activationResultLabel(activation: Record<string, unknown>): string {
  const status = recordText(activation.status);
  if (status === "skipped") return "角色行动已跳过";
  const result = recordObject(activation.result);
  const alignment = recordText(result.alignment);
  if (alignment) return `查验为${teamLabel(alignment)}`;
  if (result.consensus_reached === true) return "袭击目标已确认";
  if (result.consensus_reached === false) return "未达成袭击共识";
  if (result.effect === "protect_registered") return "守护已登记";
  if (result.heal_used === true) return "已使用解药";
  if (result.poison_used === true) return "已使用毒药";
  return status === "completed" ? "行动已完成" : status ?? "事实已记录";
}

function authorityLabel(item: V2TimelineItem): string {
  if (item.kind === "milestone" || item.templateRender) return "权威事实";
  if (
    item.actionType.includes("speech") ||
    item.actionType.includes("discussion")
  ) {
    return "玩家声称";
  }
  return item.modelRequest ? "模型行动 · 结果已落库" : "权威事实";
}

function audienceLabel(value: string): string {
  const labels: Record<string, string> = {
    all: "公开",
    public: "公开",
    god: "上帝视角",
    god_view: "上帝视角",
    private: "私密",
    legacy_unknown: "旧记录范围未知",
  };
  return labels[value] ?? value;
}

function playerLabel(
  playerId: string | null,
  identities: Map<string, V2PlayerIdentity>,
): string {
  if (!playerId) return "无人";
  const identity = identities.get(playerId);
  return identity
    ? `${identity.seat}号 ${identity.display_name}`
    : playerId;
}

function roleLabel(value: string): string {
  const labels: Record<string, string> = {
    guard: "守卫",
    hunter: "猎人",
    idiot: "白痴",
    seer: "预言家",
    villager: "村民",
    werewolf: "狼人",
    witch: "女巫",
  };
  return labels[value] ?? value;
}

function roleColor(value: string): string {
  if (value === "werewolf") return "red";
  if (value === "villager") return "default";
  return "blue";
}

function teamLabel(value: string): string {
  const labels: Record<string, string> = {
    village: "好人阵营",
    villagers: "好人阵营",
    werewolf: "狼人阵营",
    werewolves: "狼人阵营",
  };
  return labels[value] ?? value;
}

function deathCauseLabel(value: string | null): string {
  const labels: Record<string, string> = {
    exile: "投票放逐",
    hunter_shot: "猎人带走",
    night_resolution: "夜间结算",
    poison: "女巫毒杀",
    werewolf_attack: "狼人袭击",
    werewolf_self_explosion: "狼人自爆",
    witch_poison: "女巫毒杀",
  };
  return value ? (labels[value] ?? value) : "—";
}

function modelFactAuthorityLabel(value: string | null): string {
  const labels: Record<string, string> = {
    judge_fact: "法官权威事实",
    player_claim_unverified: "玩家声明（未验证）",
  };
  return value ? (labels[value] ?? value) : "公开事实";
}

function winnerLabel(value: string | null): string {
  if (value === "villagers" || value === "village") return "好人阵营";
  if (value === "werewolves" || value === "werewolf") return "狼人阵营";
  return value ?? "未知阵营";
}

function roundFromPhase(phaseId: string): number | null {
  if (phaseId === "first_night") return 1;
  const match = /^(?:day|night)_(\d+)$/.exec(phaseId);
  return match ? Number(match[1]) : null;
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

function truncate(value: string, maxLength: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > maxLength
    ? `${normalized.slice(0, maxLength)}…`
    : normalized;
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
      typeof parsed.speech === "string"
    ) {
      return parsed.speech.trim();
    }
  } catch {
    return trimmed;
  }
  return trimmed;
}
