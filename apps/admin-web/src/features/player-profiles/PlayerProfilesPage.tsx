import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Button from "antd/es/button";
import Input from "antd/es/input";
import Select from "antd/es/select";
import { type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import {
  playerProfileListParamsFromSearch,
  setPlayerProfileSearchValues,
} from "@/features/player-profiles/list-state";
import { playerProfileKeys } from "@/features/player-profiles/query-keys";
import { usePlayerProfileRepository } from "@/features/player-profiles/repository";
import type {
  AdminPlayerProfile,
  PlayerProfileStatus,
  PlayerTtsSpeakerOption,
} from "@/features/player-profiles/types";

const STATUS_LABELS: Record<PlayerProfileStatus, string> = {
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
};

export default function PlayerProfilesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = playerProfileListParamsFromSearch(searchParams);
  const repository = usePlayerProfileRepository();
  const { session } = useAdminSession();
  const permissions = session?.permissions ?? [];
  const canWrite = hasAdminPermission(permissions, "players.write");
  const canPublish = hasAdminPermission(permissions, "players.publish");
  const optionsQuery = useQuery({
    queryKey: playerProfileKeys.options(),
    queryFn: ({ signal }) => repository.getOptions(signal),
    staleTime: 5 * 60_000,
  });
  const profilesQuery = useQuery({
    queryKey: playerProfileKeys.list(params),
    queryFn: ({ signal }) => repository.list(params, signal),
    placeholderData: keepPreviousData,
  });
  const ttsSpeakersQuery = useQuery({
    queryKey: playerProfileKeys.ttsSpeakers(),
    queryFn: ({ signal }) => repository.getTtsSpeakers(signal),
    staleTime: 60 * 60_000,
  });
  const data = profilesQuery.data;

  function updateSearch(values: Record<string, string | undefined>) {
    setSearchParams(
      setPlayerProfileSearchValues(searchParams, { page: "1", ...values }),
    );
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = new FormData(event.currentTarget).get("q");
    updateSearch({ q: typeof value === "string" ? value : undefined });
  }

  function clearFilters() {
    setSearchParams(
      setPlayerProfileSearchValues(searchParams, {
        page: undefined,
        q: undefined,
        status: undefined,
        model: undefined,
        personality_id: undefined,
      }),
    );
  }

  const hasFilters = Boolean(
    params.q || params.status || params.model || params.personality_id,
  );

  return (
    <div className="admin-page player-profiles-page">
      <header className="page-heading player-profiles-heading">
        <div>
          <span className="page-kicker">CONTENT</span>
          <h1>虚拟玩家</h1>
          <p>管理 C 端可用玩家的人设、模型与发布生命周期。</p>
        </div>
        {canWrite ? (
          <Link className="admin-primary-link" to="/content/players/new">
            新建玩家草稿
          </Link>
        ) : (
          <span className="page-readiness-badge">只读权限</span>
        )}
      </header>

      <section aria-label="玩家筛选" className="player-filter-panel">
        <form className="player-search-form" onSubmit={handleSearch} role="search">
          <label>
            <span>搜索玩家</span>
            <Input
              aria-label="搜索玩家"
              defaultValue={params.q ?? ""}
              key={params.q ?? "empty-search"}
              name="q"
              placeholder="名称或简介"
              type="search"
            />
          </label>
          <Button htmlType="submit">
            搜索
          </Button>
        </form>
        <div className="player-filter-grid">
          <label>
            <span>生命周期</span>
            <Select
              aria-label="生命周期"
              onChange={(value) => updateSearch({ status: value })}
              options={[
                { label: "全部状态", value: "" },
                { label: "草稿", value: "draft" },
                { label: "已发布", value: "published" },
                { label: "已归档", value: "archived" },
              ]}
              value={params.status ?? ""}
            />
          </label>
          <label>
            <span>模型</span>
            <Select
              aria-label="模型"
              disabled={optionsQuery.isPending || optionsQuery.isError}
              onChange={(value) => updateSearch({ model: value })}
              options={[
                { label: "全部模型", value: "" },
                ...(optionsQuery.data?.models.map((option) => ({
                  label: option.label,
                  value: option.model_id,
                })) ?? []),
              ]}
              value={params.model ?? ""}
            />
          </label>
          <label>
            <span>性格</span>
            <Select
              aria-label="性格"
              disabled={optionsQuery.isPending || optionsQuery.isError}
              onChange={(value) => updateSearch({ personality_id: value })}
              options={[
                { label: "全部性格", value: "" },
                ...(optionsQuery.data?.personalities.map((option) => ({
                  label: option.label,
                  value: option.id,
                })) ?? []),
              ]}
              value={params.personality_id ?? ""}
            />
          </label>
          <label>
            <span>排序</span>
            <Select
              aria-label="排序"
              onChange={(value) => {
                const [sort, direction] = value.split(":");
                updateSearch({ sort, direction });
              }}
              options={[
                { label: "最近更新", value: "updated_at:desc" },
                { label: "最近创建", value: "created_at:desc" },
                { label: "名称 A–Z", value: "display_name:asc" },
                { label: "C 端顺序", value: "display_order:asc" },
              ]}
              value={`${params.sort}:${params.direction}`}
            />
          </label>
          <label>
            <span>每页</span>
            <Select
              aria-label="每页"
              onChange={(value) => updateSearch({ page_size: value })}
              options={[
                { label: "10 条", value: "10" },
                { label: "20 条", value: "20" },
                { label: "50 条", value: "50" },
              ]}
              value={String(params.page_size)}
            />
          </label>
          {hasFilters ? (
            <Button
              className="player-clear-filter"
              htmlType="button"
              onClick={clearFilters}
              type="text"
            >
              清除筛选
            </Button>
          ) : null}
        </div>
      </section>

      {optionsQuery.isError ? (
        <p className="player-inline-warning" role="status">
          筛选选项暂时不可用，玩家列表仍可浏览。
        </p>
      ) : null}

      <section aria-labelledby="player-list-title" className="player-list-panel">
        <div className="player-list-heading">
          <div>
            <span>PLAYER LIBRARY</span>
            <h2 id="player-list-title">玩家内容库</h2>
          </div>
          <p aria-live="polite">
            {data ? `共 ${data.pagination.total} 个玩家` : "正在统计..."}
          </p>
        </div>

        {profilesQuery.isPending ? <PlayerListLoading /> : null}
        {profilesQuery.isError ? (
          <PlayerListError error={profilesQuery.error} onRetry={profilesQuery.refetch} />
        ) : null}
        {data && data.items.length === 0 ? (
          <div className="player-empty-state">
            <span aria-hidden="true">人</span>
            <h3>{hasFilters ? "没有符合条件的玩家" : "还没有玩家内容"}</h3>
            <p>
              {hasFilters
                ? "调整或清除筛选条件后重试。"
                : canWrite
                  ? "创建第一份草稿，审核后再发布到 C 端。"
                  : "当前还没有可浏览的玩家内容。"}
            </p>
          </div>
        ) : null}
        {data && data.items.length > 0 ? (
          <ul aria-label="虚拟玩家列表" className="player-admin-list">
            {data.items.map((profile) => (
              <PlayerListItem
                canPublish={canPublish}
                canWrite={canWrite}
                key={profile.id}
                profile={profile}
                ttsSpeakerOptions={ttsSpeakersQuery.data?.items ?? []}
              />
            ))}
          </ul>
        ) : null}

        {data && data.pagination.total > 0 ? (
          <PlayerPagination
            page={data.pagination.page}
            pages={data.pagination.pages}
            setPage={(page) =>
              setSearchParams(
                setPlayerProfileSearchValues(searchParams, {
                  page: String(page),
                }),
              )
            }
          />
        ) : null}
      </section>
    </div>
  );
}

function PlayerListItem({
  canPublish,
  canWrite,
  profile,
  ttsSpeakerOptions,
}: {
  canPublish: boolean;
  canWrite: boolean;
  profile: AdminPlayerProfile;
  ttsSpeakerOptions: PlayerTtsSpeakerOption[];
}) {
  const canEdit =
    profile.status !== "archived" &&
    canWrite &&
    (profile.status !== "published" || canPublish);
  const voiceLabel = playerVoiceLabel(profile, ttsSpeakerOptions);
  return (
    <li className="player-admin-row">
      <div className="player-admin-identity">
        <span className="player-admin-avatar">
          {profile.avatar_image_url ? (
            <img alt="" src={profile.avatar_image_url} />
          ) : (
            <span aria-hidden="true">{profile.display_name.charAt(0)}</span>
          )}
        </span>
        <span>
          <strong>{profile.display_name}</strong>
          <small title={profile.id}>{profile.id}</small>
        </span>
      </div>
      <div className="player-admin-status-cell">
        <span className={`player-status-badge is-${profile.status}`}>
          {STATUS_LABELS[profile.status]}
        </span>
        {profile.featured ? <span className="player-featured-badge">推荐</span> : null}
      </div>
      <div className="player-admin-model-cell">
        <strong>{profile.model}</strong>
        <small>{profile.personality_id} · {profile.strategy_profile}</small>
        <small title={profile.tts_speaker ?? "继承全局玩家音色"}>
          音色：{voiceLabel}
        </small>
      </div>
      <div className="player-admin-tags-cell">
        {profile.tags.slice(0, 2).map((tag) => (
          <span key={tag}>{tag}</span>
        ))}
        {profile.tags.length === 0 ? <small>无标签</small> : null}
      </div>
      <div className="player-admin-updated-cell">
        <strong>{formatDateTime(profile.updated_at)}</strong>
        <small>版本 {profile.version} · 操作人 {profile.updated_by ?? "系统"}</small>
      </div>
      <div className="player-admin-action-cell">
        <Link
          aria-label={`${canEdit ? "编辑" : "查看"} ${profile.display_name}`}
          className="admin-secondary-link"
          to={`/content/players/${encodeURIComponent(profile.id)}`}
        >
          {canEdit ? "编辑" : "查看"}
        </Link>
      </div>
    </li>
  );
}

function playerVoiceLabel(
  profile: AdminPlayerProfile,
  options: PlayerTtsSpeakerOption[],
) {
  const disabled = profile.voice_enabled === false ? "已关闭 · " : "";
  if (!profile.tts_speaker) {
    return `${disabled}继承全局`;
  }
  const speaker = options.find(
    (option) => option.voice_type === profile.tts_speaker,
  );
  if (!speaker) {
    return `${disabled}${profile.tts_speaker}`;
  }
  const dialect = speaker.dialects.find(
    (option) => option.id === profile.tts_dialect,
  );
  return `${disabled}${speaker.name}${dialect ? ` · ${dialect.label}` : ""}`;
}

function PlayerPagination({
  page,
  pages,
  setPage,
}: {
  page: number;
  pages: number;
  setPage: (page: number) => void;
}) {
  return (
    <nav aria-label="玩家列表分页" className="player-pagination">
      <button
        disabled={page <= 1}
        onClick={() => setPage(page - 1)}
        type="button"
      >
        上一页
      </button>
      <span aria-current="page">第 {page} / {Math.max(1, pages)} 页</span>
      <button
        disabled={pages === 0 || page >= pages}
        onClick={() => setPage(page + 1)}
        type="button"
      >
        下一页
      </button>
    </nav>
  );
}

function PlayerListLoading() {
  return (
    <div aria-live="polite" className="player-list-loading" role="status">
      <span />
      <span />
      <span />
      <p>正在读取玩家内容...</p>
    </div>
  );
}

function PlayerListError({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => unknown;
}) {
  return (
    <div aria-live="assertive" className="player-list-error" role="alert">
      <h3>无法读取玩家内容</h3>
      <p>{error.message}</p>
      {isAdminApiError(error) && error.requestId ? (
        <small>请求编号：{error.requestId}</small>
      ) : null}
      <button onClick={() => void onRetry()} type="button">
        重新加载
      </button>
    </div>
  );
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
