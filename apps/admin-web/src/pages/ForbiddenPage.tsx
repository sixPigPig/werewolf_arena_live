import AntApp from "antd/es/app";
import Button from "antd/es/button";
import Result from "antd/es/result";
import Space from "antd/es/space";
import { useNavigate } from "react-router-dom";

import { useAdminSession } from "@/features/auth/session-context";
import { adminOperationErrorDescription } from "@/lib/admin-notification";

export default function ForbiddenPage() {
  const { notification } = AntApp.useApp();
  const navigate = useNavigate();
  const { error, logout, pendingAction, session } = useAdminSession();

  async function handleLogout() {
    try {
      await logout();
    } catch (logoutError) {
      notification.error({
        description: adminOperationErrorDescription(
          logoutError,
          "退出失败，请稍后重试。",
        ),
        title: "退出失败",
      });
    }
  }

  return (
    <main className="auth-page ant-auth-page">
      <Result
        extra={
          <Space wrap>
            <Button onClick={() => navigate("/content/players")} type="primary">返回玩家管理</Button>
            {session ? (
              <Button
                loading={pendingAction === "logout"}
                onClick={() => void handleLogout()}
              >
                退出当前账号
              </Button>
            ) : (
              <Button onClick={() => navigate("/login")}>返回登录</Button>
            )}
          </Space>
        }
        status="403"
        subTitle={
          <Space orientation="vertical" size={8}>
            <span>当前后台身份无权访问这个页面。如果工作职责已变更，请联系超级管理员调整权限。</span>
            {error?.requestId ? <small>请求编号：{error.requestId}</small> : null}
          </Space>
        }
        title={<h1 id="forbidden-title">没有访问权限</h1>}
      />
    </main>
  );
}
