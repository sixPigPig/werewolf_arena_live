import type { DebugItem } from "../types";

type ActionCardProps = {
  item: DebugItem;
  selected: boolean;
  onSelect: (item: DebugItem) => void;
};

export function ActionCard({ item, selected, onSelect }: ActionCardProps) {
  return (
    <button
      aria-label={`${item.title} ${item.actor} 选择 ${item.choice ?? "无"}`}
      className={`w-full rounded border px-3 py-2 text-left text-sm transition focus:outline-none focus:ring-2 focus:ring-slate-500 ${
        selected
          ? "border-slate-900 bg-slate-900 text-white"
          : "border-slate-200 bg-white text-slate-800 hover:border-slate-400 hover:bg-slate-50"
      }`}
      onClick={() => onSelect(item)}
      type="button"
    >
      <span className="block font-medium">{item.title}</span>
      <span
        className={`mt-1 block break-words text-xs ${
          selected ? "text-slate-200" : "text-slate-500"
        }`}
      >
        {item.actor} 选择 {item.choice ?? "无"}
      </span>
    </button>
  );
}
