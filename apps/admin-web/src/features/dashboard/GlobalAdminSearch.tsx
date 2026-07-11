import { useQuery } from "@tanstack/react-query";
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
      <label><span className="sr-only">全局 ID 搜索</span><input aria-label="全局 ID 搜索" onChange={(event) => setInput(event.target.value)} placeholder="搜索 Run / Session / 玩家 / 任务" value={input} /></label>
      {open ? <div className="global-admin-search-results" role="status">
        {runtimeMode === "preview" ? <span>预览模式不连接全局搜索。</span> : results.isFetching ? <span>正在搜索...</span> : results.isError ? <span>搜索暂时不可用。</span> : results.data?.items.length === 0 ? <span>没有匹配结果。</span> : results.data?.items.map((item) => <Link key={`${item.type}:${item.id}`} onClick={() => setInput("")} to={item.href}><span>{TYPE_LABELS[item.type]}</span><strong>{item.label}</strong><small>{item.description} · {item.status}</small></Link>)}
      </div> : null}
    </div>
  );
}
