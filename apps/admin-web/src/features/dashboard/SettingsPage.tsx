import Card from "antd/es/card";
import Descriptions, { type DescriptionsItemType } from "antd/es/descriptions";
import Col from "antd/es/grid/col";
import Row from "antd/es/grid/row";
import Tag from "antd/es/tag";
import type { ReactNode } from "react";

import {
  AdminError,
  AdminLoading,
  AdminPage,
  AdminPageHeader,
} from "@/components/admin/AdminPage";
import { useAdminSession } from "@/features/auth/session-context";
import { useSettingsQuery } from "@/features/dashboard/queries";

export default function SettingsPage() {
  const { runtimeMode } = useAdminSession();
  const settings = useSettingsQuery(runtimeMode);
  if (settings.isPending) {
    return <AdminLoading message="正在读取运行设置..." />;
  }
  if (settings.isError || !settings.data) {
    return <AdminError description="运行设置暂时不可用。" title="无法读取运行设置" />;
  }
  const data = settings.data;
  return (
    <AdminPage className="dashboard-page">
      <AdminPageHeader
        description="只展示安全运行开关与协调参数，不返回密钥、数据库地址或身份提供商详情。"
        extra={<Tag color={data.environment === "production" ? "green" : "blue"}>{data.environment.toUpperCase()}</Tag>}
        kicker="SYSTEM / SETTINGS"
        title="运行设置"
      />
      <Row gutter={[16, 16]}>
        <SettingsSection
          rows={[
            ["OIDC", flag(data.authentication.oidc_enabled)],
            ["开发登录", flag(data.authentication.development_login_enabled)],
            ["Admin Secure Cookie", flag(data.authentication.secure_admin_cookie)],
            ["Public Secure Cookie", flag(data.authentication.secure_public_cookie)],
            ["Admin 会话", duration(data.authentication.admin_session_ttl_seconds)],
            ["Public 会话", duration(data.authentication.public_session_ttl_seconds)],
          ]}
          title="认证边界"
        />
        <SettingsSection
          rows={[
            ["旧内容写入", flag(data.compatibility.legacy_content_writes_enabled)],
            ["旧语音生成", flag(data.compatibility.legacy_voice_generation_enabled)],
            ["TTS", flag(data.tts_enabled)],
          ]}
          title="兼容写入口"
        />
        <SettingsSection
          rows={[
            ["租约", `${data.live_runs.lease_seconds} 秒`],
            ["心跳", `${data.live_runs.heartbeat_seconds} 秒`],
            ["事件轮询", `${data.live_runs.event_poll_seconds} 秒`],
            ["API 前缀", <Tag>{data.api_prefix}</Tag>],
          ]}
          title="运行协调"
        />
        <SettingsSection
          rows={[
            ["语音轮询", `${data.workers.judge_voice_poll_seconds} 秒`],
            ["语音心跳", `${data.workers.judge_voice_heartbeat_seconds} 秒`],
            ["语音探针窗口", `${data.workers.judge_voice_probe_max_age_seconds} 秒`],
            ["Reaper 轮询", `${data.workers.reaper_poll_seconds} 秒`],
            ["失联宽限", `${data.workers.reaper_stale_grace_seconds} 秒`],
            ["最大恢复次数", String(data.workers.reaper_max_attempts)],
            ["Reaper 探针窗口", `${data.workers.reaper_probe_max_age_seconds} 秒`],
          ]}
          title="持久 Worker"
        />
      </Row>
    </AdminPage>
  );
}

function SettingsSection({
  rows,
  title,
}: {
  rows: Array<[string, ReactNode]>;
  title: string;
}) {
  const items: DescriptionsItemType[] = rows.map(([label, value]) => ({
    children: value,
    key: label,
    label,
  }));
  return (
    <Col lg={12} xs={24}>
      <Card title={<h2>{title}</h2>}>
        <Descriptions column={1} items={items} size="small" />
      </Card>
    </Col>
  );
}

function flag(value: boolean) {
  return <Tag color={value ? "success" : "default"}>{value ? "已启用" : "已关闭"}</Tag>;
}

function duration(seconds: number) {
  return seconds >= 86_400
    ? `${Math.round(seconds / 86_400)} 天`
    : `${Math.round(seconds / 3_600)} 小时`;
}
