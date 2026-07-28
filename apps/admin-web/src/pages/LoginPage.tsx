import { useQuery } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import AntApp from "antd/es/app";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Divider from "antd/es/divider";
import Flex from "antd/es/flex";
import Spin from "antd/es/spin";
import Typography from "antd/es/typography";
import { type FormEvent, useEffect } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { getAdminLoginOptions } from "@/features/auth/auth-api";
import { isAdminDevLoginEnabled } from "@/features/auth/runtime-config";
import { useAdminSession } from "@/features/auth/session-context";
import { adminOperationErrorDescription } from "@/lib/admin-notification";

export default function LoginPage() {
  const { notification } = AntApp.useApp();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const {
    clearError,
    loginWithDevSession,
    pendingAction,
    status,
    unauthenticatedReason,
  } = useAdminSession();
  const devLoginEnabled = isAdminDevLoginEnabled();
  const returnTo = safeReturnTo(searchParams.get("returnTo"));
  const oidcError = searchParams.get("oidcError");
  const loginOptions = useQuery({
    enabled: !devLoginEnabled,
    queryFn: getAdminLoginOptions,
    queryKey: ["admin", "login-options"],
    retry: false,
    staleTime: 60_000,
  });
  const oidcStartPath = loginOptions.data?.oidc_enabled
    ? loginOptions.data.oidc_start_path
    : null;

  useEffect(() => {
    if (unauthenticatedReason === "signed-out") {
      notification.success({
        key: "admin-signed-out",
        title: "已安全退出后台",
      });
    }
  }, [notification, unauthenticatedReason]);

  useEffect(() => {
    if (oidcError) {
      notification.error({
        description: oidcErrorMessage(oidcError),
        key: "admin-oidc-login-error",
        title: "企业账号登录失败",
      });
    }
  }, [notification, oidcError]);

  if (status === "loading") {
    return (
      <main className="auth-page">
        <Flex align="center" aria-live="polite" gap={12} role="status">
          <Spin size="small" />
          <Typography.Text>正在检查现有后台会话...</Typography.Text>
        </Flex>
      </main>
    );
  }

  if (status === "authenticated") {
    return <Navigate replace to={returnTo} />;
  }

  async function handleDevLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearError();
    try {
      await loginWithDevSession();
      notification.success({ title: "登录成功" });
      navigate(returnTo, { replace: true });
    } catch (error) {
      notification.error({
        description: adminOperationErrorDescription(
          error,
          "登录失败，请重新尝试。",
        ),
        title: "登录失败",
      });
    }
  }

  return (
    <main className="auth-page ant-auth-page">
      <Card className="ant-auth-card">
        <Flex align="center" className="ant-auth-brand-row" gap={12}>
          <span className="auth-brand" aria-hidden="true">WA</span>
          <span>
            <Typography.Text className="auth-kicker">WEREWOLF ARENA</Typography.Text>
            <Typography.Text type="secondary">运营与诊断后台</Typography.Text>
          </span>
        </Flex>
        <Typography.Title id="admin-login-title" level={1}>登录管理后台</Typography.Title>
        <Typography.Paragraph type="secondary">
          后台仅面向获得授权的运营与技术人员，不支持公开注册。
        </Typography.Paragraph>

        <Flex gap={12} vertical>
          {unauthenticatedReason === "expired" ? (
            <Alert role="status" showIcon title="会话已过期。请重新登录后继续。" type="warning" />
          ) : null}
          {oidcStartPath ? (
            <Button
              block
              href={`${oidcStartPath}?return_to=${encodeURIComponent(returnTo)}`}
              size="large"
              type="primary"
            >
              使用企业账号登录
            </Button>
          ) : null}

          {devLoginEnabled ? (
            <form className="auth-form" onSubmit={handleDevLogin}>
              <Card size="small">
                <Flex gap={3} vertical>
                  <Typography.Text strong>本地开发身份</Typography.Text>
                  <Typography.Text type="secondary">
                    账号与角色由 API 服务端环境变量决定。
                  </Typography.Text>
                </Flex>
              </Card>
              <Button
                block
                htmlType="submit"
                loading={pendingAction === "login"}
                size="large"
                type="primary"
              >
                使用开发身份登录
              </Button>
            </form>
          ) : !oidcStartPath && !loginOptions.isPending ? (
            <Alert
              role="note"
              showIcon
              title="当前环境未提供登录入口。请通过已配置的企业身份入口访问，或联系系统管理员。"
              type="info"
            />
          ) : null}

        </Flex>

        <Divider />
        <Typography.Text type="secondary">
          会话凭据仅保存在安全的 HttpOnly Cookie 中，不会写入浏览器本地存储。
        </Typography.Text>
      </Card>
    </main>
  );
}

function safeReturnTo(value: string | null) {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/content/players";
  }
  if (value.startsWith("/login") || value.startsWith("/403")) {
    return "/content/players";
  }
  return value;
}

function oidcErrorMessage(code: string) {
  if (code === "admin_oidc_account_not_provisioned") {
    return "该企业账号尚未获得后台权限，请联系系统管理员。";
  }
  if (code === "admin_oidc_account_disabled") {
    return "该后台账号已停用，请联系系统管理员。";
  }
  if (code === "admin_oidc_provider_denied") {
    return "企业身份提供商未完成授权，请重新尝试。";
  }
  return "登录事务无效或身份验证失败，请重新尝试。";
}
