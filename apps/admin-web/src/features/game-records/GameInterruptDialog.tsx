import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import { isAdminApiError } from "@/api/problem-details";

const DEFAULT_INTERRUPT_REASON = "人工打断异常对局，避免继续消耗 API 额度";

export function GameInterruptDialog({
  error,
  onClose,
  onConfirm,
  opener,
  pending,
  runId,
  sessionId,
}: {
  error: unknown;
  onClose: () => void;
  onConfirm: (reason: string) => void;
  opener: HTMLButtonElement;
  pending: boolean;
  runId: string;
  sessionId: string;
}) {
  const [reason, setReason] = useState(DEFAULT_INTERRUPT_REASON);
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    return () => opener.focus();
  }, [opener]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !pending) {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), textarea:not([disabled])",
      ) ?? [],
    );
    if (focusable.length === 0) return;
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

  const errorMessage = presentGameInterruptError(error);

  return (
    <div className="player-dialog-backdrop">
      <div
        aria-describedby="game-interrupt-description"
        aria-labelledby="game-interrupt-title"
        aria-modal="true"
        className="player-transition-dialog game-delete-dialog game-interrupt-dialog"
        onKeyDown={handleKeyDown}
        ref={dialogRef}
        role="alertdialog"
      >
        <span className="page-kicker">额度保护</span>
        <h2 id="game-interrupt-title">打断对局</h2>
        <p id="game-interrupt-description">
          确认后会阻止新的模型请求，并在运行 Worker 收到信号后关闭当前模型流。
          已被上游接收的请求仍可能产生少量已处理 Token。
        </p>
        <code>{sessionId}</code>
        <small>当前运行 · {runId}</small>
        <label htmlFor="game-interrupt-reason">操作原因</label>
        <textarea
          disabled={pending}
          id="game-interrupt-reason"
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
          value={reason}
        />
        {errorMessage ? (
          <p aria-live="assertive" role="alert">
            {errorMessage}
          </p>
        ) : null}
        <div className="player-dialog-actions">
          <button
            className="admin-secondary-button"
            disabled={pending}
            onClick={onClose}
            ref={cancelRef}
            type="button"
          >
            取消
          </button>
          <button
            className="admin-danger-button"
            disabled={pending || reason.trim().length < 3}
            onClick={() => onConfirm(reason.trim())}
            type="button"
          >
            {pending ? "正在打断..." : "确认打断"}
          </button>
        </div>
      </div>
    </div>
  );
}

function presentGameInterruptError(error: unknown) {
  if (!error) return null;
  if (isAdminApiError(error, 409)) {
    return "该运行已结束或已有打断请求，请取消后刷新。";
  }
  if (isAdminApiError(error, 404)) {
    return "该运行已不存在，请取消后刷新。";
  }
  if (isAdminApiError(error)) {
    const requestId = error.requestId ? ` 请求编号：${error.requestId}` : "";
    return `暂时无法打断对局，请稍后重试。${requestId}`;
  }
  return "暂时无法打断对局，请检查网络后重试。";
}
