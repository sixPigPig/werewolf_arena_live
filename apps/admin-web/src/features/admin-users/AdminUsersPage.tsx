import PlusOutlined from "@ant-design/icons/es/icons/PlusOutlined";
import ReloadOutlined from "@ant-design/icons/es/icons/ReloadOutlined";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Checkbox from "antd/es/checkbox";
import Flex from "antd/es/flex";
import Input from "antd/es/input";
import Modal from "antd/es/modal";
import Pagination from "antd/es/pagination";
import Select from "antd/es/select";
import Table, { type ColumnsType } from "antd/es/table";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import {
  AdminEmpty,
  AdminError,
  AdminPage,
  AdminPageHeader,
} from "@/components/admin/AdminPage";
import {
  createAdminUser,
  listAdminUsers,
  revokeAdminUserSessions,
  updateAdminUser,
} from "@/features/admin-users/api";
import { adminUserKeys } from "@/features/admin-users/query-keys";
import type { AdminUserItem, AdminUserListParams } from "@/features/admin-users/types";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import type { AdminRole } from "@/features/auth/types";

const roleLabels: Record<AdminRole, string> = {
  content_editor: "内容编辑",
  operator: "运行运营",
  super_admin: "超级管理员",
  viewer: "只读观察员",
};

type DialogState = { mode: "create" } | { mode: "edit"; user: AdminUserItem };

export default function AdminUsersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { session } = useAdminSession();
  const params = paramsFromSearch(searchParams);
  const canManageRoles = hasAdminPermission(session?.permissions ?? [], "roles.manage");
  const users = useQuery({
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => listAdminUsers(params, signal),
    queryKey: adminUserKeys.list(params),
  });
  const save = useMutation({
    mutationFn: async (input: {
      mode: "create" | "edit";
      user?: AdminUserItem;
      email: string;
      displayName: string;
      role: AdminRole;
      isActive: boolean;
      reason: string;
    }) =>
      input.mode === "create"
        ? createAdminUser(
            {
              display_name: input.displayName,
              email: input.email,
              reason: input.reason,
              role: input.role,
            },
            session?.csrf_token ?? "",
          )
        : updateAdminUser(
            input.user!.id,
            {
              display_name: input.displayName,
              expected_version: input.user!.version,
              is_active: input.isActive,
              reason: input.reason,
              role: input.role,
            },
            session?.csrf_token ?? "",
          ),
    onError: (error) => {
      if (isAdminApiError(error) && error.code === "admin_user_version_conflict") {
        setNotice("账号已被其他管理员更新，列表已刷新，请重新打开后操作。");
        setDialog(null);
        void queryClient.invalidateQueries({ queryKey: adminUserKeys.all });
      }
    },
    onSuccess: (user, input) => {
      setDialog(null);
      setNotice(input.mode === "create" ? `已开通 ${user.email}` : `已更新 ${user.email}`);
      void queryClient.invalidateQueries({ queryKey: adminUserKeys.all });
    },
  });
  const revoke = useMutation({
    mutationFn: ({ user, reason }: { user: AdminUserItem; reason: string }) =>
      revokeAdminUserSessions(user.id, reason, session?.csrf_token ?? ""),
    onSuccess: (result) => {
      setNotice(`已撤销 ${result.revoked_count} 个会话`);
      setDialog(null);
      void queryClient.invalidateQueries({ queryKey: adminUserKeys.all });
    },
  });

  function updateSearch(values: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries({ page: "1", ...values })) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setSearchParams(next);
  }

  const columns: ColumnsType<AdminUserItem> = [
    {
      key: "identity",
      render: (_, user) => (
        <Flex gap={2} vertical>
          <Typography.Text strong>{user.display_name}</Typography.Text>
          <Typography.Text type="secondary">{user.email}</Typography.Text>
        </Flex>
      ),
      title: "账号",
    },
    {
      dataIndex: "role",
      key: "role",
      render: (role: AdminRole) => <Tag color="blue">{roleLabels[role]}</Tag>,
      title: "角色",
    },
    {
      dataIndex: "is_active",
      key: "is_active",
      render: (active: boolean) => (
        <Tag color={active ? "success" : "default"}>{active ? "已启用" : "已停用"}</Tag>
      ),
      title: "状态",
    },
    {
      key: "binding",
      render: (_, user) => (
        <Flex gap={2} vertical>
          <span>{user.identity_status === "bound" ? "已绑定 OIDC" : "等待首次登录"}</span>
          <Typography.Text type="secondary">版本 {user.version}</Typography.Text>
        </Flex>
      ),
      title: "身份绑定",
    },
    {
      key: "sessions",
      render: (_, user) => (
        <Flex gap={2} vertical>
          <span>{user.active_session_count} 个活动会话</span>
          <Typography.Text type="secondary">
            {user.last_session_at ? `最近登录 ${formatDate(user.last_session_at)}` : "尚未登录"}
          </Typography.Text>
        </Flex>
      ),
      title: "会话",
    },
    {
      key: "action",
      render: (_, user) => (
        <Button onClick={() => setDialog({ mode: "edit", user })} size="small">
          管理 {user.display_name}
        </Button>
      ),
      title: "操作",
    },
  ];

  return (
    <AdminPage className="system-page">
      <AdminPageHeader
        description="开通 OIDC 预授权账号、调整固定角色并强制撤销后台会话。"
        extra={
          <>
            <Button aria-label="手动刷新" icon={<ReloadOutlined aria-hidden="true" />} loading={users.isFetching} onClick={() => void users.refetch()}>
              手动刷新
            </Button>
            {canManageRoles ? (
              <Button aria-label="开通账号" icon={<PlusOutlined aria-hidden="true" />} onClick={() => setDialog({ mode: "create" })} type="primary">
                开通账号
              </Button>
            ) : null}
          </>
        }
        kicker="ACCESS CONTROL"
        title="后台账号"
      />

      {notice ? <Alert closable onClose={() => setNotice(null)} role="status" showIcon title={notice} type="success" /> : null}
      <Card title="筛选条件">
        <form
          className="ant-admin-filter-grid"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            updateSearch({ q: String(data.get("q") ?? "").trim() || undefined });
          }}
          role="search"
        >
          <label className="ant-filter-wide">
            <span>搜索账号</span>
            <Input defaultValue={params.q ?? ""} name="q" placeholder="姓名或邮箱" type="search" />
          </label>
          <label>
            <span>角色</span>
            <Select
              aria-label="账号角色"
              onChange={(value) => updateSearch({ role: value || undefined })}
              options={[
                { label: "全部角色", value: "" },
                ...Object.entries(roleLabels).map(([value, label]) => ({ label, value })),
              ]}
              value={params.role ?? ""}
            />
          </label>
          <label>
            <span>状态</span>
            <Select
              aria-label="账号状态"
              onChange={(value) => updateSearch({ is_active: value || undefined })}
              options={[
                { label: "全部状态", value: "" },
                { label: "已启用", value: "true" },
                { label: "已停用", value: "false" },
              ]}
              value={params.is_active ?? ""}
            />
          </label>
          <label>
            <span>身份绑定</span>
            <Select
              aria-label="身份绑定"
              onChange={(value) => updateSearch({ identity_status: value || undefined })}
              options={[
                { label: "全部", value: "" },
                { label: "已绑定 OIDC", value: "bound" },
                { label: "等待首次登录", value: "unbound" },
              ]}
              value={params.identity_status ?? ""}
            />
          </label>
          <Flex align="flex-end" gap={8}>
            <Button onClick={() => setSearchParams({})}>清除筛选</Button>
            <Button htmlType="submit" type="primary">应用筛选</Button>
          </Flex>
        </form>
      </Card>

      {users.isError ? (
        <AdminError
          description={isAdminApiError(users.error) ? users.error.message : "账号服务暂时不可用。"}
          onRetry={users.refetch}
          requestId={isAdminApiError(users.error) ? users.error.requestId : null}
          title="无法读取后台账号"
        />
      ) : (
        <Card
          extra={<Typography.Text type="secondary">共 {users.data?.pagination.total ?? 0} 个后台账号</Typography.Text>}
          styles={{ body: { padding: 0 } }}
          title={<h2>账号与会话</h2>}
        >
          <Table<AdminUserItem>
            columns={columns}
            dataSource={users.data?.items ?? []}
            loading={users.isPending}
            locale={{ emptyText: <AdminEmpty description="没有符合条件的账号；调整筛选条件，或开通新的预授权账号。" /> }}
            pagination={false}
            rowKey="id"
            scroll={{ x: 980 }}
          />
        </Card>
      )}
      {users.data ? (
        <Flex justify="flex-end">
          <Pagination
            current={users.data.pagination.page}
            onChange={(page) => updateSearch({ page: String(page) })}
            pageSize={users.data.pagination.page_size}
            showSizeChanger={false}
            total={users.data.pagination.total}
          />
        </Flex>
      ) : null}

      {dialog ? (
        <AccountDialog
          canManageRoles={canManageRoles}
          currentUserId={session?.user.id ?? ""}
          error={save.error ?? revoke.error}
          key={dialog.mode === "create" ? "create" : dialog.user.id}
          onClose={() => setDialog(null)}
          onRevoke={(user, reason) => revoke.mutate({ reason, user })}
          onSave={(input) => save.mutate(input)}
          pending={save.isPending || revoke.isPending}
          state={dialog}
        />
      ) : null}
    </AdminPage>
  );
}

function AccountDialog({
  canManageRoles,
  currentUserId,
  error,
  onClose,
  onRevoke,
  onSave,
  pending,
  state,
}: {
  state: DialogState;
  currentUserId: string;
  canManageRoles: boolean;
  pending: boolean;
  error: unknown;
  onClose: () => void;
  onSave: (input: { mode: "create" | "edit"; user?: AdminUserItem; email: string; displayName: string; role: AdminRole; isActive: boolean; reason: string }) => void;
  onRevoke: (user: AdminUserItem, reason: string) => void;
}) {
  const user = state.mode === "edit" ? state.user : null;
  const [reason, setReason] = useState("");
  const [role, setRole] = useState<AdminRole>(user?.role ?? "viewer");
  const isSelf = user?.id === currentUserId;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    onSave({
      displayName: String(data.get("display_name") ?? ""),
      email: String(data.get("email") ?? ""),
      isActive: user && isSelf ? user.is_active : data.get("is_active") === "on",
      mode: state.mode,
      reason,
      role: user && (!canManageRoles || isSelf) ? user.role : role,
      user: user ?? undefined,
    });
  }

  return (
    <Modal
      footer={null}
      mask={{ closable: !pending }}
      onCancel={onClose}
      open
      title={<h2 id="account-dialog-title">{user ? `管理 ${user.display_name}` : "开通后台账号"}</h2>}
    >
      <Typography.Paragraph type="secondary">
        {user
          ? "修改固定角色或账号状态。OIDC 身份绑定不会在此页面显示或重置。"
          : "账号首次使用验证邮箱登录后会绑定 OIDC issuer/sub。"}
      </Typography.Paragraph>
      <form className="ant-account-form" onSubmit={submit}>
        <label>
          <span>邮箱</span>
          <Input defaultValue={user?.email ?? ""} disabled={Boolean(user)} name="email" required type="email" />
        </label>
        <label>
          <span>显示名称</span>
          <Input defaultValue={user?.display_name ?? ""} maxLength={120} name="display_name" required />
        </label>
        <label>
          <span>固定角色</span>
          <Select
            aria-label="固定角色"
            disabled={!canManageRoles || isSelf}
            onChange={(value) => setRole(value as AdminRole)}
            options={Object.entries(roleLabels).map(([value, label]) => ({ label, value }))}
            value={role}
          />
        </label>
        {user ? (
          <Checkbox defaultChecked={user.is_active} disabled={isSelf} name="is_active">
            账号启用
          </Checkbox>
        ) : null}
        <label>
          <span>操作原因</span>
          <Input.TextArea minLength={3} onChange={(event) => setReason(event.target.value)} required rows={3} value={reason} />
        </label>
        {isSelf ? <Typography.Text type="secondary">当前账号不能修改自身角色或停用自身。</Typography.Text> : null}
        {error ? (
          <Alert role="alert" showIcon title={isAdminApiError(error) ? error.message : "账号操作失败，请稍后重试。"} type="error" />
        ) : null}
        <Flex gap={8} justify="flex-end" wrap>
          {user && user.active_session_count > 0 ? (
            <Button danger disabled={pending || reason.trim().length < 3} onClick={() => onRevoke(user, reason)}>
              撤销全部会话
            </Button>
          ) : null}
          <Button disabled={pending} onClick={onClose}>取消</Button>
          <Button htmlType="submit" loading={pending} type="primary">
            {user ? "保存账号" : "确认开通"}
          </Button>
        </Flex>
      </form>
    </Modal>
  );
}

function paramsFromSearch(search: URLSearchParams): AdminUserListParams {
  const role = search.get("role");
  const active = search.get("is_active");
  const identity = search.get("identity_status");
  return {
    direction: "desc",
    identity_status:
      identity === "bound" || identity === "unbound" ? identity : undefined,
    is_active: active === "true" || active === "false" ? active : undefined,
    page: Math.max(1, Number(search.get("page")) || 1),
    page_size: 20,
    q: search.get("q")?.trim() || undefined,
    role: Object.hasOwn(roleLabels, role ?? "") ? (role as AdminRole) : undefined,
    sort: "updated_at",
  };
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
