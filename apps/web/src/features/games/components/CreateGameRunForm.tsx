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
    const isSelected = selectedRuleSetId === rule.id;
    const roleSummary =
      rule.role_summary ??
      rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");

    return (
      <label
        className={`block rounded-md border p-3 text-sm transition has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-slate-950 has-[:focus-visible]:ring-offset-2 ${
          isSelected
            ? "border-slate-950 bg-slate-100"
            : "border-slate-200 bg-white"
        }`}
        key={rule.id}
      >
        <input
          aria-label={rule.name}
          checked={isSelected}
          className="sr-only"
          name="rule_set_id"
          type="radio"
          value={rule.id}
          onChange={() => setSelectedRuleSetId(rule.id)}
        />
        <span className="block font-semibold text-slate-950">{rule.name}</span>
        <span className="mt-1 block text-slate-600">
          {rule.player_count} 人 · {rule.complexity ?? "标准"} ·{" "}
          {rule.estimated_duration ?? "中"}
        </span>
        <span className="mt-2 block text-slate-700">{roleSummary}</span>
        {rule.rule_tags && rule.rule_tags.length > 0 ? (
          <span className="mt-2 flex flex-wrap gap-1.5">
            {rule.rule_tags.map((tag) => (
              <span
                className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-xs text-slate-600"
                key={tag}
              >
                {tag}
              </span>
            ))}
          </span>
        ) : null}
      </label>
    );
  };

  return (
    <form
      className="rounded-md border border-slate-200 bg-white p-4"
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
                <div className="mt-2 grid gap-3 md:grid-cols-2">
                  {quickRuleSets.map(renderRuleCard)}
                </div>
              </section>
            ) : null}
            {sheriffRuleSets.length > 0 ? (
              <section>
                <h3 className="text-xs font-semibold uppercase text-slate-500">
                  标准警长局
                </h3>
                <div className="mt-2 grid gap-3 md:grid-cols-2">
                  {sheriffRuleSets.map(renderRuleCard)}
                </div>
              </section>
            ) : null}
          </div>
        ) : null}
      </fieldset>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
          随机种子
          <input
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            inputMode="numeric"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
            placeholder="可留空"
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
          最大轮数
          <input
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
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
        <label className="flex flex-1 flex-col gap-1 text-sm font-medium text-slate-700">
          演示慢速
          <select
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={eventPacing}
            onChange={(event) =>
              setEventPacing(event.target.value as EventPacingMode)
            }
          >
            <option value="off">关闭</option>
            <option value="standard">标准演示</option>
            <option value="slow">慢速讲解</option>
          </select>
        </label>
        <button
          className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
          disabled={isSubmitDisabled}
          type="submit"
        >
          {mutation.isPending ? "正在发起..." : "发起对局"}
        </button>
      </div>
      {validationError ? (
        <p className="mt-3 text-sm text-red-700">{validationError}</p>
      ) : null}
      {mutation.isError ? (
        <p className="mt-3 text-sm text-red-700">无法发起对局</p>
      ) : null}
    </form>
  );
}
