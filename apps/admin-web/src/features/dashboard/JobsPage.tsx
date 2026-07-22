import ReloadOutlined from "@ant-design/icons/es/icons/ReloadOutlined";
import { useQuery } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Flex from "antd/es/flex";
import Pagination from "antd/es/pagination";
import Select from "antd/es/select";
import Space from "antd/es/space";
import Table, { type ColumnsType } from "antd/es/table";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { useSearchParams } from "react-router-dom";

import { AdminPage, AdminPageHeader } from "@/components/admin/AdminPage";
import { useAdminSession } from "@/features/auth/session-context";
import { listAdminJobs } from "@/features/dashboard/api";
import type {
  AdminJob,
  AdminJobStatus,
} from "@/features/dashboard/types";

const STATUSES: AdminJobStatus[] = ["queued", "running", "completed", "failed"];
const STATUS_LABELS: Record<AdminJobStatus, string> = {
  completed: "已完成",
  failed: "失败",
  queued: "排队中",
  running: "执行中",
};
const STATUS_COLORS: Record<AdminJobStatus, string> = {
  completed: "success",
  failed: "error",
  queued: "default",
  running: "processing",
};

export default function JobsPage() {
  const { runtimeMode } = useAdminSession();
  const [search, setSearch] = useSearchParams();
  const page = Math.max(1, Number(search.get("page")) || 1);
  const rawStatus = search.get("status");
  const status = STATUSES.includes(rawStatus as AdminJobStatus)
    ? (rawStatus as AdminJobStatus)
    : undefined;
  const highlightedJob = search.get("job");
  const jobs = useQuery({
    queryFn: ({ signal }) =>
      runtimeMode === "preview"
        ? { items: [], pagination: { page: 1, page_size: 20, total: 0, pages: 0 } }
        : listAdminJobs({ page, page_size: 20, status }, signal),
    queryKey: ["admin", "dashboard", "jobs", { page, status }],
    refetchInterval: runtimeMode === "authenticated" ? 10_000 : false,
  });

  function updateStatus(next: string) {
    const params = new URLSearchParams(search);
    if (next) params.set("status", next);
    else params.delete("status");
    params.delete("page");
    setSearch(params);
  }

  function updatePage(nextPage: number) {
    setSearch((current) => {
      const next = new URLSearchParams(current);
      next.set("page", String(nextPage));
      return next;
    });
  }

  const columns: ColumnsType<AdminJob> = [
    {
      key: "job",
      render: (_, job) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text strong>
            {job.mode === "missing" ? "生成缺失语音" : "重新生成全部"}
          </Typography.Text>
          <Typography.Text copyable={{ text: job.id }} type="secondary">
            {job.id}
          </Typography.Text>
        </Space>
      ),
      title: "任务",
    },
    {
      dataIndex: "status",
      key: "status",
      render: (value: AdminJobStatus) => (
        <Tag color={STATUS_COLORS[value]}>{STATUS_LABELS[value]}</Tag>
      ),
      title: "状态",
    },
    {
      key: "progress",
      render: (_, job) => `${job.processed_count} / ${job.total_count}`,
      title: "进度",
    },
    {
      key: "result",
      render: (_, job) =>
        job.error_code ?? `生成 ${job.generated_count} · 失败 ${job.failed_count}`,
      title: "结果",
    },
    {
      dataIndex: "created_at",
      key: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN"),
      title: "创建时间",
    },
  ];

  return (
    <AdminPage className="dashboard-page">
      <AdminPageHeader
        description="查看持久语音任务的领取、进度和稳定错误分类。"
        kicker="SYSTEM / JOBS"
        title="后台任务"
      />
      <Card>
        <Flex align="center" gap={12} justify="space-between" wrap>
          <Select
            aria-label="任务状态"
            onChange={updateStatus}
            options={[
              { label: "全部状态", value: "" },
              ...STATUSES.map((item) => ({ label: STATUS_LABELS[item], value: item })),
            ]}
            style={{ minWidth: 160 }}
            value={status ?? ""}
          />
          <Button
            icon={<ReloadOutlined />}
            loading={jobs.isFetching}
            onClick={() => void jobs.refetch()}
          >
            刷新
          </Button>
        </Flex>
      </Card>
      {jobs.isError ? (
        <Alert role="alert" showIcon title="任务列表暂时不可用。" type="error" />
      ) : null}
      <Card styles={{ body: { padding: 0 } }}>
        <Table<AdminJob>
          columns={columns}
          dataSource={jobs.data?.items ?? []}
          loading={jobs.isPending}
          locale={{ emptyText: "当前没有符合条件的持久任务。" }}
          pagination={false}
          rowClassName={(job) => (highlightedJob === job.id ? "is-highlighted" : "")}
          rowKey="id"
          scroll={{ x: 840 }}
        />
      </Card>
      {jobs.data && jobs.data.pagination.total > 0 ? (
        <Flex justify="flex-end">
          <Pagination
            current={page}
            onChange={updatePage}
            pageSize={20}
            showSizeChanger={false}
            total={jobs.data.pagination.total}
          />
        </Flex>
      ) : null}
    </AdminPage>
  );
}
