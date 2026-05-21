import type { ReactNode } from "react";

import { withGlassPanel } from "../../../components/ui/glass";
import type { GodViewActionLine, GodViewState } from "../liveGodView";

type GodViewSituationPanelProps = {
  state: GodViewState;
};

export function GodViewSituationPanel({ state }: GodViewSituationPanelProps) {
  return (
    <aside
      className={withGlassPanel(
        "god-view-situation-panel god-view-frame min-w-0 overflow-hidden rounded-lg text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.32)]",
      )}
      data-testid="god-view-situation-panel"
    >
      <SituationSection title="局势总览">
        <div className="space-y-1.5">
          <InfoRow
            label="当前阶段"
            value={`${state.dayNightLabel} · ${state.phaseLabel}`}
          />
          <InfoRow label="当前焦点" value={state.currentSeatLabel} />
          <InfoRow label="存活人数" value={state.aliveLabel} />
          <InfoRow label="胜负条件" value={state.winMode} />
          <div
            className={`rounded-md border px-2.5 py-2 text-xs ${winPressureTone(
              state.winPressure.tone,
            )}`}
          >
            <p className="font-semibold">{state.winPressure.label}</p>
            <p className="mt-1 opacity-80">{state.winPressure.detail}</p>
          </div>
        </div>
      </SituationSection>

      <SituationSection title="阵营进度">
        <div className="space-y-2">
          <ProgressLine
            count={state.progress.wolvesAlive}
            label="狼人存活"
            max={state.progress.totalPlayers}
            tone="danger"
          />
          <ProgressLine
            count={state.progress.godsAlive}
            label="神职存活"
            max={state.progress.totalPlayers}
            tone="info"
          />
          <ProgressLine
            count={state.progress.villagersAlive}
            label="平民存活"
            max={state.progress.totalPlayers}
            tone="success"
          />
        </div>
      </SituationSection>

      <SituationSection title="夜晚行动回顾">
        <div className="space-y-1.5" data-testid="god-view-night-action-order">
          {state.nightActionOrder.map((action) => (
            <NightActionLine
              action={action}
              key={`${action.order}-${action.label}-${action.value}`}
            />
          ))}
        </div>
      </SituationSection>
    </aside>
  );
}

function SituationSection({
  children,
  title,
}: {
  children: ReactNode;
  title: string;
}) {
  return (
    <section className="border-b border-amber-500/15 px-4 py-3 last:border-b-0">
      <h2 className="text-sm font-semibold text-amber-50">{title}</h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-slate-700/45 bg-black/20 px-2.5 py-1.5 text-xs">
      <span className="shrink-0 text-slate-500">{label}</span>
      <span className="min-w-0 text-right text-slate-200">{value}</span>
    </div>
  );
}

function ProgressLine({
  count,
  label,
  max,
  tone,
}: {
  count: number;
  label: string;
  max: number;
  tone: "danger" | "info" | "success";
}) {
  const width = max > 0 ? Math.round((count / max) * 100) : 0;
  const toneClass =
    tone === "danger"
      ? "bg-red-400"
      : tone === "info"
        ? "bg-sky-300"
        : "bg-emerald-400";

  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-semibold text-slate-100">{count}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-black/45">
        <span
          className={`block h-full rounded-full ${toneClass}`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

function NightActionLine({
  action,
}: {
  action: GodViewActionLine & { order: number };
}) {
  return (
    <div
      className="grid grid-cols-[1.5rem_5rem_minmax(0,1fr)] gap-2 rounded-md border border-slate-700/45 bg-black/25 px-2.5 py-1.5 text-xs"
      data-testid="god-view-night-action"
    >
      <span className="text-amber-200">{action.order}</span>
      <span className={actionTone(action.tone)}>{action.label}</span>
      <span className="min-w-0 truncate text-slate-200">{action.value}</span>
    </div>
  );
}

function actionTone(tone: GodViewActionLine["tone"]) {
  if (tone === "danger") {
    return "text-red-200";
  }
  if (tone === "info") {
    return "text-sky-200";
  }
  if (tone === "success") {
    return "text-emerald-200";
  }
  if (tone === "warning") {
    return "text-amber-200";
  }
  return "text-slate-500";
}

function winPressureTone(tone: GodViewState["winPressure"]["tone"]) {
  if (tone === "danger") {
    return "border-red-400/30 bg-red-950/25 text-red-100";
  }
  if (tone === "warning") {
    return "border-amber-300/30 bg-amber-950/25 text-amber-100";
  }
  if (tone === "safe") {
    return "border-emerald-300/30 bg-emerald-950/25 text-emerald-100";
  }
  return "border-slate-600/45 bg-slate-950/40 text-slate-200";
}
