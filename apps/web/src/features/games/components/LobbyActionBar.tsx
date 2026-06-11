import { useEffect, useRef, useState } from "react";

import { Button, TextField } from "../../../components/ui";

const clearDialogFocusableSelector = [
  'a[href]:not([tabindex="-1"])',
  'button:not(:disabled):not([tabindex="-1"])',
  'input:not(:disabled):not([tabindex="-1"])',
  'select:not(:disabled):not([tabindex="-1"])',
  'textarea:not(:disabled):not([tabindex="-1"])',
  '[tabindex]:not([tabindex="-1"]):not([disabled])',
].join(",");

export type LobbyActionBarProps = {
  disabled: boolean;
  loading: boolean;
  maxRounds: string;
  onClearAll: () => void;
  onFillFavorites: () => void;
  onMaxRoundsChange: (value: string) => void;
  onRandomFill: () => void;
  onSeedChange: (value: string) => void;
  seed: string;
};

export function LobbyActionBar({
  disabled,
  loading,
  maxRounds,
  onClearAll,
  onFillFavorites,
  onMaxRoundsChange,
  onRandomFill,
  onSeedChange,
  seed,
}: LobbyActionBarProps) {
  const [confirmingClear, setConfirmingClear] = useState(false);
  const clearButtonRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!confirmingClear) {
      return;
    }

    const returnFocusElement = clearButtonRef.current;
    dialogRef.current
      ?.querySelector<HTMLButtonElement>("[data-clear-dialog-cancel]")
      ?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setConfirmingClear(false);
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const dialog = dialogRef.current;
      if (!dialog) {
        return;
      }

      const focusableElements = Array.from(
        dialog.querySelectorAll<HTMLElement>(clearDialogFocusableSelector),
      );
      const firstFocusable = focusableElements[0];
      const lastFocusable = focusableElements.at(-1);

      if (!firstFocusable || !lastFocusable) {
        return;
      }

      if (event.shiftKey) {
        if (
          document.activeElement === firstFocusable ||
          !dialog.contains(document.activeElement)
        ) {
          event.preventDefault();
          lastFocusable.focus();
        }
        return;
      }

      if (
        document.activeElement === lastFocusable ||
        !dialog.contains(document.activeElement)
      ) {
        event.preventDefault();
        firstFocusable.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusElement?.focus();
    };
  }, [confirmingClear]);

  return (
    <footer className="lobby-action-bar" data-testid="lobby-action-bar">
      <div className="lobby-action-parameters">
        <label>
          <span>随机种子</span>
          <TextField.Root
            aria-label="随机种子"
            inputMode="numeric"
            placeholder="可留空"
            value={seed}
            onChange={(event) => onSeedChange(event.target.value)}
          />
        </label>
        <label>
          <span>最大轮数</span>
          <TextField.Root
            aria-label="最大轮数"
            max={20}
            min={1}
            required
            type="number"
            value={maxRounds}
            onChange={(event) => onMaxRoundsChange(event.target.value)}
          />
        </label>
      </div>
      <div className="lobby-action-buttons">
        <Button onClick={onRandomFill} skin="gothic" type="button">
          随机填充空席
        </Button>
        <Button onClick={onFillFavorites} skin="gothic" type="button">
          只用收藏填充
        </Button>
        <Button
          onClick={(event) => {
            clearButtonRef.current = event.currentTarget;
            setConfirmingClear(true);
          }}
          skin="gothic"
          type="button"
        >
          清空阵容
        </Button>
        <Button
          className="lobby-action-launch"
          disabled={disabled}
          intent="warning"
          loading={loading}
          skin="gothic"
          type="submit"
        >
          发起对局
        </Button>
      </div>
      {confirmingClear ? (
        <div className="lobby-clear-dialog-backdrop">
          <section
            aria-describedby="lobby-clear-dialog-description"
            aria-labelledby="lobby-clear-dialog-title"
            aria-modal="true"
            className="lobby-clear-dialog"
            ref={dialogRef}
            role="alertdialog"
          >
            <h2 id="lobby-clear-dialog-title">确认清空阵容</h2>
            <p id="lobby-clear-dialog-description">
              全部席位玩家与临时模型覆盖都会被移除。
            </p>
            <div className="lobby-clear-dialog-actions">
              <Button
                data-clear-dialog-cancel=""
                onClick={() => setConfirmingClear(false)}
                skin="gothic"
                type="button"
              >
                取消
              </Button>
              <Button
                intent="warning"
                onClick={() => {
                  onClearAll();
                  setConfirmingClear(false);
                }}
                skin="gothic"
                type="button"
              >
                确认清空
              </Button>
            </div>
          </section>
        </div>
      ) : null}
    </footer>
  );
}
