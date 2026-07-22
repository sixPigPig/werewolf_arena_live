import ArrowRightOutlined from "@ant-design/icons/es/icons/ArrowRightOutlined";
import Alert from "antd/es/alert";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Col from "antd/es/grid/col";
import Row from "antd/es/grid/row";
import Space from "antd/es/space";
import Statistic from "antd/es/statistic";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { Link, useNavigate } from "react-router-dom";

import {
  AdminError,
  AdminLoading,
  AdminPage,
  AdminPageHeader,
} from "@/components/admin/AdminPage";
import { useAdminSession } from "@/features/auth/session-context";
import { useOverviewQuery } from "@/features/dashboard/queries";

export default function OverviewPage() {
  const navigate = useNavigate();
  const { runtimeMode } = useAdminSession();
  const overview = useOverviewQuery(runtimeMode);

  if (overview.isPending) {
    return <AdminLoading message="正在汇总运营状态..." />;
  }
  if (overview.isError || !overview.data) {
    return (
      <AdminError
        description="运营总览暂时不可用。"
        onRetry={overview.refetch}
        title="无法读取运营总览"
      />
    );
  }

  const data = overview.data;
  return (
    <AdminPage className="dashboard-page">
      <AdminPageHeader
        description="聚合内容、对局、运行、任务与自动恢复健康状态。"
        extra={<Tag color={data.environment === "production" ? "green" : "blue"}>{data.environment.toUpperCase()}</Tag>}
        kicker="OPERATIONS / OVERVIEW"
        title="运营总览"
      />

      <Row gutter={[16, 16]}>
        <MetricCard
          detail={`${data.profiles.draft} 草稿 · ${data.profiles.published} 已发布`}
          href="/content/players"
          label="玩家内容"
          value={data.profiles.total}
        />
        <MetricCard
          detail={`${data.games.incomplete} 未完整 · ${data.games.resumable} 可恢复`}
          href="/operations/games"
          label="对局记录"
          value={data.games.total}
        />
        <MetricCard
          detail={`${data.runs.stale} 失联 · ${data.runs.failed} 失败`}
          href="/operations/runs"
          label="活动运行"
          value={data.runs.queued + data.runs.running}
        />
        <MetricCard
          detail={`${data.jobs.failed} 失败 · ${data.jobs.completed} 完成`}
          href="/system/jobs"
          label="后台任务"
          value={data.jobs.queued + data.jobs.running}
        />
      </Row>

      <Card
        extra={
          <Tag color={data.quality.worker_up ? "success" : "error"}>
            Evaluator {data.quality.worker_up ? "正常" : "异常"}
          </Tag>
        }
        title={<h2 id="dashboard-quality-title">对局质量健康</h2>}
      >
        <Typography.Text className="ant-admin-section-kicker">
          GAME QUALITY / LAST {data.quality.cohort_days} DAYS
        </Typography.Text>
        {data.quality.sample_count === 0 ? (
          <Alert
            description={`不会把空数据展示为 100% 通过；当前有 ${data.quality.legacy_count} 局旧数据。`}
            showIcon
            title="暂无已完成评估样本"
            type="info"
          />
        ) : (
          <Row gutter={[12, 12]}>
            <QualityMetric
              detail={`样本 ${data.quality.sample_count} · 警告 ${data.quality.warn_count} · 不可用 ${data.quality.unavailable_count}`}
              label="评估结论"
              value={`${data.quality.pass_count} 通过 / ${data.quality.fail_count} 失败`}
            />
            <QualityMetric
              detail={`部分数据 ${data.quality.partial_count} · 旧数据 ${data.quality.legacy_count}`}
              label="P0 对局"
              value={String(data.quality.p0_game_count)}
            />
            <QualityMetric
              detail={`Prompt 覆盖 ${ratioLabel(data.quality.prompt_fact_included, data.quality.prompt_fact_expected)}`}
              label="关键事实写入率"
              value={ratioLabel(data.quality.critical_fact_recorded, data.quality.critical_fact_expected)}
            />
            <QualityMetric
              detail={`阵容告警 ${data.quality.lineup_warning_count} · 发言耗尽 ${data.quality.speech_retry_exhausted_count}`}
              label="有效语音覆盖"
              value={ratioLabel(data.quality.voice_covered, data.quality.voice_expected)}
            />
            <QualityMetric
              detail={`动作样本 ${data.quality.action_sample_count}`}
              label="动作 P95"
              value={data.quality.action_p95_ms === null ? `样本不足 (${data.quality.action_sample_count}/20)` : `${data.quality.action_p95_ms} ms`}
            />
            <QualityMetric
              detail={`执行失败 ${data.quality.worker_failed_count} · 过期租约 ${data.quality.expired_lease_count}`}
              label="评估队列"
              value={`${data.quality.pending_count} 等待 / ${data.quality.processing_count} 处理中`}
            />
          </Row>
        )}
      </Card>

      <Row gutter={[16, 16]}>
        <Col lg={14} xs={24}>
          <Card
            extra={<Tag color={data.reaper_up ? "success" : "error"}>Reaper {data.reaper_up ? "正常" : "异常"}</Tag>}
            title={<h2 id="dashboard-alerts-title">需要关注</h2>}
          >
            {data.alerts.length === 0 ? (
              <Alert
                description="运行恢复和持久任务当前没有异常信号。"
                showIcon
                title="没有活动告警"
                type="success"
              />
            ) : (
              <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                {data.alerts.map((alert) => (
                  <Alert
                    action={<Button onClick={() => navigate(alert.href)} size="small">{alert.count} 项 <ArrowRightOutlined /></Button>}
                    description={alert.detail}
                    key={alert.code}
                    showIcon
                    title={alert.title}
                    type={alert.severity === "critical" ? "error" : "warning"}
                  />
                ))}
              </Space>
            )}
          </Card>
        </Col>
        <Col lg={10} xs={24}>
          <Card title={<h2 id="dashboard-breakdown-title">状态分布</h2>}>
            <dl className="ant-dashboard-breakdown">
              <div><dt>运行完成 / 取消</dt><dd>{data.runs.completed} / {data.runs.canceled}</dd></div>
              <div><dt>恢复已耗尽</dt><dd>{data.runs.recovery_exhausted}</dd></div>
              <div><dt>推荐玩家</dt><dd>{data.profiles.featured}</dd></div>
              <div><dt>语音任务失败</dt><dd>{data.jobs.failed}</dd></div>
            </dl>
            <Typography.Text type="secondary">
              更新时间：{new Date(data.generated_at).toLocaleString("zh-CN")}
            </Typography.Text>
          </Card>
        </Col>
      </Row>
    </AdminPage>
  );
}

function MetricCard({
  detail,
  href,
  label,
  value,
}: {
  detail: string;
  href: string;
  label: string;
  value: number;
}) {
  return (
    <Col lg={6} sm={12} xs={24}>
      <Link className="ant-dashboard-metric-link" to={href}>
        <Card hoverable>
          <Statistic title={label} value={value} />
          <Typography.Text type="secondary">{detail}</Typography.Text>
        </Card>
      </Link>
    </Col>
  );
}

function QualityMetric({ detail, label, value }: { detail: string; label: string; value: string }) {
  return (
    <Col lg={8} md={12} xs={24}>
      <Card className="ant-quality-metric" size="small">
        <Statistic title={label} value={value} />
        <Typography.Text type="secondary">{detail}</Typography.Text>
      </Card>
    </Col>
  );
}

function ratioLabel(numerator: number, denominator: number) {
  if (denominator === 0) return "无样本";
  return `${((numerator / denominator) * 100).toFixed(1)}% (${numerator}/${denominator})`;
}
