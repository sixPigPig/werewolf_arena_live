import type { DebugItem, GameRound } from "../types";

import { ActionCard } from "./ActionCard";

type NightPhaseProps = {
  round: GameRound;
  items: DebugItem[];
  selectedItem: DebugItem | null;
  onSelect: (item: DebugItem) => void;
};

export function NightPhase({
  round,
  items,
  selectedItem,
  onSelect,
}: NightPhaseProps) {
  return (
    <section className="border-t border-slate-200 pt-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <h3 className="text-sm font-semibold text-slate-950">夜晚</h3>
        <dl className="grid grid-cols-3 gap-3 text-xs text-slate-600">
          <div>
            <dt className="font-medium text-slate-500">死亡</dt>
            <dd className="break-words">{round.eliminated ?? "无"}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-500">守护</dt>
            <dd className="break-words">{round.protected ?? "无"}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-500">查验</dt>
            <dd className="break-words">{round.investigated ?? "无"}</dd>
          </div>
        </dl>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {items.length === 0 ? (
          <p className="text-sm text-slate-500">无夜晚行动</p>
        ) : (
          items.map((item) => (
            <ActionCard
              item={item}
              key={item.id}
              onSelect={onSelect}
              selected={selectedItem?.id === item.id}
            />
          ))
        )}
      </div>
    </section>
  );
}
