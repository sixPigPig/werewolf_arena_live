import { Fragment } from "react";

import type { LiveNavStatus, LiveNavStatusTone } from "../liveNavStatus";

type LiveNavStatusBadgeProps = {
  status: LiveNavStatus;
};

const toneClasses = {
  danger: {
    dot: "bg-red-300 shadow-[0_0_10px_rgba(252,165,165,0.55)]",
    text: "text-red-100",
  },
  done: {
    dot: "bg-slate-300 shadow-[0_0_10px_rgba(203,213,225,0.35)]",
    text: "text-slate-200",
  },
  good: {
    dot: "bg-teal-300 shadow-[0_0_10px_rgba(94,234,212,0.55)]",
    text: "text-teal-100",
  },
  neutral: {
    dot: "bg-sky-300 shadow-[0_0_10px_rgba(125,211,252,0.45)]",
    text: "text-sky-100",
  },
  warning: {
    dot: "bg-amber-300 shadow-[0_0_10px_rgba(252,211,77,0.5)]",
    text: "text-amber-100",
  },
} satisfies Record<LiveNavStatusTone, { dot: string; text: string }>;

export function LiveNavStatusBadge({ status }: LiveNavStatusBadgeProps) {
  const tone = toneClasses[status.tone];

  return (
    <div
      className={`live-nav-status flex min-w-0 shrink-0 flex-nowrap items-center gap-x-2 text-xs font-semibold ${tone.text}`}
      data-status-kind={status.kind}
      data-testid="live-nav-status"
    >
      <span
        aria-hidden="true"
        className={`h-2 w-2 shrink-0 rounded-full ${tone.dot}`}
      />
      <span className="shrink-0">{status.label}</span>
      {status.detailItems.map((item) => (
        <Fragment key={item}>
          <span aria-hidden="true" className="text-slate-500">
            ·
          </span>
          <span className="shrink-0 text-slate-300">{item}</span>
        </Fragment>
      ))}
    </div>
  );
}
