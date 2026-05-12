import {
  Badge,
  Button,
  Callout,
  Card,
  Flex,
  RadioCards,
  SelectField,
  Text,
  TextField,
} from "../../../components/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { createGameRun } from "../api/createGameRun";
import { listRuleSets } from "../api/listRuleSets";
import type { EventPacingMode, RuleSetSummary } from "../types";

export function CreateGameRunForm() {
  const navigate = useNavigate();
  const [selectedRuleSetId, setSelectedRuleSetId] = useState("classic_8");
  const [seed, setSeed] = useState("");
  const [maxRounds, setMaxRounds] = useState("8");
  const [eventPacing, setEventPacing] = useState<EventPacingMode>("off");
  const [validationError, setValidationError] = useState<string | null>(null);

  const ruleSetsQuery = useQuery({
    queryKey: ["rule-sets"],
    queryFn: listRuleSets,
  });

  const mutation = useMutation({
    mutationFn: createGameRun,
    onSuccess: (run) => navigate(`/games/live/${run.run_id}`),
  });

  const ruleSets = ruleSetsQuery.data?.rule_sets ?? [];
  const selectedRuleSet =
    ruleSets.find((rule) => rule.id === selectedRuleSetId) ??
    ruleSets[0] ??
    null;
  const isSubmitDisabled =
    mutation.isPending || ruleSetsQuery.isPending || ruleSetsQuery.isError;

  const renderRuleCard = (rule: RuleSetSummary) => {
    const roleSummary = formatRoleSummary(rule);
    const isSelected = selectedRuleSetId === rule.id;

    return (
      <RadioCards.Item
        aria-label={rule.name}
        className={[
          "group relative min-h-[10.25rem] overflow-hidden rounded-lg px-4 py-3",
          "border-slate-400/20 bg-slate-950/35 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]",
          "hover:border-amber-200/60 hover:bg-slate-950/55",
          isSelected
            ? "border-amber-200/85 bg-amber-950/20 shadow-[0_0_0_1px_rgba(251,191,36,0.38),0_0_28px_rgba(251,191,36,0.24),inset_0_1px_0_rgba(255,255,255,0.08)]"
            : "",
        ].join(" ")}
        key={rule.id}
        value={rule.id}
      >
        <span
          aria-hidden="true"
          className={[
            "absolute inset-x-3 top-0 h-px bg-gradient-to-r from-transparent via-amber-200/45 to-transparent",
            isSelected ? "opacity-100" : "opacity-0 group-hover:opacity-70",
          ].join(" ")}
        />
        <Flex className="relative min-w-0 flex-row items-start gap-4" width="100%">
          <span
            aria-hidden="true"
            className={[
              "grid h-16 w-16 shrink-0 place-items-center rounded-full border text-2xl font-semibold",
              "bg-[radial-gradient(circle_at_50%_35%,rgba(251,191,36,0.18),rgba(15,23,42,0.14)_55%,rgba(2,6,23,0.55))]",
              isSelected
                ? "border-amber-200/70 text-amber-100 shadow-[0_0_22px_rgba(251,191,36,0.22)]"
                : "border-slate-300/25 text-slate-300",
            ].join(" ")}
          >
            {getRuleEmblem(rule)}
          </span>
          <Flex className="min-w-0" direction="column" gap="2" width="100%">
            <Text
              as="span"
              className="break-words font-serif text-xl leading-7 text-amber-50"
              size="3"
              weight="bold"
            >
              {rule.name}
            </Text>
            <Text as="span" className="break-words text-slate-300" size="2">
              {rule.player_count} 人 · {rule.complexity ?? "标准"} ·{" "}
              {rule.estimated_duration ?? "中"}
            </Text>
            <Text as="span" className="break-words text-slate-200" size="2">
              {roleSummary}
            </Text>
            {rule.rule_tags && rule.rule_tags.length > 0 ? (
              <Flex gap="1" wrap="wrap">
                {rule.rule_tags.map((tag) => (
                  <Badge
                    className="border-amber-300/35 bg-slate-950/20 text-amber-100"
                    color="gray"
                    key={tag}
                    variant="surface"
                  >
                    {tag}
                  </Badge>
                ))}
              </Flex>
            ) : null}
          </Flex>
        </Flex>
      </RadioCards.Item>
    );
  };

  return (
    <Card asChild size="2">
      <form
        className="games-create-module"
        data-testid="games-create-module"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const parsedMaxRounds = Number(maxRounds);
          if (
            !maxRounds ||
            !Number.isInteger(parsedMaxRounds) ||
            parsedMaxRounds < 1 ||
            parsedMaxRounds > 20
          ) {
            setValidationError("最大轮数必须是 1 到 20 的整数");
            return;
          }

          setValidationError(null);
          mutation.mutate({
            rule_set_id: selectedRuleSetId,
            seed: seed ? Number(seed) : null,
            max_rounds: parsedMaxRounds,
            event_pacing: eventPacing,
          });
        }}
      >
      <fieldset className="mb-5">
        <legend className="flex items-center gap-2 text-base font-semibold text-amber-50">
          <span
            aria-hidden="true"
            className="h-5 w-5 rotate-45 border border-amber-200/60"
          />
          官方规则
        </legend>
        {ruleSetsQuery.isPending ? (
          <p className="mt-2 text-sm text-slate-600">正在读取官方规则...</p>
        ) : null}
        {ruleSetsQuery.isError ? (
          <p className="mt-2 text-sm text-red-700">无法读取官方规则</p>
        ) : null}
        {ruleSets.length > 0 ? (
          <div className="mt-4 space-y-4">
            <RadioCards.Root
              aria-label="官方规则"
              className="mt-2"
              columns={{ initial: "1", md: "2" }}
              gap="3"
              highContrast
              onValueChange={setSelectedRuleSetId}
              value={selectedRuleSetId}
              variant="surface"
            >
              {ruleSets.map(renderRuleCard)}
            </RadioCards.Root>
            {selectedRuleSet ? (
              <SelectedRuleDetails rule={selectedRuleSet} />
            ) : null}
          </div>
        ) : null}
      </fieldset>
      <div className="flex flex-col gap-3 border-t border-amber-200/15 pt-4 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-200">
          随机种子
          <TextField.Root
            inputMode="numeric"
            placeholder="可留空"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-200">
          最大轮数
          <TextField.Root
            min={1}
            max={20}
            required
            type="number"
            value={maxRounds}
            onChange={(event) => {
              setMaxRounds(event.target.value);
              setValidationError(null);
            }}
          />
        </label>
        <div className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-200">
          <span id="event-pacing-label">演示慢速</span>
          <SelectField
            aria-labelledby="event-pacing-label"
            value={eventPacing}
            onChange={(event) =>
              setEventPacing(event.target.value as EventPacingMode)
            }
          >
            <option value="off">关闭</option>
            <option value="standard">标准演示</option>
            <option value="slow">慢速讲解</option>
          </SelectField>
        </div>
        <Button
          disabled={isSubmitDisabled}
          highContrast
          loading={mutation.isPending}
          type="submit"
        >
          发起对局
        </Button>
      </div>
      {validationError ? (
        <Callout.Root className="mt-3" color="red" size="1" variant="soft">
          <Callout.Text>{validationError}</Callout.Text>
        </Callout.Root>
      ) : null}
      {mutation.isError ? (
        <Callout.Root className="mt-3" color="red" size="1" variant="soft">
          <Callout.Text>无法发起对局</Callout.Text>
        </Callout.Root>
      ) : null}
      </form>
    </Card>
  );
}

function SelectedRuleDetails({ rule }: { rule: RuleSetSummary }) {
  const roleSummary = formatRoleSummary(rule);
  const rows = [
    { label: "阵营配置", value: roleSummary },
    { label: "发言顺序", value: formatSpeechPolicy(rule) },
    { label: "警长规则", value: formatSheriffRule(rule) },
    { label: "胜利条件", value: formatWinCondition(rule) },
    { label: "复盘提示", value: formatReplayHint(rule) },
  ];

  return (
    <section
      className="relative overflow-hidden rounded-lg border border-amber-200/25 bg-slate-950/35 px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
      data-testid="selected-rule-details"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute bottom-4 right-7 hidden h-32 w-32 rounded-full border border-amber-200/10 text-center font-serif text-7xl leading-[8rem] text-amber-100/5 md:block"
      >
        狼
      </div>
      <div className="relative flex items-center gap-3">
        <span
          aria-hidden="true"
          className="grid h-12 w-12 shrink-0 place-items-center rounded-full border border-amber-200/45 bg-amber-300/10 font-serif text-2xl text-amber-100"
        >
          {getRuleEmblem(rule)}
        </span>
        <div className="min-w-0">
          <h3 className="break-words font-serif text-2xl font-semibold leading-8 text-amber-100">
            {rule.name}规则
          </h3>
          {rule.description ? (
            <p className="mt-1 text-sm text-slate-300">{rule.description}</p>
          ) : null}
        </div>
      </div>
      <dl className="relative mt-4 divide-y divide-amber-200/10">
        {rows.map((row) => (
          <div
            className="grid gap-1 py-2 sm:grid-cols-[8rem_1fr]"
            key={row.label}
          >
            <dt className="text-sm font-semibold text-amber-100">{row.label}</dt>
            <dd className="text-sm leading-6 text-slate-100">{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function formatRoleSummary(rule: RuleSetSummary) {
  if (rule.role_summary) {
    return rule.role_summary;
  }

  return rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");
}

function getRuleEmblem(rule: RuleSetSummary) {
  if (rule.sheriff_enabled) {
    return "警";
  }

  if (rule.name.includes("新手")) {
    return "新";
  }

  if (rule.name.includes("社交")) {
    return "社";
  }

  return "典";
}

function formatSpeechPolicy(rule: RuleSetSummary) {
  if (rule.speech_policy === "sheriff_directed") {
    return "警长决定警左或警右，所有玩家完成完整发言";
  }

  return "顺序发言";
}

function formatSheriffRule(rule: RuleSetSummary) {
  if (!rule.sheriff_enabled) {
    return "无警长";
  }

  const voteWeight = rule.sheriff_vote_weight ?? 1.5;
  return `有警长，警徽 ${voteWeight} 票`;
}

function formatWinCondition(rule: RuleSetSummary) {
  if (
    rule.win_condition === "slaughter_side" ||
    rule.rule_tags?.includes("屠边")
  ) {
    return "狼人淘汰所有神民或村民；好人放逐所有狼人";
  }

  return "狼人数量大于等于其他存活玩家；好人放逐所有狼人";
}

function formatReplayHint(rule: RuleSetSummary) {
  const nightActions = rule.night_actions ?? [];
  const hasNightRoles = nightActions.length > 1;
  const hasSheriff = Boolean(rule.sheriff_enabled);

  if (hasSheriff) {
    return "显示上警、警徽流、投票轨迹与关键发言";
  }

  if (hasNightRoles) {
    return "显示夜间行动、投票轨迹与关键发言";
  }

  return "突出发言博弈、投票轨迹与关键轮次";
}
