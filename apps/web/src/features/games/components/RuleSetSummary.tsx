import { Badge } from "@radix-ui/themes";

import type { RuleSetSummary as RuleSetSummaryType } from "../types";

type RuleSetSummaryProps = {
  ruleSet?: RuleSetSummaryType | null;
};

const FALLBACK_RULE: RuleSetSummaryType = {
  id: "classic_8",
  version: "legacy",
  name: "经典 8 人局",
  player_count: 8,
  roles: [
    { role: "狼人", count: 2 },
    { role: "预言家", count: 1 },
    { role: "守卫", count: 1 },
    { role: "村民", count: 4 },
  ],
  role_summary: "2 狼人 / 1 预言家 / 1 守卫 / 4 村民",
};

export function RuleSetSummary({ ruleSet }: RuleSetSummaryProps) {
  const rule = ruleSet ?? FALLBACK_RULE;
  const roleSummary =
    rule.role_summary ??
    rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");

  return (
    <section
      className="rounded-lg border border-amber-500/20 bg-slate-950/60 p-4 text-slate-100 shadow-[0_18px_50px_rgba(0,0,0,0.24)] backdrop-blur-xl"
      data-testid="rule-set-summary"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold text-amber-50">{rule.name}</h2>
        <span className="text-xs text-amber-200/70">v{rule.version}</span>
        <span className="text-xs text-teal-100/70">
          {rule.player_count} 人
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-300">{roleSummary}</p>
      {rule.rule_tags && rule.rule_tags.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {rule.rule_tags.map((tag) => (
            <Badge color="amber" key={tag} variant="surface">
              {tag}
            </Badge>
          ))}
        </div>
      ) : null}
    </section>
  );
}
