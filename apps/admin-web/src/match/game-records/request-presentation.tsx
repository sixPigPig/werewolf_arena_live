import { CheckOutlined, CopyOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import Alert from "antd/es/alert";
import Button from "antd/es/button";
import Collapse from "antd/es/collapse";
import Descriptions from "antd/es/descriptions";
import Empty from "antd/es/empty";
import Flex from "antd/es/flex";
import Space from "antd/es/space";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { useState, type ReactNode } from "react";

import { isAdminApiError } from "@/api/problem-details";
import { readV2GameEvent } from "@/v2/game-records/api";
import {
  classifyV2ModelContextContract,
  structuredModelContextFromRequestPayload,
} from "@/v2/game-records/model-context-contract";
import {
  actionLabel,
  formatClock,
  phaseLabel,
  prettyJson,
} from "@/v2/game-records/presentation";
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";
import type {
  V2GameRecordEvent,
  V2MemorySelectorAudit,
  V2ModelRequest,
  V2PromptProjection,
} from "@/v2/game-records/types";

type RequestMessage = {
  role: string;
  text: string;
};

type StructuredPrompt = {
  intro: string | null;
  value: Record<string, unknown>;
};

type KnownEventsSummary = {
  recordSeqMax: number | null;
  recordSeqMin: number | null;
  schemaVersion: number | null;
  selectedCount: number;
};

const fieldLabels: Record<string, string> = {
  ability_id: "能力",
  ability_instance_id: "能力实例 ID",
  activation_id: "激活 ID",
  action_id: "动作 ID",
  action_type: "动作类型",
  address_resolution: "寻址结果",
  addressed_to: "提问对象",
  answer_record_seq: "回答记录序号",
  answer_source_event_id: "回答来源事件",
  answer_turn_index: "回答发言序号",
  actor: "执行者",
  actor_id: "玩家 ID",
  actor_kind: "执行者类型",
  actor_profile: "角色画像",
  at_seq: "动作发生序号",
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
  consensus_rule: "共识规则",
  context: "补充上下文",
  confirmation_status: "确认状态",
  current_round_no: "当前轮次",
  current_round_statement_char_count: "本轮原文字符数",
  current_round_statement_count: "本轮原文数",
  data: "事件数据",
  decision_note: "当时声明的简短理由",
  timeline: "完整公开发言时间线",
  decision_rules: "决策约束",
  dead_player_ids: "出局玩家",
  display_name: "玩家名称",
  event_type: "事件类型",
  events: "公开事件",
  event_ref: "事件引用",
  exact_quote: "原话",
  facts: "已知事实",
  game_id: "对局 ID",
  game_setup: "对局配置",
  goal: "动作目标",
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
  state: "动作发生时公开状态",
  public_timeline: "统一公开时间线",
  public_history: "公开历史",
  hard_rules: "硬规则",
  rules: "本动作相关规则",
  history: "公开发言历史",
  ledger_schema_version: "发言账本版本",
  model_view_schema_version: "模型视图版本",
  model_context_schema_version: "模型上下文版本",
  prompt_template_version: "提示词模板版本",
  known_events_schema_version: "已知事件版本",
  model_view_selector_version: "模型视图选择器版本",
  known_events: "动作发生前已知事件",
  selector: "真人记忆选择审计",
  source_count: "全源事件数",
  retained_count: "选择器保留数",
  omitted_count: "选择器省略数",
  future_filtered_count: "未来事件过滤数",
  category: "选择分类",
  latest_actor_memory_ref: "最近角色记忆引用",
  latest_actor_memory_cutoff_seq: "最近角色记忆截止序号",
  latest_actor_memory_hash: "最近角色记忆 SHA-256",
  source_type_counts: "全源类型计数",
  retained_type_counts: "保留类型计数",
  omitted_type_counts: "省略类型计数",
  lossless_scope: "无损声明范围",
  known_at_seq: "获知时记录序号",
  known_event_count: "模型已选事件数",
  known_event_total_count: "完整已知事件数",
  dropped_event_count: "未送入模型事件数",
  known_event_record_seq_min: "最早已知记录序号",
  known_event_record_seq_max: "最晚已知记录序号",
  retained_event_refs: "保留事件引用",
  dropped_event_refs: "未送入模型事件引用",
  retention_reasons: "事件保留原因",
  selection_budget_chars: "事件选择字符预算",
  selection_used_chars: "已选事件字符数",
  selection_budget_exceeded_by_required: "必保事件超出预算",
  section_char_counts: "各输入区块字符数",
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
  source_event_count: "源事件数",
  emitted_event_count: "模型可见事件数",
  future_filtered_event_count: "未来事件过滤数",
  source_claim_candidate_count: "声明候选数",
  emitted_claim_count: "模型可见声明数",
  out_of_scope_claim_count: "作用域外声明数",
  rejected_claim_count: "被拒绝声明数",
  source_question_count: "源提问数",
  current_scope_question_count: "当前作用域提问数",
  emitted_question_count: "模型可见提问数",
  out_of_scope_question_count: "作用域外提问数",
  invalid_question_count: "无效提问数",
  source_relation_count: "源回应关系数",
  emitted_relation_count: "模型可见回应关系数",
  invalid_relation_count: "无效回应关系数",
  budget_dropped_event_count: "容量选择丢弃事件数",
  derivation_rejections: "派生项拒绝明细",
  derivation: "派生校验",
  missing_fields: "缺失字段",
  reason: "原因",
  requested_fields: "请求字段",
  response_status: "回应检测状态",
  source_authority: "源内容权威性",
  source_event_ref: "源事件引用",
  validation_status: "校验状态",
  validator_version: "校验器版本",
  selection_profile: "模型视图选择规则",
  focus: "当前动作引用焦点",
  annotations: "发言结构化注释",
  claim_id: "声明 ID",
  claim_type: "声明类型",
  claimed_action_in: "声明的行动时间",
  claimed_role: "声明的角色",
  claimed_result: "声明的结果",
  claimed_team: "声明的阵营",
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
  response: "输出要求",
  self_heal_allowed: "允许自救",
  seat: "座位",
  signals: "信号",
  speech: "发言内容",
  stage: "阶段",
  status: "状态",
  speaker_ref: "发言者",
  authority: "事实权威性",
  strategy_profile: "策略类型",
  visibility: "可见范围",
  self: "玩家自身与私有事实",
  strength: "影响强度",
  target_optional: "目标可为空",
  task: "当前动作",
  target_player_id: "目标玩家",
  target_ref: "目标玩家",
  voter_ref: "投票玩家",
  target_policy: "目标规则",
  thinking: "思考模式",
  tts_speaker: "语音角色",
  type: "类型",
  player_reference_format: "玩家引用格式",
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
  day_vote: "白天投票",
  day_speech_committed: "白天发言已提交",
  disabled: "未启用",
  god_view: "上帝视角",
  hunter_response: "猎人响应",
  judge: "法官",
  judge_fact: "法官确认事实",
  night_result: "夜间结果",
  none: "无需选择",
  optional: "可选",
  player: "玩家",
  player_claim_unverified: "玩家声明（未验证）",
  player_eliminated: "玩家出局",
  player_statement: "玩家发言",
  private: "私密",
  actor_private: "仅当前玩家可见",
  public: "公开",
  public_speech: "公开发言",
  required: "必须选择",
  role_revealed: "身份公开",
  sheriff_campaign: "警长竞选",
  sheriff_vote: "警长投票",
  speech: "发言",
  vote_result: "投票结果",
  complete: "校验完整",
  deterministic_heuristic: "确定性启发式",
  none_detected: "未检测到回应",
  response_detected: "检测到回应",
  response_to_question: "对提问的回应",
  resolved: "已明确寻址",
  unresolved: "未明确寻址",
  role_claim: "角色声明",
  team_claim: "阵营声明",
  investigation_claim: "验人声明",
  future_investigation_plan: "未来验人计划",
};

export function ReadableModelInput({
  request,
}: {
  request: V2ModelRequest | null;
}) {
  if (!request?.request_payload) {
    return <Empty description="这一步没有模型输入" />;
  }
  const promptContext = structuredModelContextFromRequestPayload(
    request.request_payload,
  );
  const presentationKind = classifyV2ModelContextContract(
    request,
    promptContext,
  );
  if (presentationKind === "unsupported") {
    return <HistoricalRawModelInput request={request} />;
  }
  const messages = requestMessages(request.request_payload);
  const knownEventsValue =
    promptContext && isRecord(promptContext.known_events)
      ? promptContext.known_events
      : null;
  const knownEvents = summarizeKnownEvents(
    request.prompt_projection,
    knownEventsValue,
  );
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
  const hasSectionCharCounts =
    request.prompt_projection?.section_char_counts !== undefined;
  return (
    <div className="v2-inspector-panel">
      <div className="v2-inspector-actions">
        <JsonCopyButton
          label="复制完整输入 JSON"
          value={request.request_payload}
        />
      </div>
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
            label: "提示词结构版本",
            children:
              request.prompt_schema_version === null
                ? "—"
                : `V${request.prompt_schema_version}`,
          },
          {
            key: "model-context-schema",
            label: "模型上下文",
            children:
              request.model_context_schema_version === null
                ? "—"
                : `V${request.model_context_schema_version}`,
          },
          {
            key: "prompt-template",
            label: "提示词模板",
            children:
              request.prompt_template_version === null
                ? "—"
                : `V${request.prompt_template_version}`,
          },
          {
            key: "model-view-selector",
            label: "事件选择器",
            children:
              request.model_view_selector_version === null
                ? "—"
                : `V${request.model_view_selector_version}`,
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
            span: 2,
            children:
              modelViewSchemaVersion === null
                ? "—"
                : `V${modelViewSchemaVersion}`,
          },
          ...(knownEvents
            ? [
                {
                  key: "known-events",
                  label: "动作前已知事件",
                  children: (
                    <Space size={6} wrap>
                      {knownEvents.schemaVersion === null ? null : (
                        <Tag>V{knownEvents.schemaVersion}</Tag>
                      )}
                      <Typography.Text>
                        模型实际可见 {knownEvents.selectedCount} 个
                      </Typography.Text>
                    </Space>
                  ),
                },
                {
                  key: "known-events-range",
                  label: "已知事件序号范围",
                  children: recordSeqRange(knownEvents),
                },
              ]
            : []),
        ]}
        size="small"
      />
      <V13MemoryAudit
        expandedKnownEvents={request.expanded_known_events}
        expansionStatus={request.known_events_expansion_status}
        knownEvents={knownEventsValue}
        projection={request.prompt_projection}
      />
      {knownEvents && request.prompt_projection && hasSectionCharCounts ? (
        <Collapse
          items={[
            {
              children: (
                <ReadableValue
                  value={
                    {
                      section_char_counts:
                        request.prompt_projection.section_char_counts ?? {},
                    }
                  }
                />
              ),
              key: "known-event-selection-audit",
              label: "查看上下文结构统计",
            },
          ]}
          size="small"
        />
      ) : null}
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
  if (classifyV2ModelContextContract(request) === "unsupported") {
    return <HistoricalRawModelOutput request={request} />;
  }
  if (request.output_source === "unavailable") {
    return (
      <div className="v2-inspector-panel">
        <LiveModelStream request={request} />
        <ModelOutputDiagnostics request={request} />
        <OutputEnforcementAudit request={request} />
        <Empty
          description={
            request.status === "running"
              ? "模型正在推理，最终输出尚未返回"
              : "模型尚未返回，或没有可恢复的输出"
          }
        />
      </div>
    );
  }

  const rawValue = parseJsonValue(request.raw_response);
  const rawMatchesAdopted = outputsMatch(
    request.raw_response,
    rawValue,
    request.parsed_output,
  );

  return (
    <div className="v2-inspector-panel">
      <div className="v2-inspector-actions">
        <JsonCopyButton
          label="复制完整输出 JSON"
          value={{
            application_validation_result:
              request.application_validation_result ?? null,
            finish_reason: request.finish_reason,
            output_enforcement: request.output_enforcement ?? null,
            provider_usage: request.provider_usage,
            raw_response: request.raw_response,
            parsed_output: request.parsed_output,
            repair_kind: request.repair_kind ?? null,
            usage_conflict_observed: request.usage_conflict_observed,
            usage_consistency: request.usage_consistency,
            usage_update_count: request.usage_update_count,
          }}
        />
      </div>
      {request.output_source === "legacy_inferred" ? (
        <Alert
          description="该历史请求没有保存供应商原始响应；下方结果来自已提交的展示文本。"
          showIcon
          title="原始输出不可用"
          type="warning"
        />
      ) : null}
      <LiveModelStream request={request} />
      <ModelOutputDiagnostics request={request} />
      <OutputEnforcementAudit request={request} />
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
      {request.application_validation_result === "accepted" ? (
        <OutputSummary label="程序采用结果" value={request.parsed_output} />
      ) : request.application_validation_result === "rejected" ? (
        <Empty description="应用层校验已拒绝该输出，没有最终采用结果" />
      ) : (
        <>
          <Alert
            description="应用层校验结果未记录，Admin 不把原始响应或解析结果推断为最终采用结果。"
            showIcon
            title="最终采用状态未知"
            type="warning"
          />
          {request.parsed_output ? (
            <OutputSummary
              label="程序解析结果（采用状态未知）"
              value={request.parsed_output}
            />
          ) : null}
        </>
      )}
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

export function ModelOutputDiagnostics({
  request,
}: {
  request: V2ModelRequest;
}) {
  const usage = request.provider_usage;
  const unavailable = "unavailable（Provider 未返回）";
  const tokenCount = (value: number | undefined) =>
    value === undefined ? unavailable : value.toLocaleString("zh-CN");
  const outputCharacterCount =
    request.raw_response === null
      ? unavailable
      : Array.from(request.raw_response).length.toLocaleString("zh-CN");
  return (
    <section aria-label="模型输出与用量诊断">
      <Typography.Text strong>模型输出与用量诊断</Typography.Text>
      <Descriptions
        column={2}
        items={[
          {
            key: "finish-reason",
            label: "结束原因",
            children: finishReasonLabel(request.finish_reason),
          },
          {
            key: "output-characters",
            label: "原始输出字符数",
            children: outputCharacterCount,
          },
          {
            key: "input-tokens",
            label: "输入 Token",
            children: usage ? tokenCount(usage.input_tokens) : unavailable,
          },
          {
            key: "output-tokens",
            label: "输出 Token",
            children: usage ? tokenCount(usage.output_tokens) : unavailable,
          },
          {
            key: "reasoning-tokens",
            label: "推理 Token（输出子集）",
            children: usage ? tokenCount(usage.reasoning_tokens) : unavailable,
          },
          {
            key: "total-tokens",
            label: "Provider 总 Token",
            children: usage ? tokenCount(usage.total_tokens) : unavailable,
          },
          {
            key: "cached-input-tokens",
            label: "缓存输入 Token",
            children: usage
              ? tokenCount(usage.cached_input_tokens)
              : unavailable,
          },
          {
            key: "usage-snapshots",
            label: "合法 usage 快照",
            children:
              request.usage_update_count === null
                ? unavailable
                : String(request.usage_update_count),
          },
          {
            key: "usage-consistency",
            label: "Token 一致性",
            children: usageConsistencyLabel(request.usage_consistency),
          },
          {
            key: "usage-conflict",
            label: "usage 快照冲突",
            children:
              request.usage_conflict_observed === null
                ? "—"
                : request.usage_conflict_observed
                  ? "是"
                  : "否",
          },
        ]}
        size="small"
      />
    </section>
  );
}

function LiveModelStream({ request }: { request: V2ModelRequest }) {
  const hasReasoning = Boolean(request.stream_reasoning);
  const hasText = Boolean(request.stream_text);
  if (!hasReasoning && request.status !== "running") return null;

  const usage = request.provider_usage;
  const usesEstimatedTokens =
    usage?.output_tokens === undefined || usage.reasoning_tokens === undefined;
  const tokenValue = (providerValue: number | undefined, estimate: number | null) =>
    providerValue === undefined
      ? estimate === null
        ? "等待首个片段"
        : `≈ ${estimate.toLocaleString("zh-CN")}（实时估算）`
      : `${providerValue.toLocaleString("zh-CN")}（Provider）`;
  return (
    <section aria-label="实时推理与 Token" className="v2-model-stream">
      <Flex align="center" gap={8} justify="space-between" wrap>
        <Typography.Text strong>
          {request.status === "running" ? "实时推理" : "推理内容（流式留存）"}
        </Typography.Text>
        <Space size={6} wrap>
          <Tag color={request.status === "running" ? "processing" : "default"}>
            {request.status === "running" ? "生成中 · 约每秒刷新" : "已结束"}
          </Tag>
          {request.stream_progress_updated_at ? (
            <Typography.Text type="secondary">
              更新于 {formatClock(request.stream_progress_updated_at)}
            </Typography.Text>
          ) : null}
        </Space>
      </Flex>
      <Descriptions
        column={2}
        items={[
          {
            key: "live-output-tokens",
            label: "当前输出 Token",
            children: tokenValue(
              usage?.output_tokens,
              request.stream_estimated_output_tokens,
            ),
          },
          {
            key: "live-reasoning-tokens",
            label: "当前推理 Token",
            children: tokenValue(
              usage?.reasoning_tokens,
              request.stream_estimated_reasoning_tokens,
            ),
          },
        ]}
        size="small"
      />
      {usesEstimatedTokens ? (
        <Alert
          description="生成中的数字按已收到文本做本地估算，不作为计费或最终诊断依据；Provider 返回 usage 后会自动切换为其原始值。"
          showIcon
          type="info"
        />
      ) : null}
      <div className="v2-model-stream-block">
        <Typography.Text strong>推理内容</Typography.Text>
        <pre aria-label="模型实时推理内容">
          {request.stream_reasoning ??
            "尚未收到可展示的推理片段（Provider 可能不返回推理内容）。"}
        </pre>
      </div>
      {hasText && request.status === "running" ? (
        <div className="v2-model-stream-block">
          <Typography.Text strong>正在生成的输出</Typography.Text>
          <pre aria-label="模型实时输出内容">{request.stream_text}</pre>
        </div>
      ) : null}
      {request.stream_content_truncated ? (
        <Alert
          description="该次流式内容超过 Admin 展示上限，这里只显示前 200,000 个字符；字符计数和最终 Provider usage 仍保留原值。"
          showIcon
          type="warning"
        />
      ) : null}
    </section>
  );
}

function HistoricalRawModelInput({ request }: { request: V2ModelRequest }) {
  const contractVersion =
    request.model_context_schema_version === null
      ? "版本未知"
      : `V${request.model_context_schema_version}`;
  return (
    <div className="v2-inspector-panel">
      <div className="v2-inspector-actions">
        <JsonCopyButton
          label="复制完整输入 JSON"
          value={request.request_payload}
        />
      </div>
      <Alert
        description={
          request.input_source === "reconstructed"
            ? `${contractVersion} 模型上下文合同不受支持；这份输入由历史动作上下文重建，并非逐字原始请求。`
            : `${contractVersion} 模型上下文合同不受支持；Admin 不推断其结构或语义，以下仅展示持久化 JSON。`
        }
        showIcon
        title="历史或未知合同仅提供通用 JSON"
        type="warning"
      />
      <pre aria-label="历史模型输入原始 JSON">
        {prettyJson(request.request_payload)}
      </pre>
    </div>
  );
}

function HistoricalRawModelOutput({ request }: { request: V2ModelRequest }) {
  const value = {
    application_validation_result:
      request.application_validation_result ?? null,
    finish_reason: request.finish_reason,
    output_enforcement: request.output_enforcement ?? null,
    output_source: request.output_source,
    parsed_output: request.parsed_output,
    passive_observations: request.passive_observations,
    provider_usage: request.provider_usage,
    raw_response: request.raw_response,
    repair_kind: request.repair_kind ?? null,
    usage_conflict_observed: request.usage_conflict_observed,
    usage_consistency: request.usage_consistency,
    usage_update_count: request.usage_update_count,
  };
  return (
    <div className="v2-inspector-panel">
      <div className="v2-inspector-actions">
        <JsonCopyButton label="复制完整输出 JSON" value={value} />
      </div>
      <Alert
        description={`${
          request.model_context_schema_version === null
            ? "版本未知"
            : `V${request.model_context_schema_version}`
        } 模型上下文合同不受支持；Admin 不推断其采用语义、输出约束或修复阶段，以下仅展示保存的数据。`}
        showIcon
        title="历史或未知合同仅提供通用 JSON"
        type="warning"
      />
      <LiveModelStream request={request} />
      <ModelOutputDiagnostics request={request} />
      <pre aria-label="历史模型输出原始 JSON">{prettyJson(value)}</pre>
    </div>
  );
}

function finishReasonLabel(reason: V2ModelRequest["finish_reason"]) {
  const labels: Record<NonNullable<V2ModelRequest["finish_reason"]>, string> = {
    completed: "Provider 完成（completed）",
    stop: "正常停止（stop）",
    length: "长度上限（length）",
    max_output_tokens: "输出 Token 上限（max_output_tokens）",
    content_filter: "内容过滤（content_filter）",
    tool_calls: "工具调用（tool_calls）",
    unknown: "未知（unknown）",
  };
  return reason === null ? "—" : labels[reason];
}

function usageConsistencyLabel(
  consistency: V2ModelRequest["usage_consistency"],
) {
  if (consistency === null) return "—";
  if (consistency === "exact") return "完整一致（exact）";
  if (consistency === "provider_total_mismatch") {
    return "Provider 总数不一致（保留原值）";
  }
  return "无法判断（unavailable）";
}

function V13MemoryAudit({
  expandedKnownEvents,
  expansionStatus,
  knownEvents,
  projection,
}: {
  expandedKnownEvents: Record<string, unknown> | null;
  expansionStatus: V2ModelRequest["known_events_expansion_status"];
  knownEvents: Record<string, unknown> | null;
  projection: V2PromptProjection | null;
}) {
  const selector = projection?.selector ?? null;

  return (
    <section aria-label="V13 真人记忆投影审计">
      <Flex align="center" justify="space-between" wrap>
        <Typography.Text strong>V13 真人记忆投影审计</Typography.Text>
        <Tag color={selector ? "success" : "warning"}>
          {selector ? "选择审计完整" : "选择审计缺失"}
        </Tag>
      </Flex>
      {!selector ? (
        <Alert
          description="Admin 不从 Compact 载荷反推全源候选、选择原因或最近记忆；缺少 selector 时只能按原始 JSON 审计。"
          showIcon
          title="V13 选择器审计信息缺失"
          type="warning"
        />
      ) : null}
      <Descriptions
        column={2}
        items={[
          {
            key: "selector-flow",
            label: "全源 → 本次模型输入",
            children: selector ? (
              <Space size={[6, 6]} wrap>
                <Tag>源 {selector.source_count}</Tag>
                <Tag color="success">保留 {selector.retained_count}</Tag>
                <Tag color="warning">选择器省略 {selector.omitted_count}</Tag>
                <Tag>未来过滤 {selector.future_filtered_count}</Tag>
              </Space>
            ) : (
              "未知"
            ),
          },
          {
            key: "selector-version",
            label: "真人记忆选择器",
            children: selector ? `V${selector.version}` : "未知",
          },
          {
            key: "latest-memory-ref",
            label: "最近角色记忆引用",
            children: selector?.latest_actor_memory_ref ?? "无",
          },
          {
            key: "latest-memory-cutoff",
            label: "最近角色记忆截止序号",
            children:
              selector?.latest_actor_memory_cutoff_seq === null ||
              selector?.latest_actor_memory_cutoff_seq === undefined
                ? "无"
                : `#${selector.latest_actor_memory_cutoff_seq}`,
          },
          {
            key: "latest-memory-hash",
            label: "最近角色记忆 SHA-256",
            span: 2,
            children: selector?.latest_actor_memory_hash ?? "无",
          },
        ]}
        size="small"
      />
      {selector ? (
        <Collapse
          items={[
            {
              children: (
                <div className="v2-readable-groups">
                  <SelectorAuditEntries
                    entries={selector.retained}
                    emptyDescription="本次没有保留事件"
                    label="保留（retained）"
                  />
                  <SelectorAuditEntries
                    entries={selector.omitted}
                    emptyDescription="本次没有被选择器省略的事件"
                    label="选择器省略（selector_omitted）"
                  />
                  <SelectorAuditEntries
                    entries={selector.future_filtered}
                    emptyDescription="本次没有未来事件"
                    label="未来过滤（future_filtered）"
                  />
                </div>
              ),
              key: "v13-selector-decisions",
              label: `查看选择分类与原因（${selector.source_count} 项）`,
            },
            {
              children: (
                <div className="v2-readable-groups">
                  <ReadableGroup
                    label="全源类型计数"
                    value={selector.source_type_counts}
                  />
                  <ReadableGroup
                    label="保留类型计数"
                    value={selector.retained_type_counts}
                  />
                  <ReadableGroup
                    label="省略类型计数"
                    value={selector.omitted_type_counts}
                  />
                </div>
              ),
              key: "v13-selector-type-counts",
              label: "查看来源类型计数",
            },
          ]}
          size="small"
        />
      ) : null}
      <V7CompactionAudit
        expandedKnownEvents={expandedKnownEvents}
        expansionStatus={expansionStatus}
        knownEvents={knownEvents}
        projection={projection}
      />
    </section>
  );
}

function SelectorAuditEntries({
  emptyDescription,
  entries,
  label,
}: {
  emptyDescription: string;
  entries: Array<
    V2MemorySelectorAudit["retained"][number] | { event_ref: string; reason: string }
  >;
  label: string;
}) {
  return (
    <ReadableGroup
      label={`${label}（${entries.length}）`}
      value={entries.length ? entries : emptyDescription}
    />
  );
}

const v7CompactionAuditFields = [
  "canonical_serialized_char_count",
  "compact_serialized_char_count",
  "compaction_saved_chars",
  "compaction_ratio",
  "verbatim_speech_count",
  "verbatim_speech_chars",
  "retained_event_refs",
  "canonical_sha256",
  "round_trip_verified",
  "lossless_scope",
] as const;

function V7CompactionAudit({
  expandedKnownEvents,
  expansionStatus,
  knownEvents,
  projection,
}: {
  expandedKnownEvents: Record<string, unknown> | null;
  expansionStatus: V2ModelRequest["known_events_expansion_status"];
  knownEvents: Record<string, unknown> | null;
  projection: V2PromptProjection | null;
}) {
  const missingFields = v7CompactionAuditFields.filter(
    (key) =>
      projection === null ||
      !Object.prototype.hasOwnProperty.call(projection, key),
  );
  const schemaVersion = integerNumber(knownEvents?.schema_version);
  const encoding =
    typeof knownEvents?.encoding === "string" ? knownEvents.encoding : null;
  const compactContractSupported =
    schemaVersion === 7 && encoding === "lossless_refs_v1";
  const scopeCatalog = isRecord(knownEvents?.scope_catalog)
    ? knownEvents.scope_catalog
    : null;
  const occurrenceCatalog = isRecord(knownEvents?.occurrence_catalog)
    ? knownEvents.occurrence_catalog
    : null;
  const defaults = isRecord(knownEvents?.defaults)
    ? knownEvents.defaults
    : null;
  const canonicalChars = numericField(
    projection,
    "canonical_serialized_char_count",
  );
  const compactChars = numericField(
    projection,
    "compact_serialized_char_count",
  );
  const savedChars = numericField(projection, "compaction_saved_chars");
  const ratio = numericField(projection, "compaction_ratio");
  const speechCount = numericField(projection, "verbatim_speech_count");
  const speechChars = numericField(projection, "verbatim_speech_chars");
  const retainedRefs = Array.isArray(projection?.retained_event_refs)
    ? projection.retained_event_refs.filter(
        (value): value is string => typeof value === "string",
      )
    : null;
  const canonicalHash =
    typeof projection?.canonical_sha256 === "string"
      ? projection.canonical_sha256
      : null;
  const roundTripVerified =
    typeof projection?.round_trip_verified === "boolean"
      ? projection.round_trip_verified
      : null;
  const losslessScope =
    projection?.lossless_scope === "selector_retained_projection"
      ? projection.lossless_scope
      : null;
  const auditComplete =
    compactContractSupported && missingFields.length === 0;

  return (
    <section aria-label="V7 入选集无损编码审计">
      <Flex align="center" justify="space-between" wrap>
        <Typography.Text strong>V7 入选集无损编码审计</Typography.Text>
        <Tag color={auditComplete ? "success" : "warning"}>
          {auditComplete ? "审计字段完整" : "审计字段不完整"}
        </Tag>
      </Flex>
      {!auditComplete ? (
        <Alert
          description="未记录项统一显示为未知；Admin 不根据请求体反推 Canonical 长度、压缩收益、事件保留或回环校验结果。"
          showIcon
          title="V7 编码审计信息缺失"
          type="warning"
        />
      ) : null}
      {roundTripVerified === false ? (
        <Alert
          description="持久化审计明确记录 round_trip_verified=false；该请求仍按原始 JSON 展示，不能视为通过无损校验。"
          showIcon
          title="V7 入选集无损回环校验失败"
          type="error"
        />
      ) : null}
      <Descriptions
        column={2}
        items={[
          {
            key: "compact-contract",
            label: "Known Events 压缩合同",
            children: (
              <Space size={6} wrap>
                <Tag color={schemaVersion === 7 ? "blue" : "warning"}>
                  {schemaVersion === null ? "版本未知" : `V${schemaVersion}`}
                </Tag>
                <Typography.Text>
                  {encoding ?? "encoding 未记录"}
                </Typography.Text>
              </Space>
            ),
          },
          {
            key: "catalog-size",
            label: "可读目录规模",
            children: `scope ${scopeCatalog ? Object.keys(scopeCatalog).length : "未知"} / occurrence ${
              occurrenceCatalog ? Object.keys(occurrenceCatalog).length : "未知"
            }`,
          },
          {
            key: "backend-expansion",
            label: "后端 Canonical 展开",
            children:
              expansionStatus === "verified" ? (
                <Tag color="success">
                  已验证 V
                  {integerNumber(expandedKnownEvents?.schema_version) ?? "?"} ·{" "}
                  {Array.isArray(expandedKnownEvents?.events)
                    ? expandedKnownEvents.events.length
                    : 0}{" "}
                  个事件
                </Tag>
              ) : expansionStatus === "not_applicable" ? (
                <Tag>不适用</Tag>
              ) : expansionStatus === "invalid" ? (
                <Tag color="error">无效，禁止展开</Tag>
              ) : (
                <Tag color="warning">不可用，禁止推断</Tag>
              ),
          },
          {
            key: "serialized-characters",
            label: "Canonical → Compact 字符数",
            children: `${auditNumber(canonicalChars)} → ${auditNumber(
              compactChars,
            )}`,
          },
          {
            key: "saved-characters",
            label: "节省字符",
            children: auditNumber(savedChars),
          },
          {
            key: "compaction-ratio",
            label: "Compact / Canonical 比率",
            children:
              ratio === null
                ? "未知"
                : `${ratio.toFixed(4)}（${(ratio * 100).toFixed(2)}%）`,
          },
          {
            key: "verbatim-speech",
            label: "逐字发言保留",
            children: `${auditNumber(speechCount)} 条 / ${auditNumber(
              speechChars,
            )} 字符`,
          },
          {
            key: "round-trip",
            label: "Canonical 回环校验",
            children:
              roundTripVerified === null ? (
                "未知"
              ) : roundTripVerified ? (
                <Tag color="success">通过</Tag>
              ) : (
                <Tag color="error">失败</Tag>
              ),
          },
          {
            key: "event-refs",
            label: "入选后编码引用",
            children: `${retainedRefs?.length ?? "未知"}`,
          },
          {
            key: "lossless-scope",
            label: "无损声明范围",
            children: losslessScope ?? "未知",
          },
          {
            key: "canonical-hash",
            label: "Canonical SHA-256",
            children: canonicalHash ?? "未知",
          },
        ]}
        size="small"
      />
      <Collapse
        items={[
          {
            children: (
              <div className="v2-readable-groups">
                <ReadableGroup
                  label="V7 默认还原规则"
                  value={defaults ?? "未记录"}
                />
                <ReadableGroup
                  label="作用域目录（scope_catalog）"
                  value={scopeCatalog ?? "未记录"}
                />
                <ReadableGroup
                  label="发生阶段目录（occurrence_catalog）"
                  value={occurrenceCatalog ?? "未记录"}
                />
              </div>
            ),
            key: "v7-compaction-contract",
            label: "查看 V7 默认规则与可读目录",
          },
          {
            children: (
              <div className="v2-readable-groups">
                <ReadableGroup
                  label="入选后由编码保留的引用"
                  value={retainedRefs ?? "未记录"}
                />
              </div>
            ),
            key: "v7-event-refs",
            label: "查看编码层引用（不含选择器省略）",
          },
        ]}
        size="small"
      />
    </section>
  );
}

function auditNumber(value: number | null) {
  return value === null ? "未知" : value.toLocaleString("zh-CN");
}

function OutputEnforcementAudit({
  request,
}: {
  request: V2ModelRequest;
}) {
  const enforcement = request.output_enforcement;
  const enforcementMissing =
    enforcement === undefined ||
    enforcement === null ||
    enforcement.requested === null ||
    enforcement.actual === null;
  const validationRecorded = Object.prototype.hasOwnProperty.call(
    request,
    "application_validation_result",
  );
  const repairRecorded = Object.prototype.hasOwnProperty.call(
    request,
    "repair_kind",
  );
  return (
    <section aria-label="Provider 输出约束审计">
      <Flex align="center" justify="space-between" wrap>
        <Typography.Text strong>Provider 输出约束审计</Typography.Text>
        <Tag color={enforcementMissing ? "warning" : "success"}>
          {enforcementMissing ? "约束状态未知" : "约束状态已记录"}
        </Tag>
      </Flex>
      {enforcementMissing || !validationRecorded || !repairRecorded ? (
        <Alert
          description="未记录项以未知展示；Admin 不根据 Provider 名称、响应外形或采用结果猜测约束阶段。"
          showIcon
          title="输出审计信息不完整"
          type="warning"
        />
      ) : null}
      <Descriptions
        column={2}
        items={[
          {
            key: "requested",
            label: "请求的输出约束",
            children: outputEnforcementLabel(enforcement?.requested ?? null),
          },
          {
            key: "actual",
            label: "Provider 实际约束",
            children: outputEnforcementLabel(enforcement?.actual ?? null),
          },
          {
            key: "schema",
            label: "输出 Schema",
            children: outputSchemaLabel(enforcement ?? null),
          },
          {
            key: "repair",
            label: "Parser 修复",
            children: repairRecorded
              ? request.repair_kind === null
                ? "无机械修复"
                : request.repair_kind
              : "未知（未记录）",
          },
          {
            key: "application-validation",
            label: "应用层校验",
            children: validationRecorded
              ? applicationValidationLabel(
                  request.application_validation_result ?? null,
                )
              : "未知（未记录）",
          },
        ]}
        size="small"
      />
    </section>
  );
}

function outputEnforcementLabel(value: string | null) {
  if (value === null) return <Tag>未知（未记录）</Tag>;
  if (value === "strict_json_schema") {
    return <Tag color="success">严格 JSON Schema</Tag>;
  }
  if (value === "prompt_and_application_validation") {
    return <Tag color="warning">提示词 + 应用层校验</Tag>;
  }
  if (value === "none") return <Tag>无 Provider 结构约束</Tag>;
  return <Tag>未识别（{value}）</Tag>;
}

function outputSchemaLabel(
  enforcement: V2ModelRequest["output_enforcement"] | null,
) {
  if (enforcement?.actual === "prompt_and_application_validation") {
    return "未使用 Provider 严格 Schema";
  }
  if (enforcement?.actual === "none") return "不适用";
  if (
    !enforcement ||
    (!enforcement.schema_name && enforcement.schema_version === null)
  ) {
    return "未知（未记录）";
  }
  return `${enforcement.schema_name ?? "名称未知"} · ${
    enforcement.schema_version === null
      ? "版本未知"
      : `V${enforcement.schema_version}`
  }`;
}

function applicationValidationLabel(value: string | null) {
  if (value === null) return "未知（未记录）";
  if (value === "accepted") return <Tag color="success">已接受</Tag>;
  if (value === "rejected") return <Tag color="error">已拒绝</Tag>;
  return <Tag>未识别（{value}）</Tag>;
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

function JsonCopyButton({
  label,
  value,
}: {
  label: string;
  value: unknown;
}) {
  const [copyState, setCopyState] = useState<
    "idle" | "copied" | "failed"
  >("idle");
  return (
    <Button
      aria-label={label}
      danger={copyState === "failed"}
      icon={copyState === "copied" ? <CheckOutlined /> : <CopyOutlined />}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(prettyJson(value));
          setCopyState("copied");
        } catch {
          setCopyState("failed");
        }
      }}
      size="small"
      type="default"
    >
      {copyState === "copied"
        ? "已复制"
        : copyState === "failed"
          ? "复制失败，请重试"
          : label}
    </Button>
  );
}

export function ReadableRawEvents({
  events,
  gameId,
}: {
  events: V2GameRecordEvent[];
  gameId: string;
}) {
  const [activeKeys, setActiveKeys] = useState<string[]>([]);
  return (
    <Collapse
      activeKey={activeKeys}
      className="v2-raw-events"
      items={events.map((event) => ({
        children: activeKeys.includes(String(event.event_id)) ? (
          <RawEventPayload event={event} gameId={gameId} />
        ) : null,
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
      onChange={(keys) =>
        setActiveKeys(
          (Array.isArray(keys) ? keys : [keys]).map(String),
        )
      }
      size="small"
    />
  );
}

function RawEventPayload({
  event,
  gameId,
}: {
  event: V2GameRecordEvent;
  gameId: string;
}) {
  const query = useQuery({
    gcTime: 0,
    queryFn: ({ signal }) =>
      readV2GameEvent(gameId, event.event_id, signal),
    queryKey: v2GameRecordKeys.event(gameId, event.event_id),
  });
  if (query.isPending) {
    return <Typography.Text type="secondary">正在按需读取事件正文...</Typography.Text>;
  }
  if (query.isError) {
    return (
      <Alert
        description={
          isAdminApiError(query.error)
            ? query.error.message
            : "事件正文暂时不可用。"
        }
        message="无法读取事件正文"
        showIcon
        type="error"
      />
    );
  }
  return <pre>{prettyJson(query.data.payload)}</pre>;
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
  const task = isRecord(context.task) ? context.task : null;
  const phaseId = context.phase_id ?? task?.phase_id;
  const actionType = context.action_type ?? task?.type;
  const objective =
    typeof context.objective === "string"
      ? context.objective
      : typeof task?.goal === "string"
        ? task.goal
        : null;
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
    phaseId !== undefined
      ? {
          key: "phase",
          label: "阶段",
          children: displayScalar(phaseId, "phase_id"),
        }
      : null,
    actionType !== undefined
      ? {
          key: "action",
          label: "动作",
          children: displayScalar(actionType, "action_type"),
        }
      : null,
    task?.at_seq !== undefined
      ? {
          key: "at-seq",
          label: "动作发生序号",
          children: displayScalar(task.at_seq, "record_seq"),
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
      {objective ? (
        <section className="v2-objective-callout">
          <Typography.Text type="secondary">动作目标</Typography.Text>
          <Typography.Paragraph>{objective}</Typography.Paragraph>
        </section>
      ) : null}
      {groups.length ? (
        <div className="v2-readable-groups">
          {groups.map(([key, value]) =>
            key === "known_events" && isRecord(value) ? (
              <KnownEventsGroup key={key} value={value} />
            ) : (
              <ReadableGroup key={key} label={fieldLabel(key)} value={value} />
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}

function KnownEventsGroup({
  value,
}: {
  value: Record<string, unknown>;
}) {
  if (integerNumber(value.schema_version) === 7) {
    return <V13KnownEventsGroup value={value} />;
  }
  const events = Array.isArray(value.events) ? value.events : [];
  const claims = events.flatMap((event) =>
    isRecord(event) && Array.isArray(event.annotations)
      ? event.annotations
      : [],
  );
  const questions = Array.isArray(value.questions) ? value.questions : [];
  const relations = Array.isArray(value.relations) ? value.relations : [];
  const derivedCount = claims.length + questions.length + relations.length;
  return (
    <section className="v2-readable-group">
      <Typography.Text className="v2-readable-group-title" strong>
        动作发生前已知事件
      </Typography.Text>
      <Collapse
        items={[
          {
            children: events.length ? (
              <div className="v2-readable-list">
                {events.map((event, index) => (
                  <div className="v2-readable-list-item" key={index}>
                    <KnownEventHeader event={event} index={index} />
                    <ReadableValue value={sourceKnownEvent(event)} />
                  </div>
                ))}
              </div>
            ) : (
              <Empty description="当前动作没有已知事件" />
            ),
            key: "known-events-details",
            label: `查看模型实际可见的源事件（${events.length} 个）`,
          },
          {
            children: derivedCount ? (
              <div className="v2-readable-groups">
                <ReadableGroup label={`声明（${claims.length}）`} value={claims} />
                <ReadableGroup
                  label={`提问（${questions.length}）`}
                  value={questions}
                />
                <ReadableGroup
                  label={`回应关系（${relations.length}）`}
                  value={relations}
                />
              </div>
            ) : (
              <Empty description="当前模型上下文没有通过校验的派生索引" />
            ),
            key: "known-events-derived-index",
            label: `查看通过校验的派生索引（${derivedCount} 项）`,
          },
        ]}
        size="small"
      />
    </section>
  );
}

function V13KnownEventsGroup({
  value,
}: {
  value: Record<string, unknown>;
}) {
  const events = Array.isArray(value.events) ? value.events : [];
  const annotations = Array.isArray(value.annotations) ? value.annotations : [];
  const questions = Array.isArray(value.questions) ? value.questions : [];
  const relations = Array.isArray(value.relations) ? value.relations : [];
  const defaults = isRecord(value.defaults) ? value.defaults : {};
  const scopeCatalog = isRecord(value.scope_catalog) ? value.scope_catalog : {};
  const occurrenceCatalog = isRecord(value.occurrence_catalog)
    ? value.occurrence_catalog
    : {};
  const encoding =
    typeof value.encoding === "string" ? value.encoding : "未记录";
  return (
    <section className="v2-readable-group">
      <Typography.Text className="v2-readable-group-title" strong>
        动作发生前已知事件（V13 真人记忆入选载荷）
      </Typography.Text>
      <Descriptions
        column={2}
        items={[
          {
            key: "schema",
            label: "Compact Schema",
            children: "V7",
          },
          {
            key: "encoding",
            label: "Encoding",
            children: encoding,
          },
          {
            key: "catalogs",
            label: "目录规模",
            children: `scope ${Object.keys(scopeCatalog).length} / occurrence ${
              Object.keys(occurrenceCatalog).length
            }`,
          },
          {
            key: "payload-counts",
            label: "载荷数量",
            children: `事件 ${events.length} / 注解 ${
              annotations.length
            } / 提问 ${questions.length} / 关系 ${relations.length}`,
          },
        ]}
        size="small"
      />
      <Collapse
        items={[
          {
            children: events.length ? (
              <div className="v2-readable-list">
                {events.map((event, index) => (
                  <div className="v2-readable-list-item" key={index}>
                    <KnownEventHeader event={event} index={index} />
                    <ReadableValue value={event} />
                  </div>
                ))}
              </div>
            ) : (
              <Empty description="当前动作没有压缩事件" />
            ),
            key: "v13-compact-events",
            label: `查看选择器入选并编码的事件（${events.length} 个）`,
          },
          {
            children: annotations.length ? (
              <ReadableValue value={annotations} />
            ) : (
              <Empty description="当前载荷没有顶层注解" />
            ),
            key: "v13-annotations",
            label: `查看顶层注解及来源索引（${annotations.length} 项）`,
          },
          {
            children: (
              <div className="v2-readable-groups">
                <ReadableGroup label="V7 默认还原规则" value={defaults} />
                <ReadableGroup label="作用域目录" value={scopeCatalog} />
                <ReadableGroup
                  label="发生阶段目录"
                  value={occurrenceCatalog}
                />
              </div>
            ),
            key: "v13-catalogs",
            label: "查看默认规则与可读目录",
          },
          {
            children: (
              <div className="v2-readable-groups">
                <ReadableGroup
                  label={`提问（${questions.length}）`}
                  value={questions}
                />
                <ReadableGroup
                  label={`回应关系（${relations.length}）`}
                  value={relations}
                />
              </div>
            ),
            key: "v13-derived-indexes",
            label: `查看原序派生索引（${questions.length + relations.length} 项）`,
          },
        ]}
        size="small"
      />
    </section>
  );
}

function sourceKnownEvent(event: unknown) {
  if (!isRecord(event)) return event;
  return Object.fromEntries(
    Object.entries(event).filter(([key]) => key !== "annotations"),
  );
}

function KnownEventHeader({
  event,
  index,
}: {
  event: unknown;
  index: number;
}) {
  if (!isRecord(event)) {
    return <Typography.Text type="secondary">{index + 1}</Typography.Text>;
  }
  const knownAtSeq = integerNumber(event.known_at_seq);
  const kind = typeof event.kind === "string" ? event.kind : null;
  const authority =
    typeof event.authority === "string" ? event.authority : null;
  const visibility =
    typeof event.visibility === "string" ? event.visibility : null;
  return (
    <Space size={6} wrap>
      <Tag>{knownAtSeq === null ? `事件 ${index + 1}` : `#${knownAtSeq}`}</Tag>
      {kind ? <Tag color="blue">{timelineKindLabel(kind)}</Tag> : null}
      {visibility ? (
        <Tag color={visibility === "actor_private" ? "purple" : "default"}>
          {valueLabels[visibility] ?? visibility}
        </Tag>
      ) : null}
      {authority ? (
        <Typography.Text type="secondary">
          {valueLabels[authority] ?? authority}
        </Typography.Text>
      ) : null}
    </Space>
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

function summarizeKnownEvents(
  projection: V2PromptProjection | null,
  value: Record<string, unknown> | null,
): KnownEventsSummary | null {
  const events = value && Array.isArray(value.events) ? value.events : null;
  const metadataPresent =
    projection !== null &&
    [
      "known_events_schema_version",
      "source_event_count",
      "emitted_event_count",
      "known_event_record_seq_min",
      "known_event_record_seq_max",
    ].some((key) => projection[key] !== undefined);
  if (!events && !metadataPresent) return null;

  const eventRecords = (events ?? []).filter(isRecord);
  const sequences = eventRecords.flatMap((event) => {
    const sequence =
      integerNumber(event.known_at_seq) ?? integerNumber(event.record_seq);
    return sequence === null ? [] : [sequence];
  });
  const selectedCount =
    numericField(projection, "emitted_event_count") ?? events?.length ?? 0;
  return {
    recordSeqMax:
      numericField(projection, "known_event_record_seq_max") ??
      (sequences.length ? Math.max(...sequences) : null),
    recordSeqMin:
      numericField(projection, "known_event_record_seq_min") ??
      (sequences.length ? Math.min(...sequences) : null),
    schemaVersion:
      numericField(projection, "known_events_schema_version") ??
      integerNumber(value?.schema_version),
    selectedCount,
  };
}

function integerNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function recordSeqRange(summary: {
  recordSeqMax: number | null;
  recordSeqMin: number | null;
}) {
  if (summary.recordSeqMin === null || summary.recordSeqMax === null) return "—";
  if (summary.recordSeqMin === summary.recordSeqMax) {
    return `#${summary.recordSeqMin}`;
  }
  return `#${summary.recordSeqMin} – #${summary.recordSeqMax}`;
}

function timelineKindLabel(kind: string) {
  return valueLabels[kind] ?? humanize(kind);
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
    fieldKey === "authority" ||
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
