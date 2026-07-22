import { useQuery } from "@tanstack/react-query";
import SearchOutlined from "@ant-design/icons/es/icons/SearchOutlined";
import Card from "antd/es/card";
import Input from "antd/es/input";
import Spin from "antd/es/spin";
import Typography from "antd/es/typography";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { searchAdminResources } from "@/features/dashboard/api";
import type { AdminRuntimeMode } from "@/features/auth/types";

const TYPE_LABELS = { run: "运行", game: "对局", player: "玩家", job: "任务" };

export function GlobalAdminSearch({ runtimeMode }: { runtimeMode: AdminRuntimeMode }) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timeout = window.setTimeout(() => setQuery(input.trim()), 250);
    return () => window.clearTimeout(timeout);
  }, [input]);
  const results = useQuery({
    enabled: runtimeMode === "authenticated" && query.length >= 2,
    queryKey: ["admin", "dashboard", "search", query],
    queryFn: ({ signal }) => searchAdminResources(query, signal),
    staleTime: 10_000,
  });
  const open = input.trim().length >= 2;
  return (
    <div className="global-admin-search">
      <Input
        allowClear
        aria-label="全局 ID 搜索"
        onChange={(event) => setInput(event.target.value)}
        placeholder="搜索 Run / Session / 玩家 / 任务"
        prefix={<SearchOutlined />}
        value={input}
      />
      {open ? (
        <Card className="global-admin-search-results" role="status" size="small">
          {runtimeMode === "preview" ? (
            <Typography.Text type="secondary">预览模式不连接全局搜索。</Typography.Text>
          ) : results.isFetching ? (
            <Spin description="正在搜索..." size="small" />
          ) : results.isError ? (
            <Typography.Text type="danger">搜索暂时不可用。</Typography.Text>
          ) : results.data?.items.length === 0 ? (
            <Typography.Text type="secondary">没有匹配结果。</Typography.Text>
          ) : (
            <div className="admin-search-result-list">
              {(results.data?.items ?? []).map((item) => (
                <Link
                  aria-label={item.label}
                  key={`${item.type}:${item.id}`}
                  onClick={() => setInput("")}
                  to={item.href}
                >
                  <span>{TYPE_LABELS[item.type]}</span>
                  <strong>{item.label}</strong>
                  <small>{item.description} · {item.status}</small>
                </Link>
              ))}
            </div>
          )}
        </Card>
      ) : null}
    </div>
  );
}
