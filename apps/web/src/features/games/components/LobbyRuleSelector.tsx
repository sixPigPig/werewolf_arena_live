import { Badge, Flex, RadioCards, Text } from "../../../components/ui";

import { formatRoleSummary, getRuleEmblem } from "../rulePresentation";
import type { RuleSetSummary } from "../types";

export type LobbyRuleSelectorProps = {
  error: boolean;
  loading: boolean;
  onValueChange: (ruleId: string) => void;
  rules: RuleSetSummary[];
  value: string;
};

export function LobbyRuleSelector({
  error,
  loading,
  onValueChange,
  rules,
  value,
}: LobbyRuleSelectorProps) {
  return (
    <section
      aria-labelledby="lobby-rule-selector-title"
      className="lobby-workbench-column lobby-rule-column"
      data-testid="lobby-rule-column"
    >
      <h2 id="lobby-rule-selector-title">规则选择</h2>
      {loading ? (
        <p className="lobby-rules-status">正在读取官方规则...</p>
      ) : null}
      {error ? <p className="lobby-rules-error">无法读取官方规则</p> : null}
      <RadioCards.Root
        aria-label="官方规则"
        className="lobby-rule-list lobby-rule-grid"
        highContrast
        onValueChange={onValueChange}
        value={value}
        variant="surface"
      >
        {rules.map((rule) => {
          const isSelected = value === rule.id;

          return (
            <RadioCards.Item
              aria-label={rule.name}
              className={[
                "lobby-rule-card",
                isSelected ? "lobby-rule-card-selected" : "",
              ].join(" ")}
              key={rule.id}
              value={rule.id}
            >
              <span aria-hidden="true" className="lobby-rule-card-glint" />
              <div className="lobby-rule-card-body">
                <span
                  aria-hidden="true"
                  className={[
                    "lobby-rule-emblem",
                    isSelected ? "lobby-rule-emblem-selected" : "",
                  ].join(" ")}
                >
                  {getRuleEmblem(rule)}
                </span>
                <div className="lobby-rule-copy">
                  <Text
                    as="span"
                    className="lobby-rule-name"
                    size="3"
                    weight="bold"
                  >
                    {rule.name}
                  </Text>
                  <Text as="span" className="lobby-rule-meta" size="2">
                    {rule.player_count} 人 · {rule.complexity ?? "标准"} ·{" "}
                    {rule.estimated_duration ?? "中"}
                  </Text>
                  <Text as="span" className="lobby-rule-roles" size="2">
                    {formatRoleSummary(rule)}
                  </Text>
                  {rule.rule_tags && rule.rule_tags.length > 0 ? (
                    <Flex className="lobby-rule-tags" gap="1" wrap="wrap">
                      {rule.rule_tags.map((tag) => (
                        <Badge
                          className="lobby-rule-tag"
                          color="gray"
                          key={tag}
                          variant="surface"
                        >
                          {tag}
                        </Badge>
                      ))}
                    </Flex>
                  ) : null}
                </div>
              </div>
            </RadioCards.Item>
          );
        })}
      </RadioCards.Root>
    </section>
  );
}
