import type { ReactNode } from "react";
import { useMemo, useState } from "react";

import { withGlassPanel } from "../../../components/ui/glass";
import type {
  LiveDebugStateDiff,
  LiveDebugTrace,
  LiveDebugTraceNode,
  LiveDebugTraceNodeKind,
  LiveDebugTraceStatus,
} from "../liveDebugTrace";

type LiveDebugTraceRailProps = {
  traces: LiveDebugTrace[];
  selectedTraceId?: string | null;
  onSelectTrace?: (trace: LiveDebugTrace | null) => void;
};

const TRACE_NODE_KINDS: LiveDebugTraceNodeKind[] = [
  "request",
  "model",
  "parsed",
  "state",
  "stage",
];

const STATUS_LABELS: Record<LiveDebugTraceStatus, string> = {
  error: "异常",
  ok: "OK",
  system: "系统",
  warning: "需关注",
};

export function LiveDebugTraceRail({
  onSelectTrace,
  selectedTraceId,
  traces,
}: LiveDebugTraceRailProps) {
  const [showIssuesOnly, setShowIssuesOnly] = useState(false);
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null);

  const visibleTraces = useMemo(
    () =>
      showIssuesOnly
        ? traces.filter(
            (trace) => trace.status === "warning" || trace.status === "error",
          )
        : traces,
    [showIssuesOnly, traces],
  );

  const activeTraceId = selectedTraceId ?? expandedTraceId;

  return (
    <aside
      className={withGlassPanel(
        "live-debug-trace-rail min-w-0 overflow-hidden rounded-lg text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.3)]",
      )}
      data-testid="live-debug-trace-rail"
    >
      <header className="flex items-start justify-between gap-3 border-b border-amber-500/15 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-amber-50">Action Trace</h2>
          <p className="mt-1 text-xs text-slate-400">
            按行动聚合 · 当前 {visibleTraces.length} 条
          </p>
        </div>
        <button
          aria-pressed={showIssuesOnly}
          className={`shrink-0 rounded-md border px-2.5 py-1 text-xs font-semibold transition ${
            showIssuesOnly
              ? "border-amber-300/45 bg-amber-400/15 text-amber-50"
              : "border-slate-600/45 bg-slate-950/35 text-slate-300 hover:border-amber-300/35 hover:text-amber-50"
          }`}
          onClick={() => setShowIssuesOnly((current) => !current)}
          type="button"
        >
          只看异常
        </button>
      </header>

      {visibleTraces.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-slate-500">
          等待可追踪行动...
        </div>
      ) : (
        <ol className="max-h-[min(56rem,calc(100vh-12rem))] space-y-2 overflow-auto p-3">
          {visibleTraces.map((trace) => (
            <TraceCard
              expanded={activeTraceId === trace.id}
              key={trace.id}
              onSelect={() => {
                const nextTrace = activeTraceId === trace.id ? null : trace;
                setExpandedTraceId(nextTrace?.id ?? null);
                onSelectTrace?.(nextTrace);
              }}
              trace={trace}
            />
          ))}
        </ol>
      )}
    </aside>
  );
}

function TraceCard({
  expanded,
  onSelect,
  trace,
}: {
  expanded: boolean;
  onSelect: () => void;
  trace: LiveDebugTrace;
}) {
  const summary = trace.impactSummary.length > 0
    ? trace.impactSummary
    : trace.warnings.length > 0
      ? trace.warnings
      : ["暂无影响摘要"];

  return (
    <li
      className={`rounded-md border bg-slate-950/35 ${cardTone(trace.status)}`}
      data-testid={`live-debug-trace-card-${trace.id}`}
    >
      <button
        aria-expanded={expanded}
        className="w-full px-3 py-3 text-left"
        onClick={onSelect}
        type="button"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-mono text-[11px] text-slate-500">
              {eventRange(trace.eventIds)}
            </div>
            <div className="mt-1 break-words text-sm font-semibold text-slate-100">
              {trace.title}
            </div>
          </div>
          <span
            className={`shrink-0 rounded border px-2 py-0.5 text-[11px] font-semibold ${statusTone(
              trace.status,
            )}`}
          >
            {STATUS_LABELS[trace.status]}
          </span>
        </div>

        <NodeStrip nodes={trace.nodes} />

        <div className="mt-2 space-y-1">
          {summary.slice(0, 3).map((item, index) => (
            <p
              className="break-words text-xs leading-5 text-slate-300"
              key={`${item}-${index}`}
            >
              {item}
            </p>
          ))}
        </div>
      </button>

      {expanded ? <TraceDetails trace={trace} /> : null}
    </li>
  );
}

function NodeStrip({ nodes }: { nodes: LiveDebugTraceNode[] }) {
  return (
    <div className="mt-3 grid grid-cols-5 gap-1.5">
      {TRACE_NODE_KINDS.map((kind) => {
        const node = nodes.find((item) => item.kind === kind);
        return (
          <span
            aria-label={`${kind}: ${node?.label ?? "未记录"} (${
              node?.status ?? "muted"
            })`}
            className={`min-w-0 rounded border px-1.5 py-1 text-center text-[10px] font-semibold uppercase tracking-normal ${nodeTone(
              node?.status ?? "muted",
            )}`}
            data-testid="live-debug-trace-node"
            key={kind}
            title={node?.label ?? `${kind} 未记录`}
          >
            {kind}
          </span>
        );
      })}
    </div>
  );
}

function TraceDetails({ trace }: { trace: LiveDebugTrace }) {
  return (
    <div className="space-y-3 border-t border-slate-700/50 px-3 pb-3 pt-1">
      {trace.warnings.length > 0 ? (
        <DetailBlock title="异常提示" tone="warning">
          <ul className="space-y-1">
            {trace.warnings.map((warning, index) => (
              <li className="break-words" key={`${warning}-${index}`}>
                {warning}
              </li>
            ))}
          </ul>
        </DetailBlock>
      ) : null}

      <DetailBlock title="状态变化">
        {trace.stateDiff.length === 0 ? (
          <p>无状态变化</p>
        ) : (
          <div className="space-y-2">
            {trace.stateDiff.map((diff, index) => (
              <StateDiffLine diff={diff} key={`${diff.label}-${index}`} />
            ))}
          </div>
        )}
      </DetailBlock>

      <DetailBlock title="Prompt">
        <pre className="whitespace-pre-wrap break-words">
          {trace.prompt || "无内容"}
        </pre>
      </DetailBlock>

      <DetailBlock title="Raw response">
        <pre className="whitespace-pre-wrap break-words">
          {trace.rawResponse || "无内容"}
        </pre>
      </DetailBlock>

      <DetailBlock title="Parsed result">
        <pre className="whitespace-pre-wrap break-words">
          {formatJsonLike(trace.parsed)}
        </pre>
      </DetailBlock>

      <DetailBlock title="Payload JSON">
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words">
          {formatJsonLike(trace.payloads)}
        </pre>
      </DetailBlock>
    </div>
  );
}

function DetailBlock({
  children,
  title,
  tone = "default",
}: {
  children: ReactNode;
  title: string;
  tone?: "default" | "warning";
}) {
  return (
    <section
      className={`rounded-md border px-3 py-2 text-xs leading-5 ${
        tone === "warning"
          ? "border-amber-300/25 bg-amber-950/20 text-amber-100"
          : "border-slate-700/45 bg-black/25 text-slate-300"
      }`}
    >
      <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-normal text-slate-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

function StateDiffLine({ diff }: { diff: LiveDebugStateDiff }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[5rem_minmax(0,1fr)]">
      <span className="font-semibold text-slate-400">{diff.label}</span>
      <span className="min-w-0 break-words text-slate-200">
        {diff.before} → {diff.after}
      </span>
    </div>
  );
}

function eventRange(eventIds: number[]) {
  if (eventIds.length === 0) {
    return "#-";
  }

  const first = eventIds[0];
  const last = eventIds[eventIds.length - 1];
  return first === last ? `#${first}` : `#${first}-${last}`;
}

function formatJsonLike(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "无内容";
  }

  if (typeof value === "string") {
    return value;
  }

  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function cardTone(status: LiveDebugTraceStatus) {
  if (status === "error") {
    return "border-red-400/30";
  }
  if (status === "warning") {
    return "border-amber-300/30";
  }
  if (status === "system") {
    return "border-slate-500/30";
  }
  return "border-emerald-300/20";
}

function statusTone(status: LiveDebugTraceStatus) {
  if (status === "error") {
    return "border-red-300/35 bg-red-950/35 text-red-100";
  }
  if (status === "warning") {
    return "border-amber-300/35 bg-amber-950/35 text-amber-100";
  }
  if (status === "system") {
    return "border-slate-400/30 bg-slate-900/60 text-slate-300";
  }
  return "border-emerald-300/30 bg-emerald-950/30 text-emerald-100";
}

function nodeTone(status: LiveDebugTraceNode["status"]) {
  if (status === "error") {
    return "border-red-300/35 bg-red-950/35 text-red-100";
  }
  if (status === "warning") {
    return "border-amber-300/35 bg-amber-950/30 text-amber-100";
  }
  if (status === "ok") {
    return "border-emerald-300/25 bg-emerald-950/25 text-emerald-100";
  }
  return "border-slate-700/45 bg-slate-950/45 text-slate-500";
}
