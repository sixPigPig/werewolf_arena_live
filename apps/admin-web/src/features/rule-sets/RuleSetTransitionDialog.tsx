import { type FormEvent, useId, useState } from "react";
import type { AdminRuleSet } from "./types";

type Props = {
  title: string;
  description: string;
  confirmLabel: string;
  pendingLabel: string;
  reasonMinLength: number;
  reasonMaxLength: number;
  pending: boolean;
  error: string | null;
  candidates?: AdminRuleSet[];
  requiresReplacement?: boolean;
  candidatesPending?: boolean;
  candidatesError?: boolean;
  onCancel: () => void;
  onConfirm: (reason: string, replacementId: string | null) => void;
};

export default function RuleSetTransitionDialog({ title, description, confirmLabel, pendingLabel, reasonMinLength, reasonMaxLength, pending, error, candidates = [], requiresReplacement = false, candidatesPending = false, candidatesError = false, onCancel, onConfirm }: Props) {
  const titleId = useId(); const descriptionId = useId(); const reasonErrorId = useId();
  const [reason, setReason] = useState(""); const [replacementId, setReplacementId] = useState(""); const [reasonError, setReasonError] = useState<string | null>(null);
  const noCandidate = requiresReplacement && !candidatesPending && !candidatesError && candidates.length === 0;

  function submit(event: FormEvent) {
    event.preventDefault(); if (pending || candidatesPending || candidatesError || noCandidate) return;
    const cleaned = reason.trim();
    if (cleaned.length < reasonMinLength || cleaned.length > reasonMaxLength) { setReasonError(`操作原因需为 ${reasonMinLength}–${reasonMaxLength} 个字符`); return; }
    if (requiresReplacement && !replacementId) return;
    setReasonError(null); onConfirm(cleaned, replacementId || null);
  }

  return <section aria-describedby={descriptionId} aria-labelledby={titleId} aria-modal="true" role="dialog">
    <h2 id={titleId}>{title}</h2><p id={descriptionId}>{description}</p>
    <form onSubmit={submit}>
      {requiresReplacement ? <label><span>替代默认规则</span><select aria-label="替代默认规则" disabled={pending || candidatesPending || candidatesError || noCandidate} onChange={(event) => setReplacementId(event.target.value)} value={replacementId}><option value="">请选择已发布规则</option>{candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.draft_revision?.config?.name ?? candidate.published_revision?.config?.name ?? candidate.id}</option>)}</select></label> : null}
      {candidatesPending ? <p role="status">正在读取已发布规则...</p> : null}
      {candidatesError ? <p role="alert">无法读取已发布规则，请稍后重试。</p> : null}
      {noCandidate ? <p role="alert">没有可用的替代规则，请先发布另一套规则。</p> : null}
      <label><span>操作原因</span><textarea aria-describedby={reasonError ? reasonErrorId : undefined} aria-invalid={Boolean(reasonError)} aria-label="操作原因" disabled={pending} maxLength={reasonMaxLength} minLength={reasonMinLength} onChange={(event) => { setReason(event.target.value); setReasonError(null); }} value={reason} /></label>
      {reasonError ? <p id={reasonErrorId} role="alert">{reasonError}</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      <button disabled={pending} onClick={onCancel} type="button">取消</button>
      <button disabled={pending || candidatesPending || candidatesError || noCandidate || (requiresReplacement && !replacementId)} type="submit">{pending ? pendingLabel : confirmLabel}</button>
    </form>
  </section>;
}
