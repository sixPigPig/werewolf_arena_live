import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Card from "antd/es/card";
import Flex from "antd/es/flex";
import Pagination from "antd/es/pagination";
import Table, { type ColumnsType } from "antd/es/table";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { Link, useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import {
  AdminEmpty,
  AdminError,
  AdminPage,
  AdminPageHeader,
} from "@/components/admin/AdminPage";
import { listGameRecords } from "@/match/game-records/api";
import { gameRecordKeys } from "@/match/game-records/query-keys";
import type { GameRecordListItem } from "@/match/game-records/types";

export default function GameRecordsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const query = useQuery({
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => listGameRecords(page, signal),
    queryKey: gameRecordKeys.list(page),
  });
  const columns: ColumnsType<GameRecordListItem> = [
    {
      key: "game",
      render: (_, game) => (
        <Flex vertical>
          <Typography.Text strong>{game.title}</Typography.Text>
          <Typography.Text copyable type="secondary">{game.game_id}</Typography.Text>
        </Flex>
      ),
      title: "对局",
    },
    {
      key: "status",
      render: (_, game) => (
        <Flex gap={2} vertical>
          <Tag color={matchStatusColor(game.match_status)}>
            {matchResultLabel(game.match_status, game.winner)}
          </Tag>
          <Typography.Text type="secondary">
            实时流：{game.status} · 执行器：{executionStateLabel(game.execution_state)}
          </Typography.Text>
          <Typography.Text type="secondary">{game.current_run_id}</Typography.Text>
        </Flex>
      ),
      title: "比赛 / 实时流 / 执行器",
    },
    {
      key: "audio",
      render: (_, game) => <Tag>{audioModeLabel(game.audio_mode)}</Tag>,
      title: "音频",
    },
    {
      key: "sequence",
      render: (_, game) => (
        <Flex gap={2} vertical>
          <Typography.Text strong>事实 #{game.last_record_seq}</Typography.Text>
          <Typography.Text type="secondary">展示 #{game.last_presentation_seq}</Typography.Text>
        </Flex>
      ),
      title: "序列游标",
    },
    {
      dataIndex: "created_at",
      key: "created_at",
      render: (value: string) => formatDate(value),
      title: "创建时间",
    },
    {
      key: "action",
      render: (_, game) => <Link to={`/v2/operations/games/${game.game_id}`}>查看记录</Link>,
      title: "操作",
    },
  ];

  return (
    <AdminPage className="v2-game-records-page">
      <AdminPageHeader
        description="只读取全新的 V2 事实序列与展示序列，不投影旧对局记录。"
        extra={<Tag color="blue">独立记录模型</Tag>}
        kicker="LIVE V2 LEDGER"
        title="V2 对局记录"
      />
      {query.isError ? (
        <AdminError
          description={isAdminApiError(query.error) ? query.error.message : "V2 对局记录服务暂时不可用。"}
          onRetry={query.refetch}
          requestId={isAdminApiError(query.error) ? query.error.requestId : null}
          title="无法读取 V2 对局"
        />
      ) : (
        <Card
          extra={<Typography.Text type="secondary">{query.data ? `共 ${query.data.pagination.total} 场` : "正在统计..."}</Typography.Text>}
          styles={{ body: { padding: 0 } }}
          title={<h2 id="v2-game-list-title">新对局账本</h2>}
        >
          <Table<GameRecordListItem>
            columns={columns}
            dataSource={query.data?.items ?? []}
            loading={query.isPending}
            locale={{
              emptyText: (
                <AdminEmpty description="还没有 V2 对局；通过 V2 创建接口建立的对局会出现在这里。" />
              ),
            }}
            pagination={false}
            rowKey="game_id"
            scroll={{ x: 980 }}
          />
        </Card>
      )}
      {query.data && query.data.pagination.total > 0 ? (
        <Flex justify="flex-end">
          <Pagination
            current={page}
            onChange={(nextPage) => setSearchParams({ page: String(nextPage) })}
            pageSize={query.data.pagination.page_size}
            showSizeChanger={false}
            total={query.data.pagination.total}
          />
        </Flex>
      ) : null}
    </AdminPage>
  );
}

function formatDate(input: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(input));
}

function matchResultLabel(status: string, winner: string | null) {
  if (status === "completed") {
    if (winner === "villagers") return "已完成 · 好人胜利";
    if (winner === "werewolves") return "已完成 · 狼人胜利";
    return "终局证据不完整";
  }
  return {
    waiting: "等待开始",
    running: "进行中",
    failed: "比赛失败",
    canceled: "比赛已中止",
  }[status] ?? status;
}

function matchStatusColor(status: string) {
  if (status === "completed") return "success";
  if (status === "running") return "processing";
  if (status === "failed" || status === "canceled") return "error";
  return "default";
}

function executionStateLabel(state: string) {
  return {
    unowned: "未持有",
    owned: "执行中",
    stale: "失联",
    stopped: "已停止",
  }[state] ?? state;
}

function audioModeLabel(mode: string) {
  return {
    tts: "语音播报",
    text_only: "纯文本",
    legacy_unknown: "旧记录未知",
  }[mode] ?? mode;
}
