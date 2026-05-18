import type { ReactNode } from "react";

import { withGlassPanel } from "../../../components/ui/glass";
import type {
  GodViewEventLine,
  GodViewState,
} from "../liveGodView";

type GodViewIntelPanelProps = {
  state: GodViewState;
  debugTimeline?: ReactNode;
};

export function GodViewIntelPanel({
  state,
  debugTimeline,
}: GodViewIntelPanelProps) {
  return (
    <aside
      className={withGlassPanel(
        "god-view-intel-panel god-view-frame min-w-0 overflow-hidden rounded-lg text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.32)] xl:max-h-[calc(100vh-8rem)] xl:overflow-auto",
      )}
      data-testid="god-view-intel-panel"
    >
      <IntelSection subtitle="剧情时间线" title="事件记录">
        <EventLines lines={state.eventLines} />
      </IntelSection>

      <IntelSection title="死亡信息">
        {state.nightResolution.tone === "safe" ? (
          <div className="rounded-md border border-emerald-300/25 bg-emerald-950/25 px-3 py-2">
            <p className="text-sm font-semibold text-emerald-100">
              {state.nightResolution.label}
            </p>
            <p className="mt-1 text-xs text-emerald-100/80">
              {state.nightResolution.detail}
            </p>
          </div>
        ) : state.deaths.length === 0 ? (
          <div className="rounded-md border border-slate-600/35 bg-slate-950/35 px-3 py-2">
            <p className="text-sm font-semibold text-slate-200">
              {state.nightResolution.label}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              {state.isPeacefulNight ? "平安夜" : state.nightResolution.detail}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {state.deaths.map((death) => (
              <div
                className="rounded-md border border-red-400/25 bg-red-950/20 px-3 py-2"
                key={`${death.player}-${death.time}-${death.cause}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-red-100">
                    {death.player}
                  </span>
                  <span className="shrink-0 text-[11px] text-red-200">
                    {death.cause}
                  </span>
                </div>
                <div className="mt-1 flex justify-between gap-2 text-[11px] text-slate-400">
                  <span>死亡时间：{death.time}</span>
                  <span>{death.publicText}</span>
                </div>
                <p className="mt-1 text-[11px] text-slate-500">
                  遗言资格：待规则结算
                </p>
              </div>
            ))}
          </div>
        )}
      </IntelSection>

      <IntelSection title="身份线索（上帝视角）">
        <div className="space-y-1.5">
          {state.players.length === 0 ? (
            <p className="text-xs text-slate-500">暂无身份线索</p>
          ) : (
            state.players.slice(0, 6).map((player) => (
              <div
                className="flex items-center justify-between gap-2 rounded-md border border-slate-700/45 bg-black/25 px-2.5 py-1.5 text-xs"
                key={player.name}
              >
                <span className="min-w-0 truncate text-slate-200">
                  {player.seatNumber} 号 {player.name}
                </span>
                <span className="shrink-0 text-amber-100">
                  {player.role} · {player.identityGroup}
                </span>
              </div>
            ))
          )}
        </div>
      </IntelSection>

      <IntelSection title="警长信息">
        {state.sheriffRuleState.enabled ? (
          <div className="space-y-1.5 text-xs text-slate-300">
            <InfoRow label="当前警长" value={state.sheriff.current ?? "未产生"} />
            <InfoRow label="警徽流向" value={state.sheriff.badgeFlow} />
            <InfoRow label="归票目标" value={state.sheriff.callTarget ?? "暂无"} />
            <InfoRow
              label="警上玩家"
              value={
                state.sheriff.candidates.length > 0
                  ? state.sheriff.candidates.join("、")
                  : "暂无"
              }
            />
            <InfoRow
              label="竞选票型"
              value={
                state.sheriff.voters.length > 0
                  ? state.sheriff.voters.join("、")
                  : "暂无"
              }
            />
          </div>
        ) : (
          <p className="rounded-md border border-slate-600/45 bg-slate-950/55 px-3 py-2 text-xs text-slate-300">
            {state.sheriffRuleState.label}
          </p>
        )}
      </IntelSection>

      {debugTimeline ? (
        <details className="border-t border-amber-500/15">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-300">
            调试事件
          </summary>
          {debugTimeline}
        </details>
      ) : null}
    </aside>
  );
}

function IntelSection({
  children,
  subtitle,
  title,
}: {
  children: ReactNode;
  subtitle?: string;
  title: string;
}) {
  return (
    <section className="border-b border-amber-500/15 px-4 py-3 last:border-b-0">
      <h2 className="text-sm font-semibold text-amber-50">{title}</h2>
      {subtitle ? (
        <p className="mt-1 text-xs text-slate-400">{subtitle}</p>
      ) : null}
      <div className="mt-2">{children}</div>
    </section>
  );
}

function EventLines({ lines }: { lines: GodViewEventLine[] }) {
  if (lines.length === 0) {
    return <p className="text-xs text-slate-500">暂无事件</p>;
  }
  return (
    <ol className="space-y-1.5">
      {lines.map((line) => (
        <li
          className="grid grid-cols-[3rem_minmax(0,1fr)] gap-2 text-xs"
          key={line.id}
        >
          <span className="font-mono text-slate-500">{line.time}</span>
          <span className={eventTone(line.tone)}>{line.text}</span>
        </li>
      ))}
    </ol>
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

function eventTone(tone: GodViewEventLine["tone"]) {
  if (tone === "danger") {
    return "min-w-0 text-red-100";
  }
  if (tone === "info") {
    return "min-w-0 text-sky-100";
  }
  if (tone === "success") {
    return "min-w-0 text-emerald-100";
  }
  if (tone === "warning") {
    return "min-w-0 text-amber-100";
  }
  return "min-w-0 text-slate-300";
}
