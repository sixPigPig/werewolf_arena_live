import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import AntApp from "antd/es/app";
import Avatar from "antd/es/avatar";
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
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { AdminEmpty, AdminError } from "@/components/admin/AdminPage";
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
import { adminOperationErrorDescription } from "@/lib/admin-notification";

const STATUS_LABELS: Record<PlayerProfileStatus, string> = {
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
};

const STATUS_COLORS: Record<PlayerProfileStatus, string> = {
  draft: "warning",
  published: "success",
  archived: "default",
};

export default function PlayerProfilesPage() {
  const { notification } = AntApp.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const params = playerProfileListParamsFromSearch(searchParams);
  const repository = usePlayerProfileRepository();
  const queryClient = useQueryClient();
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
  const moveProfileMutation = useMutation({
    mutationFn: ({
      direction,
      profile,
    }: {
      direction: "up" | "down";
      profile: AdminPlayerProfile;
    }) =>
      repository.move(profile.id, {
        direction,
        expected_version: profile.version,
      }),
    onError: (error) => {
      notification.error({
        description: adminOperationErrorDescription(
          error,
          "玩家顺序调整失败，请刷新后重试。",
        ),
        title: "玩家顺序调整失败",
      });
    },
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({
        queryKey: playerProfileKeys.lists(),
      });
      notification.success({
        title: `${variables.profile.display_name} 已${variables.direction === "up" ? "上移" : "下移"}`,
      });
    },
  });

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
  const showMoveControls =
    params.sort === "display_order" && params.direction === "asc";
  const columns: ColumnsType<AdminPlayerProfile> = [
    {
      key: "identity",
      render: (_, profile) => (
        <Flex align="center" gap={12}>
          <Avatar
            shape="square"
            size={48}
            src={profile.avatar_image_url || undefined}
          >
            {profile.display_name.charAt(0)}
          </Avatar>
          <Flex gap={2} vertical>
            <Typography.Text strong>{profile.display_name}</Typography.Text>
            <Typography.Text title={profile.id} type="secondary">
              {profile.id}
            </Typography.Text>
          </Flex>
        </Flex>
      ),
      title: "玩家",
      width: 250,
    },
    {
      key: "status",
      render: (_, profile) => (
        <Flex gap={4} vertical>
          <Flex gap={4} wrap>
            <Tag color={STATUS_COLORS[profile.status]}>
              {STATUS_LABELS[profile.status]}
            </Tag>
            {profile.featured ? <Tag color="blue">推荐</Tag> : null}
          </Flex>
          <Typography.Text type="secondary">
            {profile.display_order === null
              ? "未进入 C 端顺序"
              : `C 端 #${profile.display_order}`}
          </Typography.Text>
        </Flex>
      ),
      title: "状态 / C 端",
      width: 160,
    },
    {
      key: "model",
      render: (_, profile) => (
        <Flex gap={2} vertical>
          <Typography.Text strong>{profile.model}</Typography.Text>
          <Typography.Text type="secondary">
            {profile.personality_id} · {profile.strategy_profile}
          </Typography.Text>
          <Typography.Text
            title={profile.tts_speaker ?? "继承全局玩家音色"}
            type="secondary"
          >
            音色：{playerVoiceLabel(profile, ttsSpeakersQuery.data?.items ?? [])}
          </Typography.Text>
        </Flex>
      ),
      title: "模型 / 音色",
      width: 240,
    },
    {
      key: "tags",
      render: (_, profile) =>
        profile.tags.length > 0 ? (
          <Flex gap={4} wrap>
            {profile.tags.slice(0, 2).map((tag) => (
              <Tag key={tag}>{tag}</Tag>
            ))}
          </Flex>
        ) : (
          <Typography.Text type="secondary">无标签</Typography.Text>
        ),
      title: "标签",
      width: 150,
    },
    {
      key: "updated",
      render: (_, profile) => (
        <Flex gap={2} vertical>
          <Typography.Text>{formatDateTime(profile.updated_at)}</Typography.Text>
          <Typography.Text type="secondary">
            版本 {profile.version} · 操作人 {profile.updated_by ?? "系统"}
          </Typography.Text>
        </Flex>
      ),
      title: "更新时间",
      width: 210,
    },
    {
      key: "action",
      render: (_, profile) => {
        const canEdit =
          profile.status !== "archived" &&
          canWrite &&
          (profile.status !== "published" || canPublish);
        const movePending =
          moveProfileMutation.isPending &&
          moveProfileMutation.variables.profile.id === profile.id;
        return (
          <Flex align="center" gap={4}>
            {canPublish &&
            profile.status === "published" &&
            showMoveControls ? (
              <>
                <Button
                  aria-label={`上移 ${profile.display_name}`}
                  disabled={movePending || profile.display_order === 1}
                  onClick={() =>
                    moveProfileMutation.mutate({ direction: "up", profile })
                  }
                  size="small"
                  type="text"
                >
                  上移
                </Button>
                <Button
                  aria-label={`下移 ${profile.display_name}`}
                  disabled={movePending}
                  onClick={() =>
                    moveProfileMutation.mutate({ direction: "down", profile })
                  }
                  size="small"
                  type="text"
                >
                  下移
                </Button>
              </>
            ) : null}
            <Button
              aria-label={`${canEdit ? "编辑" : "查看"} ${profile.display_name}`}
              onClick={() =>
                navigate(
                  `/content/players/${encodeURIComponent(profile.id)}`,
                )
              }
              size="small"
            >
              {canEdit ? "编辑" : "查看"}
            </Button>
          </Flex>
        );
      },
      title: "操作",
      width: 190,
    },
  ];

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
                { label: "C 端顺序", value: "display_order:asc" },
                { label: "最近更新", value: "updated_at:desc" },
                { label: "最近创建", value: "created_at:desc" },
                { label: "名称 A–Z", value: "display_name:asc" },
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
      {profilesQuery.isError ? (
        <AdminError
          description={
            isAdminApiError(profilesQuery.error)
              ? profilesQuery.error.message
              : "玩家内容服务暂时不可用。"
          }
          onRetry={profilesQuery.refetch}
          requestId={
            isAdminApiError(profilesQuery.error)
              ? profilesQuery.error.requestId
              : null
          }
          title="无法读取玩家内容"
        />
      ) : (
        <Card
          extra={
            <Typography.Text aria-live="polite" type="secondary">
              {data ? `共 ${data.pagination.total} 个玩家` : "正在统计..."}
            </Typography.Text>
          }
          styles={{ body: { padding: 0 } }}
          title={<h2 id="player-list-title">玩家内容库</h2>}
        >
          <div aria-label="虚拟玩家列表" role="region">
            <Table<AdminPlayerProfile>
              columns={columns}
              dataSource={data?.items ?? []}
              loading={
                profilesQuery.isPending
                  ? {
                      description: "正在读取玩家内容...",
                      spinning: true,
                    }
                  : false
              }
              locale={{
                emptyText: (
                  <AdminEmpty
                    description={
                      hasFilters
                        ? "没有符合条件的玩家；调整或清除筛选条件后重试。"
                        : canWrite
                          ? "还没有玩家内容；创建第一份草稿，审核后再发布到 C 端。"
                          : "当前还没有可浏览的玩家内容。"
                    }
                  />
                ),
              }}
              pagination={false}
              rowKey="id"
              scroll={{ x: 1200 }}
            />
          </div>
        </Card>
      )}

      {data && data.pagination.total > 0 ? (
        <Flex justify="flex-end">
          <Pagination
            current={data.pagination.page}
            onChange={(page) =>
              setSearchParams(
                setPlayerProfileSearchValues(searchParams, {
                  page: String(page),
                }),
              )
            }
            pageSize={data.pagination.page_size}
            showSizeChanger={false}
            total={data.pagination.total}
          />
        </Flex>
      ) : null}
    </div>
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

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
