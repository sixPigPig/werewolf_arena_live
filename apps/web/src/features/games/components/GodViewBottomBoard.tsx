import type { ReactNode } from "react";

import { withGlassPanel } from "../../../components/ui/glass";
import type { GodViewState } from "../liveGodView";
import { formatVoteCount } from "./voteFormatting";

type GodViewBottomBoardProps = {
  state: GodViewState;
};

export function GodViewBottomBoard({ state }: GodViewBottomBoardProps) {
  return (
    <section
      className={withGlassPanel(
        "god-view-bottom-board god-view-frame overflow-x-auto rounded-lg text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.28)]",
      )}
      data-testid="god-view-bottom-board"
    >
      <div className="grid min-w-[68rem] grid-cols-[1.1fr_1.15fr_1fr_1fr_1.1fr_1fr] divide-x divide-amber-500/15">
        <BottomColumn title="发言顺序">
          <div className="flex flex-wrap gap-1.5">
            {state.speechOrder.length === 0 ? (
              <EmptyText>暂无顺序</EmptyText>
            ) : (
              state.speechOrder.map((name, index) => (
                <span
                  className="rounded-full border border-amber-300/30 bg-black/30 px-2 py-1 text-xs text-slate-200"
                  key={`${name}-${index}`}
                >
                  {index + 1} → {seatLabel(state, name)}
                </span>
              ))
            )}
          </div>
        </BottomColumn>

        <BottomColumn title="票型矩阵">
          <div className="grid grid-cols-[3.2rem_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
            {state.players.length === 0 ? (
              <EmptyText>暂无票型</EmptyText>
            ) : (
              state.players.map((player) => (
                <VotePair
                  key={player.name}
                  source={`${player.seatNumber}号`}
                  target={player.voteTarget ?? "-"}
                />
              ))
            )}
          </div>
        </BottomColumn>

        <BottomColumn title="投票统计">
          <div className="space-y-1.5">
            {state.vote.tallies.length === 0 ? (
              <VoteSkeleton />
            ) : (
              state.vote.tallies.map((tally) => (
                <div key={tally.target}>
                  <div className="flex justify-between gap-2 text-xs">
                    <span className="truncate text-slate-200">
                      {seatLabel(state, tally.target)}
                    </span>
                    <span className="shrink-0 text-amber-100">
                      {formatVoteCount(tally.count)} 票
                    </span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-black/45">
                    <span
                      className="block h-full rounded-full bg-red-400"
                      style={{
                        width: `${Math.min(
                          100,
                          Math.round((tally.count / Math.max(1, state.players.length)) * 100),
                        )}%`,
                      }}
                    />
                  </div>
                </div>
              ))
            )}
          </div>
        </BottomColumn>

        <BottomColumn title="放逐候选排名">
          <div className="space-y-1.5">
            {state.vote.tallies.length === 0 ? (
              <div className="flex items-center justify-between gap-2 rounded-md border border-amber-300/20 bg-black/25 px-2 py-1.5 text-xs">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded border border-amber-300/35 text-amber-100">
                  -
                </span>
                <span className="min-w-0 flex-1 truncate text-slate-100">
                  等待投票
                </span>
                <span className="shrink-0 text-slate-400">0 票</span>
              </div>
            ) : (
              state.vote.tallies.slice(0, 3).map((tally, index) => (
                <div
                  className="flex items-center justify-between gap-2 rounded-md border border-amber-300/20 bg-black/25 px-2 py-1.5 text-xs"
                  key={tally.target}
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded border border-amber-300/35 text-amber-100">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-slate-100">
                    {seatLabel(state, tally.target)}
                  </span>
                  <span className="shrink-0 text-slate-400">
                    {formatVoteCount(tally.count)} 票
                  </span>
                </div>
              ))
            )}
          </div>
        </BottomColumn>

        <BottomColumn title="公开信息">
          <ul className="space-y-1.5 text-xs">
            {state.publicFacts.length === 0 ? (
              <EmptyText>暂无公开信息</EmptyText>
            ) : (
              state.publicFacts.map((fact) => (
                <li
                  className="rounded-md border border-slate-700/45 bg-black/25 px-2 py-1.5 text-slate-200"
                  key={fact}
                >
                  {fact}
                </li>
              ))
            )}
          </ul>
        </BottomColumn>

        <BottomColumn title="本局标记（回放点）">
          <ol className="space-y-1.5 text-xs">
            {state.replayMarks.length === 0 ? (
              <EmptyText>暂无标记</EmptyText>
            ) : (
              state.replayMarks.map((mark) => (
                <li
                  className="grid grid-cols-[2.8rem_minmax(0,1fr)] gap-2 rounded-md border border-slate-700/45 bg-black/25 px-2 py-1.5"
                  key={mark.id}
                >
                  <span className="font-mono text-slate-500">{mark.time}</span>
                  <span className="min-w-0 truncate text-slate-200">
                    {mark.text}
                  </span>
                </li>
              ))
            )}
          </ol>
        </BottomColumn>
      </div>
    </section>
  );
}

function BottomColumn({
  children,
  title,
}: {
  children: ReactNode;
  title: string;
}) {
  return (
    <div className="min-h-40 min-w-0 px-3 py-3">
      <h2 className="mb-2 text-sm font-semibold text-amber-50">{title}</h2>
      {children}
    </div>
  );
}

function EmptyText({ children }: { children: ReactNode }) {
  return <span className="text-xs text-slate-500">{children}</span>;
}

function VoteSkeleton() {
  return (
    <>
      {[1, 2, 3].map((slot) => (
        <div key={slot}>
          <div className="flex justify-between gap-2 text-xs">
            <span className="truncate text-slate-400">候选 {slot}</span>
            <span className="shrink-0 text-slate-500">0 票</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-black/45">
            <span className="block h-full w-0 rounded-full bg-slate-600" />
          </div>
        </div>
      ))}
    </>
  );
}

function VotePair({ source, target }: { source: string; target: string }) {
  return (
    <>
      <span className="text-slate-500">{source}</span>
      <span className="min-w-0 truncate text-slate-200">→ {target}</span>
    </>
  );
}

function seatLabel(state: GodViewState, name: string) {
  const player = state.players.find((item) => item.name === name);
  return player ? `${player.seatNumber}号 ${player.name}` : name;
}
