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
  const quickRuleSets = ruleSets.filter((rule) => !rule.sheriff_enabled);
  const sheriffRuleSets = ruleSets.filter((rule) => rule.sheriff_enabled);
  const isSubmitDisabled =
    mutation.isPending || ruleSetsQuery.isPending || ruleSetsQuery.isError;

  const renderRuleCard = (rule: RuleSetSummary) => {
    const roleSummary =
      rule.role_summary ??
      rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");

    return (
      <RadioCards.Item
        aria-label={rule.name}
        className="min-h-36"
        key={rule.id}
        value={rule.id}
      >
        <Flex className="min-w-0" direction="column" gap="2" width="100%">
          <Text
            as="span"
            className="break-words text-slate-950"
            size="3"
            weight="bold"
          >
            {rule.name}
          </Text>
          <Text as="span" className="break-words text-slate-600" size="2">
            {rule.player_count} 人 · {rule.complexity ?? "标准"} ·{" "}
            {rule.estimated_duration ?? "中"}
          </Text>
          <Text as="span" className="break-words text-slate-700" size="2">
            {roleSummary}
          </Text>
          {rule.rule_tags && rule.rule_tags.length > 0 ? (
            <Flex gap="1" wrap="wrap">
              {rule.rule_tags.map((tag) => (
                <Badge color="gray" key={tag} variant="surface">
                  {tag}
                </Badge>
              ))}
            </Flex>
          ) : null}
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
      <fieldset className="mb-4">
        <legend className="text-sm font-semibold text-slate-900">
          官方规则
        </legend>
        {ruleSetsQuery.isPending ? (
          <p className="mt-2 text-sm text-slate-600">正在读取官方规则...</p>
        ) : null}
        {ruleSetsQuery.isError ? (
          <p className="mt-2 text-sm text-red-700">无法读取官方规则</p>
        ) : null}
        {ruleSets.length > 0 ? (
          <div className="mt-3 space-y-4">
            {quickRuleSets.length > 0 ? (
              <section>
                <h3 className="text-xs font-semibold uppercase text-slate-500">
                  快速少人局
                </h3>
                <RadioCards.Root
                  aria-label="快速少人局"
                  className="mt-2"
                  columns={{ initial: "1", md: "2" }}
                  gap="3"
                  highContrast
                  onValueChange={setSelectedRuleSetId}
                  value={selectedRuleSetId}
                  variant="surface"
                >
                  {quickRuleSets.map(renderRuleCard)}
                </RadioCards.Root>
              </section>
            ) : null}
            {sheriffRuleSets.length > 0 ? (
              <section>
                <h3 className="text-xs font-semibold uppercase text-slate-500">
                  标准警长局
                </h3>
                <RadioCards.Root
                  aria-label="标准警长局"
                  className="mt-2"
                  columns={{ initial: "1", md: "2" }}
                  gap="3"
                  highContrast
                  onValueChange={setSelectedRuleSetId}
                  value={selectedRuleSetId}
                  variant="surface"
                >
                  {sheriffRuleSets.map(renderRuleCard)}
                </RadioCards.Root>
              </section>
            ) : null}
          </div>
        ) : null}
      </fieldset>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
          随机种子
          <TextField.Root
            inputMode="numeric"
            placeholder="可留空"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
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
        <div className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
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
