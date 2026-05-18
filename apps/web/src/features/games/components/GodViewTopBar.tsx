import { withGlassPanel } from "../../../components/ui/glass";
import type { GodViewState } from "../liveGodView";

type GodViewTopBarProps = {
  state: GodViewState;
};

export function GodViewTopBar({ state }: GodViewTopBarProps) {
  return (
    <section
      className={withGlassPanel(
        "god-view-top-bar god-view-frame overflow-hidden rounded-lg px-3 py-2 text-slate-100",
      )}
      data-testid="god-view-top-bar"
    >
      <div
        className="god-view-stage-strip grid grid-cols-2 gap-1 rounded-md border border-amber-300/35 px-3 py-2 text-[11px] text-slate-300 shadow-[0_16px_45px_rgba(0,0,0,0.24)] sm:grid-cols-4 xl:grid-cols-7"
        data-testid="god-view-stage-strip"
      >
        <TopStat label="房间名" value={state.boardName} />
        <TopStat label="天夜" value={state.dayNightLabel} />
        <TopStat label="阶段" value={state.phaseLabel} />
        <TopStat label="发言席" value={state.currentSeatLabel} />
        <TopStat label="倒计时" value={state.countdownLabel} />
        <TopStat label="存活" value={state.aliveLabel} />
        <TopStat label="胜负条件" value={state.winMode} />
      </div>
    </section>
  );
}

function TopStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="relative min-w-0 border-l border-amber-300/10 pl-2 first:border-l-0 first:pl-0">
      <span className="block text-[10px] text-amber-200/60">{label}</span>
      <span className="block truncate font-semibold text-amber-50">
        {value}
      </span>
    </div>
  );
}
