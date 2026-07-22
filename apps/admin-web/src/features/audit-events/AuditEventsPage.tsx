import ReloadOutlined from "@ant-design/icons/es/icons/ReloadOutlined";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Flex from "antd/es/flex";
import Input from "antd/es/input";
import Pagination from "antd/es/pagination";
import Select from "antd/es/select";
import Table, { type ColumnsType } from "antd/es/table";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import {
  AdminEmpty,
  AdminError,
  AdminPage,
  AdminPageHeader,
} from "@/components/admin/AdminPage";
import { listAdminAuditEvents } from "@/features/audit-events/api";
import { adminAuditKeys } from "@/features/audit-events/query-keys";
import type {
  AdminAuditEvent,
  AdminAuditParams,
} from "@/features/audit-events/types";

export default function AuditEventsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = paramsFromSearch(searchParams);
  const invalidRange = Boolean(
    params.created_from &&
      params.created_to &&
      params.created_from > params.created_to,
  );
  const query = useQuery({
    enabled: !invalidRange,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => listAdminAuditEvents(params, signal),
    queryKey: adminAuditKeys.list(params),
  });

  function update(values: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, nextValue] of Object.entries({ page: "1", ...values })) {
      if (nextValue) next.set(key, nextValue);
      else next.delete(key);
    }
    setSearchParams(next);
  }

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    update({
      action: value(data, "action"),
      q: value(data, "q"),
      resource_type: value(data, "resource_type"),
    });
  }

  const columns: ColumnsType<AdminAuditEvent> = [
    {
      key: "action",
      render: (_, event) => (
        <Flex gap={2} vertical>
          <Typography.Text strong>{event.action}</Typography.Text>
          <Typography.Text type="secondary">
            {event.actor
              ? `${event.actor.display_name} · ${event.actor.email}`
              : "系统或未知操作者"}
          </Typography.Text>
        </Flex>
      ),
      title: "操作 / 操作者",
    },
    {
      dataIndex: "result",
      key: "result",
      render: (result: string) => (
        <Tag color={result === "success" ? "success" : "error"}>
          {result === "success" ? "成功" : "失败"}
        </Tag>
      ),
      title: "结果",
    },
    {
      key: "resource",
      render: (_, event) => (
        <Flex gap={2} vertical>
          <Typography.Text strong>
            {event.resource_type}{event.resource_id ? ` · ${event.resource_id}` : ""}
          </Typography.Text>
          <Typography.Text type="secondary">{event.reason ?? "未记录原因"}</Typography.Text>
        </Flex>
      ),
      title: "资源 / 原因",
    },
    {
      key: "time",
      render: (_, event) => (
        <Flex gap={2} vertical>
          <span>{formatDate(event.created_at)}</span>
          <Typography.Text type="secondary">
            {event.request_id ? `请求 ${event.request_id}` : "无请求编号"}
          </Typography.Text>
        </Flex>
      ),
      title: "发生时间",
    },
  ];

  return (
    <AdminPage className="system-page">
      <AdminPageHeader
        description="查询后台身份、内容和运营操作的不可变审计记录。"
        extra={
          <Button
            icon={<ReloadOutlined />}
            loading={query.isFetching}
            onClick={() => void query.refetch()}
          >
            手动刷新
          </Button>
        }
        kicker="SECURITY LEDGER"
        title="审计日志"
      />
      <Card title="筛选条件">
        <form className="ant-admin-filter-grid" onSubmit={apply} role="search">
          <label className="ant-filter-wide">
            <span>搜索审计</span>
            <Input defaultValue={params.q ?? ""} name="q" placeholder="操作者、资源或请求编号" type="search" />
          </label>
          <label>
            <span>操作类型</span>
            <Input defaultValue={params.action ?? ""} name="action" placeholder="admin.user.update" />
          </label>
          <label>
            <span>结果</span>
            <Select
              aria-label="审计结果"
              onChange={(value) => update({ result: value || undefined })}
              options={[
                { label: "全部结果", value: "" },
                { label: "成功", value: "success" },
                { label: "失败", value: "failure" },
              ]}
              value={params.result ?? ""}
            />
          </label>
          <label>
            <span>资源类型</span>
            <Input defaultValue={params.resource_type ?? ""} name="resource_type" placeholder="user" />
          </label>
          <label>
            <span>开始日期</span>
            <Input aria-label="审计开始日期" onChange={(event) => update({ created_from: event.target.value || undefined })} type="date" value={params.created_from ?? ""} />
          </label>
          <label>
            <span>结束日期</span>
            <Input aria-label="审计结束日期" onChange={(event) => update({ created_to: event.target.value || undefined })} type="date" value={params.created_to ?? ""} />
          </label>
          <label>
            <span>排序</span>
            <Select
              aria-label="审计排序"
              onChange={(value) => update({ direction: value })}
              options={[
                { label: "最近发生", value: "desc" },
                { label: "最早发生", value: "asc" },
              ]}
              value={params.direction}
            />
          </label>
          <Flex align="flex-end" gap={8}>
            <Button onClick={() => setSearchParams({})}>清除筛选</Button>
            <Button htmlType="submit" type="primary">应用筛选</Button>
          </Flex>
        </form>
      </Card>
      {invalidRange ? (
        <Alert role="alert" showIcon title="开始日期不能晚于结束日期，请调整后重新筛选。" type="warning" />
      ) : null}
      {query.isError ? (
        <AdminError
          description={isAdminApiError(query.error) ? query.error.message : "审计服务暂时不可用。"}
          onRetry={query.refetch}
          title="无法读取审计日志"
        />
      ) : (
        <Card
          extra={<Typography.Text type="secondary">共 {query.data?.pagination.total ?? 0} 条记录</Typography.Text>}
          styles={{ body: { padding: 0 } }}
          title={<h2>安全操作记录</h2>}
        >
          <Table<AdminAuditEvent>
            columns={columns}
            dataSource={query.data?.items ?? []}
            loading={query.isPending}
            locale={{ emptyText: <AdminEmpty description="没有符合条件的审计记录；调整筛选条件后重试。" /> }}
            pagination={false}
            rowKey="id"
            scroll={{ x: 900 }}
          />
        </Card>
      )}
      {query.data ? (
        <Flex justify="flex-end">
          <Pagination
            current={query.data.pagination.page}
            onChange={(nextPage) => update({ page: String(nextPage) })}
            pageSize={query.data.pagination.page_size}
            showSizeChanger={false}
            total={query.data.pagination.total}
          />
        </Flex>
      ) : null}
    </AdminPage>
  );
}

function paramsFromSearch(search: URLSearchParams): AdminAuditParams {
  const direction = search.get("direction");
  return {
    action: read(search, "action"),
    created_from: read(search, "created_from"),
    created_to: read(search, "created_to"),
    direction: direction === "asc" ? "asc" : "desc",
    page: Math.max(1, Number(search.get("page")) || 1),
    page_size: 20,
    q: read(search, "q"),
    resource_type: read(search, "resource_type"),
    result: read(search, "result"),
  };
}

function read(search: URLSearchParams, key: string) {
  return search.get(key)?.trim() || undefined;
}

function value(data: FormData, key: string) {
  return String(data.get(key) ?? "").trim() || undefined;
}

function formatDate(input: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(input));
}
