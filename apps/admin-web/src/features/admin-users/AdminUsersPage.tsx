import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
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
  viewer: "只读观察员",
  content_editor: "内容编辑",
  operator: "运行运营",
  super_admin: "超级管理员",
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
    }) => input.mode === "create"
      ? createAdminUser({ email: input.email, display_name: input.displayName, role: input.role, reason: input.reason }, session?.csrf_token ?? "")
      : updateAdminUser(input.user!.id, {
          expected_version: input.user!.version,
          display_name: input.displayName,
          role: input.role,
          is_active: input.isActive,
          reason: input.reason,
        }, session?.csrf_token ?? ""),
    onSuccess: (user, input) => {
      setDialog(null);
      setNotice(input.mode === "create" ? `已开通 ${user.email}` : `已更新 ${user.email}`);
      void queryClient.invalidateQueries({ queryKey: adminUserKeys.all });
    },
    onError: (error) => {
      if (isAdminApiError(error) && error.code === "admin_user_version_conflict") {
        setNotice("账号已被其他管理员更新，列表已刷新，请重新打开后操作。");
        setDialog(null);
        void queryClient.invalidateQueries({ queryKey: adminUserKeys.all });
      }
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
      if (value) next.set(key, value); else next.delete(key);
    }
    setSearchParams(next);
  }

  return (
    <div className="admin-page system-page">
      <header className="page-heading system-heading">
        <div>
          <span className="page-kicker">ACCESS CONTROL</span>
          <h1>后台账号</h1>
          <p>开通 OIDC 预授权账号、调整固定角色并强制撤销后台会话。</p>
        </div>
        <div className="voice-assets-heading-actions">
          <button className="admin-secondary-button" onClick={() => void users.refetch()} type="button">手动刷新</button>
          {canManageRoles ? <button className="admin-primary-button" onClick={() => setDialog({ mode: "create" })} type="button">开通账号</button> : null}
        </div>
      </header>

      {notice ? <p aria-live="polite" className="system-notice" role="status">{notice}</p> : null}
      <section aria-label="后台账号筛选" className="game-filter-panel">
        <form onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          updateSearch({ q: String(data.get("q") ?? "").trim() || undefined });
        }} role="search">
          <label className="game-filter-wide"><span>搜索账号</span><input defaultValue={params.q ?? ""} name="q" placeholder="姓名或邮箱" type="search" /></label>
          <label><span>角色</span><select aria-label="账号角色" onChange={(event) => updateSearch({ role: event.target.value || undefined })} value={params.role ?? ""}><option value="">全部角色</option>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label><span>状态</span><select aria-label="账号状态" onChange={(event) => updateSearch({ is_active: event.target.value || undefined })} value={params.is_active ?? ""}><option value="">全部状态</option><option value="true">已启用</option><option value="false">已停用</option></select></label>
          <label><span>身份绑定</span><select aria-label="身份绑定" onChange={(event) => updateSearch({ identity_status: event.target.value || undefined })} value={params.identity_status ?? ""}><option value="">全部</option><option value="bound">已绑定 OIDC</option><option value="unbound">等待首次登录</option></select></label>
          <div className="game-filter-actions"><button className="admin-secondary-button" onClick={() => setSearchParams({})} type="button">清除筛选</button><button className="admin-primary-button" type="submit">应用筛选</button></div>
        </form>
      </section>

      <section aria-label="后台账号列表" className="game-list-panel">
        <div className="game-list-heading"><div><span>ADMIN ACCOUNTS</span><h2>账号与会话</h2></div><p>共 {users.data?.pagination.total ?? 0} 个后台账号</p></div>
        {users.isPending ? <div aria-live="polite" className="game-list-loading" role="status"><span /><span /><p>正在读取后台账号...</p></div> : null}
        {users.isError ? <ListError error={users.error} retry={() => void users.refetch()} /> : null}
        {users.data?.items.length === 0 ? <div className="game-empty-state"><span>账</span><h3>没有符合条件的账号</h3><p>调整筛选条件，或开通新的预授权账号。</p></div> : null}
        {users.data?.items.length ? <ul className="system-user-list">{users.data.items.map((user) => (
          <li className="system-user-row" key={user.id}>
            <div className="system-user-identity"><strong>{user.display_name}</strong><small>{user.email}</small></div>
            <span className={`system-badge role-${user.role}`}>{roleLabels[user.role]}</span>
            <span className={`system-badge ${user.is_active ? "is-active" : "is-disabled"}`}>{user.is_active ? "已启用" : "已停用"}</span>
            <div><strong>{user.identity_status === "bound" ? "已绑定 OIDC" : "等待首次登录"}</strong><small>版本 {user.version}</small></div>
            <div><strong>{user.active_session_count} 个活动会话</strong><small>{user.last_session_at ? `最近登录 ${formatDate(user.last_session_at)}` : "尚未登录"}</small></div>
            <button className="admin-secondary-button" onClick={() => setDialog({ mode: "edit", user })} type="button">管理 {user.display_name}</button>
          </li>
        ))}</ul> : null}
        {users.data ? <Pagination page={users.data.pagination.page} pages={users.data.pagination.pages} onPage={(page) => updateSearch({ page: String(page) })} /> : null}
      </section>

      {dialog ? <AccountDialog
        canManageRoles={canManageRoles}
        currentUserId={session?.user.id ?? ""}
        error={save.error ?? revoke.error}
        key={dialog.mode === "create" ? "create" : dialog.user.id}
        pending={save.isPending || revoke.isPending}
        state={dialog}
        onClose={() => setDialog(null)}
        onRevoke={(user, reason) => revoke.mutate({ user, reason })}
        onSave={(input) => save.mutate(input)}
      /> : null}
    </div>
  );
}

function AccountDialog({ state, currentUserId, canManageRoles, pending, error, onClose, onSave, onRevoke }: {
  state: DialogState; currentUserId: string; canManageRoles: boolean; pending: boolean; error: unknown;
  onClose: () => void;
  onSave: (input: { mode: "create" | "edit"; user?: AdminUserItem; email: string; displayName: string; role: AdminRole; isActive: boolean; reason: string }) => void;
  onRevoke: (user: AdminUserItem, reason: string) => void;
}) {
  const user = state.mode === "edit" ? state.user : null;
  const [reason, setReason] = useState("");
  const isSelf = user?.id === currentUserId;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    onSave({
      mode: state.mode,
      user: user ?? undefined,
      email: String(data.get("email") ?? ""),
      displayName: String(data.get("display_name") ?? ""),
      role: user && (!canManageRoles || isSelf) ? user.role : String(data.get("role")) as AdminRole,
      isActive: user && isSelf ? user.is_active : data.get("is_active") === "on",
      reason,
    });
  }
  return <div className="player-dialog-backdrop"><section aria-labelledby="account-dialog-title" aria-modal="true" className="player-transition-dialog system-account-dialog" role="dialog">
    <h2 id="account-dialog-title">{user ? `管理 ${user.display_name}` : "开通后台账号"}</h2>
    <p>{user ? "修改固定角色或账号状态。OIDC 身份绑定不会在此页面显示或重置。" : "账号首次使用验证邮箱登录后会绑定 OIDC issuer/sub。"}</p>
    <form onSubmit={submit}>
      <label><span>邮箱</span><input defaultValue={user?.email ?? ""} disabled={Boolean(user)} name="email" required type="email" /></label>
      <label><span>显示名称</span><input defaultValue={user?.display_name ?? ""} maxLength={120} name="display_name" required /></label>
      <label><span>固定角色</span><select defaultValue={user?.role ?? "viewer"} disabled={!canManageRoles || isSelf} name="role">{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {user ? <label className="system-checkbox"><input defaultChecked={user.is_active} disabled={isSelf} name="is_active" type="checkbox" /><span>账号启用</span></label> : null}
      <label><span>操作原因</span><textarea minLength={3} onChange={(event) => setReason(event.target.value)} required value={reason} /></label>
      {isSelf ? <small>当前账号不能修改自身角色或停用自身。</small> : null}
      {error ? <p aria-live="assertive" role="alert">{isAdminApiError(error) ? error.message : "账号操作失败，请稍后重试。"}</p> : null}
      <div className="player-dialog-actions">
        {user && user.active_session_count > 0 ? <button className="admin-danger-button" disabled={pending || reason.trim().length < 3} onClick={() => onRevoke(user, reason)} type="button">撤销全部会话</button> : null}
        <button className="admin-secondary-button" disabled={pending} onClick={onClose} type="button">取消</button>
        <button className="admin-primary-button" disabled={pending} type="submit">{pending ? "提交中..." : user ? "保存账号" : "确认开通"}</button>
      </div>
    </form>
  </section></div>;
}

function ListError({ error, retry }: { error: unknown; retry: () => void }) {
  return <div aria-live="assertive" className="game-list-error" role="alert"><h3>无法读取后台账号</h3><p>{isAdminApiError(error) ? error.message : "账号服务暂时不可用。"}</p>{isAdminApiError(error) && error.requestId ? <small>请求编号：{error.requestId}</small> : null}<button onClick={retry} type="button">重新加载</button></div>;
}

function Pagination({ page, pages, onPage }: { page: number; pages: number; onPage: (page: number) => void }) {
  return <nav aria-label="后台账号分页" className="game-pagination"><button disabled={page <= 1} onClick={() => onPage(page - 1)} type="button">上一页</button><span>第 {page} / {Math.max(1, pages)} 页</span><button disabled={pages === 0 || page >= pages} onClick={() => onPage(page + 1)} type="button">下一页</button></nav>;
}

function paramsFromSearch(search: URLSearchParams): AdminUserListParams {
  const role = search.get("role");
  const active = search.get("is_active");
  const identity = search.get("identity_status");
  return {
    page: Math.max(1, Number(search.get("page")) || 1),
    page_size: 20,
    q: search.get("q")?.trim() || undefined,
    role: Object.hasOwn(roleLabels, role ?? "") ? role as AdminRole : undefined,
    is_active: active === "true" || active === "false" ? active : undefined,
    identity_status: identity === "bound" || identity === "unbound" ? identity : undefined,
    sort: "updated_at",
    direction: "desc",
  };
}

function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
