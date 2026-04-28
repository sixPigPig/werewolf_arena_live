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
  const nightDeathNames = round.night_deaths.map((death) => death.player);
  const nightDeathsText = nightDeathNames.join("、") || "无";
  const resultText =
    nightDeathNames.length > 0
      ? `${nightDeathNames.join("、")} 出局`
      : round.saved_by_witch
        ? `${round.saved_by_witch} 被女巫救下，平安夜`
        : round.attacked && round.protected === round.attacked
          ? `${round.attacked} 被守护，平安夜`
          : "平安夜";

  return (
    <section className="border-t border-slate-200 pt-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <h3 className="text-sm font-semibold text-slate-950">夜晚</h3>
        <dl className="grid grid-cols-2 gap-3 text-xs text-slate-600 sm:grid-cols-4 lg:grid-cols-7">
          <div>
            <dt className="font-medium text-slate-500">袭击</dt>
            <dd className="break-words">{round.attacked ?? "无"}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-500">守护</dt>
            <dd className="break-words">{round.protected ?? "无"}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-500">查验</dt>
            <dd className="break-words">{round.investigated ?? "无"}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-500">解药</dt>
            <dd className="break-words">{round.saved_by_witch ?? "未使用"}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-500">毒药</dt>
            <dd className="break-words">{round.poisoned ?? "未使用"}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-500">夜晚死亡</dt>
            <dd className="break-words">{nightDeathsText}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-500">结果</dt>
            <dd className="break-words">{resultText}</dd>
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
