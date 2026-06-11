import { useEffect, useRef, type RefObject } from "react";

import {
  formatReplayHint,
  formatRoleSummary,
  formatSheriffRule,
  formatSpeechPolicy,
  formatWinCondition,
} from "../rulePresentation";
import type { RuleSetSummary } from "../types";

type RuleDetailsDrawerProps = {
  onClose: () => void;
  open: boolean;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  rule: RuleSetSummary;
};

const focusableSelector =
  'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export function RuleDetailsDrawer({
  onClose,
  open,
  returnFocusRef,
  rule,
}: RuleDetailsDrawerProps) {
  const drawerRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    closeButtonRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const drawer = drawerRef.current;
      if (!drawer) {
        return;
      }

      const focusableElements = Array.from(
        drawer.querySelectorAll<HTMLElement>(focusableSelector),
      );
      if (focusableElements.length === 0) {
        event.preventDefault();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;

      if (
        event.shiftKey &&
        (activeElement === firstElement || !drawer.contains(activeElement))
      ) {
        event.preventDefault();
        lastElement?.focus();
      } else if (
        !event.shiftKey &&
        (activeElement === lastElement || !drawer.contains(activeElement))
      ) {
        event.preventDefault();
        firstElement?.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [onClose, open, returnFocusRef]);

  if (!open) {
    return null;
  }

  const rows = [
    { label: "阵营配置", value: formatRoleSummary(rule) },
    { label: "发言顺序", value: formatSpeechPolicy(rule) },
    { label: "警长规则", value: formatSheriffRule(rule) },
    { label: "胜利条件", value: formatWinCondition(rule) },
    { label: "复盘提示", value: formatReplayHint(rule) },
  ];

  return (
    <div
      className="lobby-rule-drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        aria-labelledby="lobby-rule-drawer-title"
        aria-modal="true"
        className="lobby-rule-drawer"
        ref={drawerRef}
        role="dialog"
      >
        <header>
          <h2 id="lobby-rule-drawer-title">{rule.name}规则</h2>
          <button
            aria-label="关闭规则详情"
            className="lobby-rule-drawer-close"
            onClick={onClose}
            ref={closeButtonRef}
            type="button"
          >
            <span aria-hidden="true">×</span>
          </button>
        </header>
        {rule.description ? <p>{rule.description}</p> : null}
        <dl>
          {rows.map((row) => (
            <div key={row.label}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
