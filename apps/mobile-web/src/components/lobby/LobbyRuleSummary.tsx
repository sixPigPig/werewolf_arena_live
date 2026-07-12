import type { RefObject } from "react";
import type { RuleSetSummary } from "@werewolf-arena/game-client";

type LobbyRuleSummaryProps = {
  changeButtonRef: RefObject<HTMLButtonElement | null>;
  disabled: boolean;
  isError: boolean;
  isLoading: boolean;
  onOpenPicker: () => void;
  onRetry: () => void;
  ruleSet: RuleSetSummary | null;
};

export function LobbyRuleSummary({
  changeButtonRef,
  disabled,
  isError,
  isLoading,
  onOpenPicker,
  onRetry,
  ruleSet,
}: LobbyRuleSummaryProps) {
  return (
    <section aria-label="当前规则" className="mobile-lobby-rule-summary">
      <div className="mobile-lobby-rule-summary-copy">
        <span>当前规则</span>
        <h2 id="mobile-current-rule-title">{ruleSet?.name ?? "等待规则"}</h2>
        <p>
          {ruleSet
            ? `${ruleSet.player_count} 人 · ${ruleSet.role_summary ?? ruleSet.complexity ?? "自定义规则"}`
            : isLoading
              ? "正在读取规则"
              : "暂时无法读取规则"}
        </p>
      </div>
      {isError ? (
        <button onClick={onRetry} type="button">
          重新加载规则
        </button>
      ) : (
        <button
          disabled={!ruleSet || disabled}
          onClick={onOpenPicker}
          ref={changeButtonRef}
          type="button"
        >
          更换规则
        </button>
      )}
    </section>
  );
}
