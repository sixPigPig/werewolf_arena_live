import Alert from "antd/es/alert";
import Collapse from "antd/es/collapse";
import Descriptions from "antd/es/descriptions";
import Empty from "antd/es/empty";
import Flex from "antd/es/flex";
import Space from "antd/es/space";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import type { ReactNode } from "react";

import {
  actionLabel,
  formatClock,
  phaseLabel,
  prettyJson,
} from "@/v2/game-records/presentation";
import type {
  V2GameRecordDetail,
  V2ModelRequest,
} from "@/v2/game-records/types";

type RequestMessage = {
  role: string;
  text: string;
};

type StructuredPrompt = {
  intro: string | null;
  value: Record<string, unknown>;
};

const fieldLabels: Record<string, string> = {
  ability_id: "能力",
  ability_instance_id: "能力实例 ID",
  activation_id: "激活 ID",
  action_id: "动作 ID",
  action_type: "动作类型",
  addressed_to: "提问对象",
  answer_record_seq: "回答记录序号",
  answer_source_event_id: "回答来源事件",
  answer_turn_index: "回答发言序号",
  actor: "执行者",
  actor_id: "玩家 ID",
  actor_kind: "执行者类型",
  actor_profile: "角色画像",
  allowed_knowledge: "允许使用的信息",
  allowed_target_ids: "可选目标",
  audience: "受众",
  base_delivery_instruction: "基础语气说明",
  base_delivery_intensity: "基础语气强度",
  base_delivery_mood: "基础语气",
  base_delivery_pace: "基础语速",
  captured_at: "采集时间",
  candidate_player_ids: "候选玩家",
  candidates: "候选玩家",
  catchphrases: "常用表达",
  consensus_rule: "共识规则",
  context: "补充上下文",
  confirmation_status: "确认状态",
  current_round_no: "当前轮次",
  current_round_statement_char_count: "本轮原文字符数",
  current_round_statement_count: "本轮原文数",
  timeline: "完整公开发言时间线",
  decision_rules: "决策约束",
  dead_player_ids: "出局玩家",
  display_name: "玩家名称",
  event_type: "事件类型",
  exact_quote: "原话",
  facts: "已知事实",
  game_id: "对局 ID",
  game_setup: "对局配置",
  heal_remaining: "解药剩余",
  id: "ID",
  influence: "影响信号",
  judge_configuration: "法官配置",
  kind: "类型",
  language: "语言",
  max_rounds: "最大轮次",
  mode: "选择方式",
  model_id: "模型",
  model_provider: "模型提供商",
  must_choose_exact_candidate_id: "必须从候选玩家中选择",
  name: "姓名",
  night_no: "夜晚轮次",
  normalized_sha256: "内容摘要",
  objective: "动作目标",
  output_contract: "输出要求",
  payload: "事件内容",
  player_count: "玩家数",
  player_id: "玩家 ID",
  prompt_projection: "提示词投影摘要",
  prompt_schema_version: "提示词结构版本",
  personality: "性格与策略",
  prior_team_proposals: "此前提议",
  projection_policy_id: "信息投影规则",
  public_state: "公开事实",
  public_history: "公开历史",
  hard_rules: "硬规则",
  history: "公开发言历史",
  ledger_schema_version: "发言账本版本",
  model_view_schema_version: "模型视图版本",
  ledger_statement_count: "完整账本发言数",
  ledger_statement_char_count: "完整账本发言字符数",
  ledger_claim_count: "完整账本声明数",
  ledger_question_count: "完整账本提问数",
  ledger_relation_count: "完整账本关系数",
  ledger_serialized_char_count: "完整账本序列化字符数",
  model_view_statement_count: "模型视图发言数",
  model_view_statement_char_count: "模型视图发言字符数",
  model_view_claim_annotation_count: "模型视图声明注释数",
  model_view_question_count: "模型视图提问数",
  model_view_relation_count: "模型视图关系数",
  model_view_serialized_char_count: "模型视图序列化字符数",
  dropped_statement_count: "丢弃发言数",
  dropped_claim_count: "丢弃声明数",
  dropped_question_count: "丢弃提问数",
  dropped_relation_count: "丢弃关系数",
  selection_profile: "模型视图选择规则",
  focus: "当前动作引用焦点",
  annotations: "发言结构化注释",
  claim_id: "声明 ID",
  claim_type: "声明类型",
  claimed_action_in: "声明的行动时间",
  claimed_result: "声明的结果",
  claims: "结构化声明",
  first_party_source_priority: "第一方来源优先级",
  mentioned_player_refs: "涉及玩家",
  occurred_in: "实际发生时间",
  open_question_count: "未回答提问数",
  unparsed_statement_refs: "未可靠解析发言引用",
  question_count: "提问数",
  question_id: "提问 ID",
  questions: "结构化提问",
  record_seq: "记录序号",
  relation_count: "时序关系数",
  relation_id: "关系 ID",
  relation_type: "关系类型",
  relations: "确定性时序关系",
  reported_speaker_ref: "被转述玩家",
  secondary_paraphrase_count: "二手转述数",
  source_event_id: "来源事件",
  source_kind: "来源类型",
  source_record_seq_max: "最大来源记录序号",
  source_record_seq_min: "最小来源记录序号",
  source_rules: "来源与时序规则",
  specificity: "具体程度",
  statement_id: "发言 ID",
  statement_order: "发言排序规则",
  structured_claim_count: "结构化声明数",
  subject_refs: "评价对象",
  temporal_order_valid: "时序是否合法",
  temporal_relation_status: "时序关系状态",
  to_question_id: "关联提问 ID",
  to_record_seq: "提问记录序号",
  to_source_event_id: "提问来源事件",
  to_turn_index: "提问发言序号",
  turn_index: "发言序号",
  unverified_reported_response_count: "未验证回答转述数",
  uttered_record_seq: "发言记录序号",
  uttered_turn_index: "发言序号",
  asked_by: "提问者",
  asked_in: "提问发生时间",
  asked_record_seq: "提问记录序号",
  asked_turn_index: "提问发言序号",
  asserted_relation_type: "转述所声称的关系",
  from_record_seq: "回应记录序号",
  from_source_event_id: "回应来源事件",
  from_speaker_ref: "回应者",
  from_turn_index: "回应发言序号",
  role_summary: "身份配置",
  round_no: "轮次",
  rule_name: "规则",
  run_id: "运行 ID",
  schema_version: "结构版本",
  self_heal_allowed: "允许自救",
  seat: "座位",
  signals: "信号",
  speech: "发言内容",
  stage: "阶段",
  status: "状态",
  speaker_ref: "发言者",
  strategy_profile: "策略类型",
  self: "玩家自身与私有事实",
  strength: "影响强度",
  target_optional: "目标可为空",
  target_player_id: "目标玩家",
  target_ref: "目标玩家",
  target_policy: "目标规则",
  thinking: "思考模式",
  tts_speaker: "语音角色",
  type: "类型",
  version: "版本",
  topic: "主题",
  knowledge_fact_ids: "知识事实 ID",
  knowledge_projection_hash: "信息投影摘要",
  werewolf_teammates: "狼人队友",
};

const valueLabels: Record<string, string> = {
  all: "公开",
  decision: "决策",
  decision_and_speech: "决策 + 发言",
  day_debate: "白天讨论",
  day_speech_committed: "白天发言已提交",
  disabled: "未启用",
  god_view: "上帝视角",
  judge: "法官",
  none: "无需选择",
  optional: "可选",
  player: "玩家",
  private: "私密",
  public: "公开",
  public_speech: "公开发言",
  required: "必须选择",
  sheriff_campaign: "警长竞选",
  speech: "发言",
};

export function ReadableModelInput({
  request,
}: {
  request: V2ModelRequest | null;
}) {
  if (!request?.request_payload) {
    return <Empty description="这一步没有模型输入" />;
  }
  const messages = requestMessages(request.request_payload);
  const serializedCharCount = numericField(
    request.prompt_projection,
    "serialized_char_count",
  );
  const ledgerSchemaVersion = numericField(
    request.prompt_projection,
    "ledger_schema_version",
  );
  const modelViewSchemaVersion = numericField(
    request.prompt_projection,
    "model_view_schema_version",
  );
  const ledgerStatementCount = numericField(
    request.prompt_projection,
    "ledger_statement_count",
  );
  const droppedStatementCount = numericField(
    request.prompt_projection,
    "dropped_statement_count",
  );
  const currentRoundStatementCount = numericField(
    request.prompt_projection,
    "current_round_statement_count",
  );
  const structuredClaimCount = numericField(
    request.prompt_projection,
    "structured_claim_count",
  );
  const openQuestionCount = numericField(
    request.prompt_projection,
    "open_question_count",
  );
  return (
    <div className="v2-inspector-panel">
      {request.input_source === "reconstructed" ? (
        <Alert
          description="该历史请求早于完整输入持久化；这里根据当时保存的动作上下文和当前模板重建，不能视为逐字原始请求。"
          showIcon
          title="历史输入为重建结果"
          type="warning"
        />
      ) : null}
      <Descriptions
        column={2}
        items={[
          {
            key: "model",
            label: "模型",
            children: String(request.request_payload.model ?? "—"),
          },
          {
            key: "kind",
            label: "请求类型",
            children: request.request_kind === "decision" ? "决策" : "发言",
          },
          {
            key: "stream",
            label: "流式响应",
            children: request.request_payload.stream === true ? "是" : "否",
          },
          {
            key: "tokens",
            label: "最大输出",
            children: String(
              request.request_payload.max_output_tokens ??
                request.request_payload.max_tokens ??
                "—",
            ),
          },
          {
            key: "prompt-schema",
            label: "提示词结构",
            children:
              request.prompt_schema_version === null
                ? "—"
                : `V${request.prompt_schema_version}`,
          },
          {
            key: "prompt-size",
            label: "投影字符数",
            children:
              serializedCharCount === null
                ? "—"
                : serializedCharCount.toLocaleString("zh-CN"),
          },
          {
            key: "ledger-schema",
            label: "发言账本",
            children:
              ledgerSchemaVersion === null
                ? "—"
                : `V${ledgerSchemaVersion}`,
          },
          {
            key: "model-view-schema",
            label: "模型视图",
            children:
              modelViewSchemaVersion === null
                ? "—"
                : `V${modelViewSchemaVersion}`,
          },
          {
            key: "ledger-statements",
            label: "完整公开发言",
            children:
              ledgerStatementCount === null
                ? "—"
                : String(ledgerStatementCount),
          },
          {
            key: "dropped-statements",
            label: "发言截断",
            children:
              droppedStatementCount === null
                ? "—"
                : droppedStatementCount === 0
                  ? "0（无截断）"
                  : String(droppedStatementCount),
          },
          {
            key: "current-statements",
            label: "本轮完整发言",
            children:
              currentRoundStatementCount === null
                ? "—"
                : String(currentRoundStatementCount),
          },
          {
            key: "structured-claims",
            label: "结构化声明",
            children:
              structuredClaimCount === null
                ? "—"
                : String(structuredClaimCount),
          },
          {
            key: "open-questions",
            label: "未回答提问",
            children:
              openQuestionCount === null ? "—" : String(openQuestionCount),
          },
        ]}
        size="small"
      />
      {messages.length ? (
        messages.map((message, index) => (
          <PromptMessageCard
            key={`${message.role}-${index}`}
            message={message}
          />
        ))
      ) : (
        <ReadableGroup label="请求参数" value={request.request_payload} />
      )}
    </div>
  );
}

export function ReadableModelOutput({
  request,
}: {
  request: V2ModelRequest | null;
}) {
  if (!request) return <Empty description="这一步没有模型输出" />;
  if (request.output_source === "unavailable") {
    return <Empty description="模型尚未返回，或历史记录没有可恢复的输出" />;
  }

  const rawValue = parseJsonValue(request.raw_response);
  const adoptedValue = request.parsed_output ?? rawValue ?? request.raw_response;
  const rawMatchesAdopted = outputsMatch(
    request.raw_response,
    rawValue,
    request.parsed_output,
  );

  return (
    <div className="v2-inspector-panel">
      {request.output_source === "legacy_inferred" ? (
        <Alert
          description="该历史请求没有保存供应商原始响应；下方结果来自已提交的展示文本。"
          showIcon
          title="原始输出不可用"
          type="warning"
        />
      ) : null}
      {request.passive_observations.length ? (
        <>
          <Alert
            description="以下信号只记录模型是否违背已给规则，用于评估真实推理表现；不会触发重试、改写、拦截或替换。"
            showIcon
            title={`旁路观察（未影响对局，${request.passive_observations.length} 项）`}
            type="warning"
          />
          <Collapse
            items={[
              {
                children: (
                  <pre>{prettyJson(request.passive_observations)}</pre>
                ),
                key: "passive-observations",
                label: "查看旁路观察详情",
              },
            ]}
            size="small"
          />
        </>
      ) : null}
      <OutputSummary label="程序采用结果" value={adoptedValue} />
      {request.raw_response ? (
        <Collapse
          className="v2-raw-response-collapse"
          items={[
            {
              children: (
                <OutputSummary
                  compact
                  label="模型原始返回"
                  value={rawValue ?? request.raw_response}
                />
              ),
              key: "raw-response",
              label: rawMatchesAdopted
                ? "模型原始返回（与采用结果一致）"
                : "查看模型原始返回",
            },
          ]}
          size="small"
        />
      ) : null}
    </div>
  );
}

function numericField(
  value: Record<string, unknown> | null,
  key: string,
): number | null {
  const candidate = value?.[key];
  return typeof candidate === "number" && Number.isFinite(candidate)
    ? candidate
    : null;
}

export function ReadableRawEvents({
  events,
}: {
  events: V2GameRecordDetail["events"];
}) {
  return (
    <Collapse
      className="v2-raw-events"
      items={events.map((event) => ({
        children: <pre>{prettyJson(event.payload)}</pre>,
        key: String(event.event_id),
        label: (
          <Flex gap={8}>
            <Tag>#{event.record_seq}</Tag>
            <Typography.Text strong>{event.event_type}</Typography.Text>
            <Typography.Text type="secondary">
              {formatClock(event.created_at)}
            </Typography.Text>
          </Flex>
        ),
      }))}
      size="small"
    />
  );
}

function PromptMessageCard({ message }: { message: RequestMessage }) {
  const structured = parseStructuredPrompt(message.text);
  const isSystem = message.role.toLowerCase() === "system";
  return (
    <section
      className={
        isSystem
          ? "v2-prompt-message is-system"
          : "v2-prompt-message is-user"
      }
    >
      <Flex align="center" justify="space-between">
        <Space size={8}>
          <Tag color={isSystem ? "blue" : "purple"}>
            {isSystem ? "SYSTEM" : "USER"}
          </Tag>
          <Typography.Text strong>
            {isSystem ? "系统指令" : "动作输入"}
          </Typography.Text>
        </Space>
        <Typography.Text copyable={{ text: message.text }} type="secondary">
          复制原文
        </Typography.Text>
      </Flex>
      {structured ? (
        <>
          {structured.intro ? (
            <Typography.Paragraph className="v2-prompt-intro">
              {structured.intro}
            </Typography.Paragraph>
          ) : null}
          <ActionContext context={structured.value} />
        </>
      ) : (
        <Typography.Paragraph className="v2-readable-prose">
          {message.text}
        </Typography.Paragraph>
      )}
    </section>
  );
}

function ActionContext({
  context,
}: {
  context: Record<string, unknown>;
}) {
  const primaryKeys = new Set([
    "schema_version",
    "action_id",
    "action_type",
    "game_id",
    "run_id",
    "phase_id",
    "actor",
    "objective",
  ]);
  const descriptionItems = [
    context.phase_id !== undefined
      ? {
          key: "phase",
          label: "阶段",
          children: displayScalar(context.phase_id, "phase_id"),
        }
      : null,
    context.action_type !== undefined
      ? {
          key: "action",
          label: "动作",
          children: displayScalar(context.action_type, "action_type"),
        }
      : null,
    context.actor !== undefined
      ? {
          key: "actor",
          label: "执行者",
          children: displayActor(context.actor),
        }
      : null,
    context.action_id !== undefined
      ? {
          key: "action-id",
          label: "动作 ID",
          children: displayScalar(context.action_id, "action_id"),
        }
      : null,
    context.game_id !== undefined
      ? {
          key: "game-id",
          label: "对局 ID",
          children: displayScalar(context.game_id, "game_id"),
        }
      : null,
    context.run_id !== undefined
      ? {
          key: "run-id",
          label: "运行 ID",
          children: displayScalar(context.run_id, "run_id"),
        }
      : null,
  ].filter(Boolean) as Array<{
    key: string;
    label: string;
    children: ReactNode;
  }>;
  const groups = Object.entries(context).filter(
    ([key, value]) => !primaryKeys.has(key) && value !== undefined,
  );

  return (
    <div className="v2-action-context">
      {descriptionItems.length ? (
        <Descriptions
          column={2}
          items={descriptionItems}
          size="small"
        />
      ) : null}
      {typeof context.objective === "string" && context.objective ? (
        <section className="v2-objective-callout">
          <Typography.Text type="secondary">动作目标</Typography.Text>
          <Typography.Paragraph>{context.objective}</Typography.Paragraph>
        </section>
      ) : null}
      {groups.length ? (
        <div className="v2-readable-groups">
          {groups.map(([key, value]) => (
            <ReadableGroup key={key} label={fieldLabel(key)} value={value} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ReadableGroup({
  label,
  value,
}: {
  label: string;
  value: unknown;
}) {
  return (
    <section className="v2-readable-group">
      <Typography.Text className="v2-readable-group-title" strong>
        {label}
      </Typography.Text>
      <ReadableValue value={value} />
    </section>
  );
}

function ReadableValue({
  fieldKey,
  value,
}: {
  fieldKey?: string;
  value: unknown;
}) {
  if (Array.isArray(value)) {
    if (!value.length) {
      return <Typography.Text type="secondary">无</Typography.Text>;
    }
    if (value.every(isScalar)) {
      return (
        <Space size={[6, 6]} wrap>
          {value.map((item, index) => (
            <Tag key={`${String(item)}-${index}`}>
              {scalarText(item, fieldKey)}
            </Tag>
          ))}
        </Space>
      );
    }
    return (
      <div className="v2-readable-list">
        {value.map((item, index) => (
          <div className="v2-readable-list-item" key={index}>
            <Typography.Text type="secondary">
              {index + 1}
            </Typography.Text>
            <ReadableValue value={item} />
          </div>
        ))}
      </div>
    );
  }
  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (!entries.length) {
      return <Typography.Text type="secondary">无</Typography.Text>;
    }
    return (
      <div className="v2-readable-fields">
        {entries.map(([key, child]) => (
          <div
            className={
              isScalar(child)
                ? "v2-readable-field"
                : "v2-readable-field is-wide"
            }
            key={key}
          >
            <Typography.Text
              className="v2-readable-field-label"
              type="secondary"
            >
              {fieldLabel(key)}
            </Typography.Text>
            <ReadableValue fieldKey={key} value={child} />
          </div>
        ))}
      </div>
    );
  }
  return displayScalar(value, fieldKey);
}

function OutputSummary({
  compact = false,
  label,
  value,
}: {
  compact?: boolean;
  label: string;
  value: unknown;
}) {
  if (value === null || value === undefined) {
    return <Empty description="没有可展示的模型结果" />;
  }
  if (isRecord(value)) {
    const speech =
      typeof value.speech === "string" && value.speech.trim()
        ? value.speech.trim()
        : null;
    const target =
      typeof value.target_player_id === "string" &&
      value.target_player_id.trim()
        ? value.target_player_id.trim()
        : value.target_player_id === null
          ? null
          : undefined;
    const rest = Object.fromEntries(
      Object.entries(value).filter(
        ([key]) => key !== "speech" && key !== "target_player_id",
      ),
    );
    return (
      <section
        className={
          compact
            ? "v2-output-summary is-compact"
            : "v2-output-summary"
        }
      >
        <Typography.Text type="secondary">{label}</Typography.Text>
        {target !== undefined ? (
          <div className="v2-output-target">
            <Typography.Text type="secondary">目标玩家</Typography.Text>
            {target ? <Tag color="blue">{target}</Tag> : <Tag>未选择目标</Tag>}
          </div>
        ) : null}
        {speech ? (
          <div>
            <Typography.Text type="secondary">最终发言</Typography.Text>
            <Typography.Paragraph className="v2-output-speech">
              {speech}
            </Typography.Paragraph>
          </div>
        ) : null}
        {Object.keys(rest).length ? <ReadableValue value={rest} /> : null}
      </section>
    );
  }
  return (
    <section
      className={
        compact ? "v2-output-summary is-compact" : "v2-output-summary"
      }
    >
      <Typography.Text type="secondary">{label}</Typography.Text>
      <Typography.Paragraph className="v2-output-speech">
        {String(value)}
      </Typography.Paragraph>
    </section>
  );
}

function requestMessages(
  requestPayload: Record<string, unknown>,
): RequestMessage[] {
  const input = Array.isArray(requestPayload.input)
    ? requestPayload.input
    : [];
  const messages = Array.isArray(requestPayload.messages)
    ? requestPayload.messages
    : [];
  const items = input.length ? input : messages;
  return items.flatMap((item) => {
    if (!isRecord(item)) return [];
    const role =
      typeof item.role === "string" && item.role ? item.role : "message";
    const text =
      typeof item.content === "string"
        ? item.content
        : Array.isArray(item.content)
          ? item.content
              .map((part) =>
                typeof part === "string"
                  ? part
                  : isRecord(part) && typeof part.text === "string"
                    ? part.text
                    : "",
              )
              .filter(Boolean)
              .join("\n")
          : "";
    return text ? [{ role, text }] : [];
  });
}

function parseStructuredPrompt(text: string): StructuredPrompt | null {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    const value = JSON.parse(text.slice(start, end + 1));
    if (!isRecord(value)) return null;
    return {
      intro: text.slice(0, start).replace(/[：:\s]+$/u, "") || null,
      value,
    };
  } catch {
    return null;
  }
}

function parseJsonValue(raw: string | null): unknown {
  if (!raw) return null;
  const normalized = raw
    .trim()
    .replace(/^```(?:json)?\s*/u, "")
    .replace(/\s*```$/u, "");
  const candidates = [normalized];
  const start = normalized.indexOf("{");
  const end = normalized.lastIndexOf("}");
  if (start >= 0 && end > start) {
    candidates.push(normalized.slice(start, end + 1));
  }
  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate);
    } catch {
      continue;
    }
  }
  return null;
}

function outputsMatch(
  raw: string | null,
  rawValue: unknown,
  parsed: Record<string, unknown> | null,
) {
  if (!raw || !parsed) return false;
  if (
    typeof parsed.speech === "string" &&
    raw.trim() === parsed.speech.trim()
  ) {
    return true;
  }
  return rawValue !== null && prettyJson(rawValue) === prettyJson(parsed);
}

function displayActor(value: unknown): ReactNode {
  if (!isRecord(value)) return displayScalar(value, "actor");
  const kind = typeof value.kind === "string" ? value.kind : null;
  const id = typeof value.id === "string" ? value.id : null;
  return (
    <Space size={6} wrap>
      {kind ? <Tag>{valueLabels[kind] ?? kind}</Tag> : null}
      {id ? <Typography.Text copyable>{id}</Typography.Text> : null}
    </Space>
  );
}

function displayScalar(value: unknown, fieldKey?: string): ReactNode {
  if (value === null || value === undefined || value === "") {
    return <Typography.Text type="secondary">无</Typography.Text>;
  }
  if (typeof value === "boolean") {
    return <Tag color={value ? "success" : "default"}>{value ? "是" : "否"}</Tag>;
  }
  if (typeof value === "number") {
    return <Typography.Text>{String(value)}</Typography.Text>;
  }
  const text = String(value);
  if (fieldKey === "phase_id") {
    return <Typography.Text>{phaseLabel(text)}</Typography.Text>;
  }
  if (fieldKey === "action_type") {
    return <Typography.Text>{actionLabel(text)}</Typography.Text>;
  }
  if (fieldKey?.endsWith("_id") || fieldKey?.endsWith("_sha256")) {
    return <Typography.Text copyable code>{text}</Typography.Text>;
  }
  if (
    fieldKey === "status" ||
    fieldKey === "mode" ||
    fieldKey === "kind" ||
    fieldKey === "audience"
  ) {
    return <Tag>{valueLabels[text] ?? humanize(text)}</Tag>;
  }
  return <Typography.Text>{valueLabels[text] ?? text}</Typography.Text>;
}

function scalarText(value: unknown, fieldKey?: string) {
  if (value === null || value === undefined) return "无";
  if (typeof value === "boolean") return value ? "是" : "否";
  const text = String(value);
  if (fieldKey === "phase_id") return phaseLabel(text);
  if (fieldKey === "action_type") return actionLabel(text);
  return valueLabels[text] ?? text;
}

function fieldLabel(key: string) {
  return fieldLabels[key] ?? humanize(key);
}

function humanize(value: string) {
  return value.replaceAll("_", " ");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isScalar(value: unknown) {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}
