import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Form from "antd/es/form";
import Select from "antd/es/select";
import Space from "antd/es/space";
import Typography from "antd/es/typography";
import { useEffect } from "react";

import { isAdminApiError } from "@/api/problem-details";
import {
  AdminError,
  AdminLoading,
  AdminPage,
  AdminPageHeader,
} from "@/components/admin/AdminPage";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import {
  getAdminJudgeConfiguration,
  updateAdminJudgeConfiguration,
} from "@/features/judge-configuration/api";
import { previewJudgeConfiguration } from "@/features/judge-configuration/preview";
import { adminJudgeConfigurationKeys } from "@/features/judge-configuration/query-keys";
import type { UpdateJudgeConfigurationRequest } from "@/features/judge-configuration/types";

const { Text } = Typography;

type JudgeConfigurationForm = Pick<
  UpdateJudgeConfigurationRequest,
  "model_id" | "tts_speaker"
>;

export default function JudgeConfigurationPage() {
  const [form] = Form.useForm<JudgeConfigurationForm>();
  const queryClient = useQueryClient();
  const { runtimeMode, session } = useAdminSession();
  const canManage = hasAdminPermission(session?.permissions ?? [], "settings.manage");
  const configurationQuery = useQuery({
    queryKey: adminJudgeConfigurationKeys.detail,
    queryFn: ({ signal }) =>
      runtimeMode === "preview"
        ? Promise.resolve(previewJudgeConfiguration)
        : getAdminJudgeConfiguration(signal),
    staleTime: 15_000,
  });
  const mutation = useMutation({
    mutationFn: (request: UpdateJudgeConfigurationRequest) =>
      updateAdminJudgeConfiguration(request, session?.csrf_token ?? ""),
    onSuccess: (configuration) => {
      queryClient.setQueryData(adminJudgeConfigurationKeys.detail, configuration);
    },
  });
  const configuration = configurationQuery.data;

  useEffect(() => {
    if (!configuration) return;
    form.setFieldsValue({
      model_id: configuration.model_id,
      tts_speaker: configuration.tts_speaker,
    });
  }, [configuration, form]);

  if (configurationQuery.isPending) {
    return <AdminLoading message="正在读取法官配置..." />;
  }
  if (configurationQuery.isError || !configuration) {
    return (
      <AdminError
        description="法官配置暂时不可用。"
        onRetry={() => configurationQuery.refetch()}
        title="无法读取法官配置"
      />
    );
  }

  const editable = canManage && runtimeMode !== "preview";
  const expectedVersion = configuration.version;

  function save(values: JudgeConfigurationForm) {
    mutation.mutate({
      model_provider: "agent_plan",
      model_id: values.model_id,
      tts_speaker: values.tts_speaker,
      expected_version: expectedVersion,
    });
  }

  return (
    <AdminPage className="judge-configuration-page">
      <AdminPageHeader
        description="配置动态法官播报使用的模型与音色，不包含虚拟玩家的人设、策略及表达参数。"
        kicker="CONTENT / JUDGE"
        title="法官配置"
      />

      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {configuration.source === "environment" ? (
          <Alert
            description="首次保存后将写入数据库，并覆盖环境变量中的法官模型与音色默认值。"
            showIcon
            title="当前使用环境默认配置"
            type="info"
          />
        ) : null}
        {!configuration.speaker_catalog_available ? (
          <Alert
            description="目前只能保留当前音色；目录恢复后可选择其他音色。"
            showIcon
            title="音色目录暂时不可用"
            type="warning"
          />
        ) : null}
        <Alert
          description="动态法官播报会读取这里的配置；已经生成的静态法官语音不会自动改写，重新生成时会使用所选音色。"
          showIcon
          title="生效范围"
          type="info"
        />
        {mutation.isError ? (
          <Alert
            description={configurationError(mutation.error)}
            showIcon
            title="保存失败"
            type="error"
          />
        ) : null}
        {mutation.isSuccess ? (
          <Alert showIcon title="法官配置已保存" type="success" />
        ) : null}

        <Card title="播报配置">
          <Form<JudgeConfigurationForm>
            form={form}
            layout="vertical"
            onFinish={save}
            requiredMark={false}
          >
            <Form.Item
              label="模型"
              name="model_id"
              rules={[{ required: true, message: "请选择法官模型" }]}
            >
              <Select
                disabled={!editable}
                optionFilterProp="label"
                options={configuration.models.map((model) => ({
                  label: `${model.label} · ${model.model_id}`,
                  value: model.model_id,
                }))}
                placeholder="选择法官模型"
                showSearch
              />
            </Form.Item>
            <Form.Item
              extra={`TTS 资源：${configuration.tts_resource_id}`}
              label="音色"
              name="tts_speaker"
              rules={[{ required: true, message: "请选择法官音色" }]}
            >
              <Select
                disabled={!editable || !configuration.speaker_catalog_available}
                optionFilterProp="label"
                options={configuration.speakers.map((speaker) => ({
                  label: `${speaker.name} · ${speaker.voice_type}`,
                  value: speaker.voice_type,
                }))}
                placeholder="选择法官音色"
                showSearch
              />
            </Form.Item>
            <Space align="center" wrap>
              <Button
                disabled={!editable}
                htmlType="submit"
                loading={mutation.isPending}
                type="primary"
              >
                保存配置
              </Button>
              {!canManage ? <Text type="secondary">当前账号仅可查看。</Text> : null}
              {runtimeMode === "preview" ? (
                <Text type="secondary">预览模式不写入配置。</Text>
              ) : null}
            </Space>
          </Form>
        </Card>
      </Space>
    </AdminPage>
  );
}

function configurationError(error: unknown) {
  if (isAdminApiError(error)) {
    return error.problem.detail;
  }
  return "法官配置保存失败，请稍后重试。";
}
