import Input, { type InputRef } from "antd/es/input";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";

export function PlayerTransitionDialog({
  actionLabel,
  description,
  error,
  onClose,
  onConfirm,
  pending,
  title,
}: {
  actionLabel: string;
  description: string;
  error: string | null;
  onClose: () => void;
  onConfirm: (reason: string) => void;
  pending: boolean;
  title: string;
}) {
  const [reason, setReason] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const reasonRef = useRef<InputRef>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    reasonRef.current?.focus();
    return () => previouslyFocused?.focus();
  }, []);

  useEffect(() => {
    if (error) {
      reasonRef.current?.focus();
    }
  }, [error]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = reason.trim();
    if (normalized.length < 3 || normalized.length > 500) {
      setValidationError("操作原因需为 3 到 500 个字符");
      reasonRef.current?.focus();
      return;
    }
    setValidationError(null);
    onConfirm(normalized);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !pending) {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), textarea:not([disabled])",
      ) ?? [],
    );
    if (focusable.length === 0) {
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1) ?? first;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="player-dialog-backdrop">
      <div
        aria-describedby="player-transition-description"
        aria-labelledby="player-transition-title"
        aria-modal="true"
        className="player-transition-dialog"
        onKeyDown={handleKeyDown}
        ref={dialogRef}
        role="alertdialog"
      >
        <form onSubmit={submit}>
          <span className="page-kicker">LIFECYCLE ACTION</span>
          <h2 id="player-transition-title">{title}</h2>
          <p id="player-transition-description">{description}</p>
          <label>
            <span>操作原因</span>
            <Input.TextArea
              aria-label="操作原因"
              aria-describedby="transition-reason-help transition-reason-error"
              aria-invalid={Boolean(validationError || error)}
              disabled={pending}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              ref={reasonRef}
              rows={4}
              status={validationError || error ? "error" : undefined}
              value={reason}
            />
          </label>
          <small id="transition-reason-help">3–500 个字符，将写入审计日志。</small>
          {validationError || error ? (
            <p aria-live="assertive" id="transition-reason-error" role="alert">
              {validationError ?? error}
            </p>
          ) : null}
          <div className="player-dialog-actions">
            <button
              className="admin-secondary-button"
              disabled={pending}
              onClick={onClose}
              type="button"
            >
              取消
            </button>
            <button
              className="admin-danger-button"
              disabled={pending}
              type="submit"
            >
              {pending ? "正在提交..." : actionLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
