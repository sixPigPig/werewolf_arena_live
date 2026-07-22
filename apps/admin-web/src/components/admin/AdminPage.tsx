import Alert from "antd/es/alert";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Empty from "antd/es/empty";
import Flex from "antd/es/flex";
import Result from "antd/es/result";
import Skeleton from "antd/es/skeleton";
import Space from "antd/es/space";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import type { ReactNode } from "react";

const { Paragraph, Text, Title } = Typography;

type AdminPageProps = {
  children: ReactNode;
  className?: string;
};

export function AdminPage({ children, className = "" }: AdminPageProps) {
  return <div className={`admin-page ant-admin-page ${className}`.trim()}>{children}</div>;
}

type AdminPageHeaderProps = {
  description?: ReactNode;
  extra?: ReactNode;
  kicker?: ReactNode;
  title: ReactNode;
};

export function AdminPageHeader({
  description,
  extra,
  kicker,
  title,
}: AdminPageHeaderProps) {
  return (
    <Flex align="flex-start" className="ant-admin-page-header" gap={20} justify="space-between" wrap>
      <div>
        {kicker ? <Text className="ant-admin-page-kicker">{kicker}</Text> : null}
        <Title level={1}>{title}</Title>
        {description ? <Paragraph>{description}</Paragraph> : null}
      </div>
      {extra ? <Space wrap>{extra}</Space> : null}
    </Flex>
  );
}

type AdminSectionProps = {
  children: ReactNode;
  className?: string;
  extra?: ReactNode;
  title?: ReactNode;
};

export function AdminSection({
  children,
  className,
  extra,
  title,
}: AdminSectionProps) {
  return (
    <Card className={className} extra={extra} title={title}>
      {children}
    </Card>
  );
}

export function AdminLoading({ message }: { message: string }) {
  return (
    <Card aria-live="polite" role="status">
      <Skeleton active paragraph={{ rows: 4 }} title={{ width: "36%" }} />
      <Text type="secondary">{message}</Text>
    </Card>
  );
}

type AdminErrorProps = {
  description: ReactNode;
  onRetry?: () => unknown;
  requestId?: string | null;
  title?: ReactNode;
};

export function AdminError({
  description,
  onRetry,
  requestId,
  title = "页面暂时不可用",
}: AdminErrorProps) {
  return (
    <Result
      extra={
        onRetry ? (
          <Button onClick={() => void onRetry()} type="primary">
            重新加载
          </Button>
        ) : null
      }
      status="error"
      subTitle={
        <Space orientation="vertical" size={4}>
          <span>{description}</span>
          {requestId ? <Text type="secondary">请求编号：{requestId}</Text> : null}
        </Space>
      }
      title={title}
    />
  );
}

export function AdminEmpty({
  action,
  description,
}: {
  action?: ReactNode;
  description: ReactNode;
}) {
  return (
    <Empty description={description} image={Empty.PRESENTED_IMAGE_SIMPLE}>
      {action}
    </Empty>
  );
}

export function AdminInlineWarning({ message }: { message: ReactNode }) {
  return <Alert showIcon title={message} type="warning" />;
}

export function AdminStatusTag({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "error" | "processing" | "success" | "warning";
}) {
  const color = {
    default: "default",
    error: "error",
    processing: "processing",
    success: "success",
    warning: "warning",
  }[tone];
  return <Tag color={color}>{children}</Tag>;
}
