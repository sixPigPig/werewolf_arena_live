import { personalityLabel } from "../playerProfileOptions";
import { summarizeLineup } from "../lineupUtils";
import type { PlayerConfig, VirtualPlayerProfile } from "../types";

type LineupSummaryProps = {
  configs: PlayerConfig[];
  playerCount: number;
  profiles: VirtualPlayerProfile[];
};

export function LineupSummary({
  configs,
  playerCount,
  profiles,
}: LineupSummaryProps) {
  const summary = summarizeLineup(configs, profiles, playerCount);
  const modelText = formatCounts(summary.modelCounts);
  const personalityText = formatCounts(
    summary.personalityCounts.map((item) => ({
      ...item,
      label: personalityLabel(item.label),
    })),
  );

  return (
    <section aria-label="阵容预览" className="lineup-summary">
      <div className="lineup-summary-primary">
        <span className="lineup-summary-stat">已选 {summary.assignedCount} / {playerCount}</span>
        <span className="lineup-summary-stat">收藏玩家 {summary.favoriteCount}</span>
        {summary.invalidSeatCount > 0 ? (
          <span className="lineup-summary-warning">
            异常席位 {summary.invalidSeatCount}
          </span>
        ) : null}
      </div>
      <div className="lineup-summary-secondary">
        <span>
          {summary.emptySeatCount > 0
            ? "空席将由系统随机补齐"
            : "阵容已安排完整"}
        </span>
        {modelText ? <span>模型 {modelText}</span> : null}
        {personalityText ? <span>性格 {personalityText}</span> : null}
      </div>
    </section>
  );
}

function formatCounts(counts: { label: string; count: number }[]) {
  return counts.map((item) => `${item.label} ${item.count}`).join(" · ");
}
