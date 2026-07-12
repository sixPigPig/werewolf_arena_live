import { type RefObject, useRef } from "react";
import type { RuleSetSummary } from "@werewolf-arena/game-client";

import { LobbyModal } from "./LobbyModal";
import { getLobbyRuleCardImage } from "./lobbyRuleAssets";

type LobbyRulePickerProps = {
  backgroundRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSelect: (ruleSetId: string) => void;
  restoreFocusRef: RefObject<HTMLElement | null>;
  ruleSets: RuleSetSummary[];
  selectedRuleSetId: string | null;
};

export function LobbyRulePicker({
  backgroundRef,
  onClose,
  onSelect,
  restoreFocusRef,
  ruleSets,
  selectedRuleSetId,
}: LobbyRulePickerProps) {
  const selectedRuleRef = useRef<HTMLButtonElement | null>(null);

  return (
    <LobbyModal
      backgroundRef={backgroundRef}
      className="mobile-lobby-rule-dialog"
      initialFocusRef={selectedRuleRef}
      labelledBy="mobile-rule-picker-title"
      onClose={onClose}
      restoreFocusRef={restoreFocusRef}
    >
      <header className="mobile-lobby-modal-header">
        <h2 id="mobile-rule-picker-title">选择规则</h2>
        <button aria-label="关闭规则选择" onClick={onClose} type="button">
          ×
        </button>
      </header>
      <div aria-label="可用规则" className="mobile-lobby-rule-grid" role="group">
        {ruleSets.map((ruleSet) => {
          const isSelected = ruleSet.id === selectedRuleSetId;
          const image = getLobbyRuleCardImage(ruleSet.id, isSelected);
          return (
            <button
              aria-label={`选择规则 ${ruleSet.name}`}
              aria-pressed={isSelected}
              className="mobile-lobby-rule-option"
              key={ruleSet.id}
              onClick={() => {
                onSelect(ruleSet.id);
                onClose();
              }}
              ref={isSelected ? selectedRuleRef : undefined}
              type="button"
            >
              {image ? <img alt="" aria-hidden="true" src={image} /> : null}
              <strong>{ruleSet.name}</strong>
              <span>{ruleSet.player_count} 人</span>
              <small>
                {ruleSet.role_summary ?? ruleSet.complexity ?? "自定义规则"}
              </small>
            </button>
          );
        })}
      </div>
    </LobbyModal>
  );
}
