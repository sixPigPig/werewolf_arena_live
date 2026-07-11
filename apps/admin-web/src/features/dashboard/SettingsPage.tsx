import { useAdminSession } from "@/features/auth/session-context";
import { useSettingsQuery } from "@/features/dashboard/queries";

export default function SettingsPage() {
  const { runtimeMode } = useAdminSession();
  const settings = useSettingsQuery(runtimeMode);
  if (settings.isPending) return <div className="dashboard-page-state">正在读取运行设置...</div>;
  if (settings.isError || !settings.data) return <div className="dashboard-page-state" role="alert">运行设置暂时不可用。</div>;
  const data = settings.data;
  return (
    <div className="admin-page dashboard-page">
      <header className="page-heading"><div><span className="page-kicker">SYSTEM / SETTINGS</span><h1>运行设置</h1><p>只展示安全运行开关与协调参数，不返回密钥、数据库地址或身份提供商详情。</p></div><span className={`dashboard-environment is-${data.environment}`}>{data.environment.toUpperCase()}</span></header>
      <div className="settings-grid">
        <SettingsSection title="认证边界" rows={[
          ["OIDC", flag(data.authentication.oidc_enabled)], ["开发登录", flag(data.authentication.development_login_enabled)], ["Admin Secure Cookie", flag(data.authentication.secure_admin_cookie)], ["Public Secure Cookie", flag(data.authentication.secure_public_cookie)], ["Admin 会话", duration(data.authentication.admin_session_ttl_seconds)], ["Public 会话", duration(data.authentication.public_session_ttl_seconds)],
        ]} />
        <SettingsSection title="兼容写入口" rows={[
          ["旧内容写入", flag(data.compatibility.legacy_content_writes_enabled)], ["旧收藏写入", flag(data.compatibility.legacy_favorite_writes_enabled)], ["旧语音生成", flag(data.compatibility.legacy_voice_generation_enabled)], ["TTS", flag(data.tts_enabled)],
        ]} />
        <SettingsSection title="运行协调" rows={[
          ["租约", `${data.live_runs.lease_seconds} 秒`], ["心跳", `${data.live_runs.heartbeat_seconds} 秒`], ["事件轮询", `${data.live_runs.event_poll_seconds} 秒`], ["API 前缀", data.api_prefix],
        ]} />
        <SettingsSection title="持久 Worker" rows={[
          ["语音轮询", `${data.workers.judge_voice_poll_seconds} 秒`], ["Reaper 轮询", `${data.workers.reaper_poll_seconds} 秒`], ["失联宽限", `${data.workers.reaper_stale_grace_seconds} 秒`], ["最大恢复次数", String(data.workers.reaper_max_attempts)], ["心跳探针窗口", `${data.workers.reaper_probe_max_age_seconds} 秒`],
        ]} />
      </div>
    </div>
  );
}

function SettingsSection({ title, rows }: { title: string; rows: Array<[string, string]> }) {
  return <section className="settings-panel"><h2>{title}</h2><dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section>;
}

function flag(value: boolean) { return value ? "已启用" : "已关闭"; }
function duration(seconds: number) { return seconds >= 86400 ? `${Math.round(seconds / 86400)} 天` : `${Math.round(seconds / 3600)} 小时`; }
