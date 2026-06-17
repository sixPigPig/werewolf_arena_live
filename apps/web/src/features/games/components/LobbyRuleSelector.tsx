import classic8CardSelected from "../../../assets/rule-cards/classic-8-selected.png";
import classic8Card from "../../../assets/rule-cards/classic-8.png";
import hunt12CardSelected from "../../../assets/rule-cards/hunt-12-selected.png";
import hunt12Card from "../../../assets/rule-cards/hunt-12.png";
import social8CardSelected from "../../../assets/rule-cards/social-8-selected.png";
import social8Card from "../../../assets/rule-cards/social-8.png";
import starter6CardSelected from "../../../assets/rule-cards/starter-6-selected.png";
import starter6Card from "../../../assets/rule-cards/starter-6.png";
import { RadioCards } from "../../../components/ui";

import { formatRoleSummary } from "../rulePresentation";
import type { RuleSetSummary } from "../types";

export type LobbyRuleSelectorProps = {
  error: boolean;
  loading: boolean;
  onValueChange: (ruleId: string) => void;
  rules: RuleSetSummary[];
  value: string;
};

type RuleCardArt = {
  selectedSrc: string;
  src: string;
};

const RULE_CARD_ART_BY_ID: Record<string, RuleCardArt> = {
  classic_8: {
    selectedSrc: classic8CardSelected,
    src: classic8Card,
  },
  classic_12_seer_witch_hunter_idiot: {
    selectedSrc: hunt12CardSelected,
    src: hunt12Card,
  },
  sheriff_12: {
    selectedSrc: hunt12CardSelected,
    src: hunt12Card,
  },
  social_8: {
    selectedSrc: social8CardSelected,
    src: social8Card,
  },
  starter_6: {
    selectedSrc: starter6CardSelected,
    src: starter6Card,
  },
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
      {rules.length > 0 ? (
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
            const cardArt = RULE_CARD_ART_BY_ID[rule.id];
            const ruleMeta = `${rule.player_count} 人 · ${
              rule.complexity ?? "标准"
            } · ${rule.estimated_duration ?? "中"}`;

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
                <div className="lobby-rule-card-body">
                  {cardArt ? (
                    <img
                      alt=""
                      aria-hidden="true"
                      className="lobby-rule-card-image"
                      draggable={false}
                      src={isSelected ? cardArt.selectedSrc : cardArt.src}
                    />
                  ) : (
                    <div className="lobby-rule-card-fallback">
                      <span className="lobby-rule-name">{rule.name}</span>
                      <span className="lobby-rule-meta">{ruleMeta}</span>
                      <span className="lobby-rule-roles">
                        {formatRoleSummary(rule)}
                      </span>
                    </div>
                  )}
                  <span aria-hidden="true" className="sr-only">
                    <span>{rule.name}</span>
                    <span>{ruleMeta}</span>
                    <span>{formatRoleSummary(rule)}</span>
                    {rule.rule_tags?.map((tag) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </span>
                </div>
              </RadioCards.Item>
            );
          })}
        </RadioCards.Root>
      ) : null}
    </section>
  );
}
