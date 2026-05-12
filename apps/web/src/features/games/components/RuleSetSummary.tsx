import { Badge } from "../../../components/ui";
import { withGlassPanel } from "../../../components/ui/glass";

import type { RuleSetSummary as RuleSetSummaryType } from "../types";

type RuleSetSummaryProps = {
  ruleSet?: RuleSetSummaryType | null;
  variant?: "panel" | "nav";
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

export function RuleSetSummary({
  ruleSet,
  variant = "panel",
}: RuleSetSummaryProps) {
  const rule = ruleSet ?? FALLBACK_RULE;
  const roleSummary =
    rule.role_summary ??
    rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");
  const isNav = variant === "nav";

  return (
    <section
      className={
        isNav
          ? "rule-set-summary live-command-rule-summary flex min-w-0 shrink-0 flex-nowrap items-center gap-x-3 text-slate-100"
          : withGlassPanel("rule-set-summary rounded-lg p-4 text-slate-100")
      }
      data-testid="rule-set-summary"
    >
      <div
        className={`flex items-center gap-x-3 ${
          isNav ? "min-w-0" : ""
        }`}
      >
        <h2
          className={
            isNav
              ? "max-w-[13rem] truncate text-sm font-semibold text-amber-50"
              : "text-sm font-semibold text-amber-50"
          }
        >
          {rule.name}
        </h2>
        <span className="text-xs font-semibold text-amber-300/85">
          v{rule.version}
        </span>
        <span className="text-xs text-teal-100/70">{rule.player_count} 人</span>
      </div>
      <p
        className={
          isNav
            ? "sr-only"
            : "mt-1 text-sm text-slate-300"
        }
      >
        {roleSummary}
      </p>
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
