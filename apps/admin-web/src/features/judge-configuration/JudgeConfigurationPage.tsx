import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import AntApp from "antd/es/app";
import Button from "antd/es/button";
import Card from "antd/es/card";
import Form from "antd/es/form";
import Select from "antd/es/select";
import Space from "antd/es/space";
import Typography from "antd/es/typography";
import { useEffect } from "react";

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
import { adminOperationErrorDescription } from "@/lib/admin-notification";

const { Text } = Typography;

type JudgeConfigurationForm = Pick<
  UpdateJudgeConfigurationRequest,
  "voice_mode" | "tts_speaker" | "random_tts_speakers"
>;

export default function JudgeConfigurationPage() {
  const { notification } = AntApp.useApp();
  const [form] = Form.useForm<JudgeConfigurationForm>();
  const voiceMode = Form.useWatch("voice_mode", form) ?? "fixed";
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
    onError: (error) => {
      notification.error({
        description: adminOperationErrorDescription(
          error,
          "法官配置保存失败，请稍后重试。",
        ),
        title: "法官配置保存失败",
      });
    },
    onSuccess: (configuration) => {
      queryClient.setQueryData(adminJudgeConfigurationKeys.detail, configuration);
      notification.success({ title: "法官配置已保存" });
    },
  });
  const configuration = configurationQuery.data;

  useEffect(() => {
    if (!configuration) return;
    form.setFieldsValue({
      voice_mode: configuration.voice_mode,
      tts_speaker: configuration.tts_speaker,
      random_tts_speakers: configuration.random_tts_speakers,
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
      voice_mode: values.voice_mode,
      tts_speaker: values.voice_mode === "fixed" ? values.tts_speaker : null,
      random_tts_speakers:
        values.voice_mode === "random" ? values.random_tts_speakers : [],
      expected_version: expectedVersion,
    });
  }

  return (
    <AdminPage className="judge-configuration-page">
      <AdminPageHeader
        description="法官使用确定性模板准确播报引擎事实；这里仅配置整局使用的法官音色。"
        kicker="CONTENT / JUDGE"
        title="法官配置"
      />

      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {configuration.source === "environment" ? (
          <Alert
            description="首次保存后将写入数据库，并覆盖环境变量中的法官默认音色。"
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
          description="固定模式整局使用所选音色；每局随机模式会在创建对局时从音色池选择一次并冻结，继续、重试和回放保持一致。"
          showIcon
          title="生效范围"
          type="info"
        />
        <Card title="播报配置">
          <Form<JudgeConfigurationForm>
            form={form}
            layout="vertical"
            onFinish={save}
            requiredMark={false}
          >
            <Form.Item label="音色模式" name="voice_mode" rules={[{ required: true }]}>
              <Select
                disabled={!editable}
                options={[
                  { label: "固定音色", value: "fixed" },
                  { label: "每局随机音色", value: "random" },
                ]}
              />
            </Form.Item>
            {voiceMode === "fixed" ? (
              <Form.Item
                extra={`TTS 资源：${configuration.tts_resource_id}`}
                label="固定音色"
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
            ) : (
              <Form.Item
                extra="开局时从音色池随机选择一次；至少选择两个音色。"
                label="随机音色池"
                name="random_tts_speakers"
                rules={[
                  { required: true, message: "请选择随机音色池" },
                  {
                    min: 2,
                    type: "array",
                    message: "随机音色池至少需要两个音色",
                  },
                ]}
              >
                <Select
                  disabled={!editable || !configuration.speaker_catalog_available}
                  mode="multiple"
                  optionFilterProp="label"
                  options={configuration.speakers.map((speaker) => ({
                    label: `${speaker.name} · ${speaker.voice_type}`,
                    value: speaker.voice_type,
                  }))}
                  placeholder="选择至少两个法官音色"
                  showSearch
                />
              </Form.Item>
            )}
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
