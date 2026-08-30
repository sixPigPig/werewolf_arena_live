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
        description="聚合内容、任务与运行参数健康状态。"
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
          detail={`${data.jobs.failed} 失败 · ${data.jobs.completed} 完成`}
          href="/system/jobs"
          label="后台任务"
          value={data.jobs.queued + data.jobs.running}
        />
      </Row>

      <Row gutter={[16, 16]}>
        <Col lg={14} xs={24}>
          <Card
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
              <div><dt>推荐玩家</dt><dd>{data.profiles.featured}</dd></div>
              <div><dt>失败任务</dt><dd>{data.jobs.failed}</dd></div>
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
