import type { DebugItem, GameRound, RawPlayer, RuleSetSummary } from "../types";

import { ActionCardGroup } from "./ActionCard";

type NightPhaseProps = {
  round: GameRound;
  players?: RawPlayer[];
  ruleSet?: RuleSetSummary | null;
  items: DebugItem[];
  selectedItem: DebugItem | null;
  onSelect: (item: DebugItem) => void;
};

export function NightPhase({
  round,
  players = [],
  ruleSet = null,
  items,
  selectedItem,
  onSelect,
}: NightPhaseProps) {
  const nightDeathNames = round.night_deaths.map((death) => death.player);
  const nightDeathsText = nightDeathNames.join("、") || "无";
  const hasProtectionRole = hasNightRole(ruleSet, players, isProtectionRole);
  const hasSeerRole = hasNightRole(ruleSet, players, isSeerRole);
  const hasWitchRole = hasNightRole(ruleSet, players, isWitchRole);
  const resultText =
    nightDeathNames.length > 0
      ? `${nightDeathNames.join("、")} 出局`
      : hasWitchRole && round.saved_by_witch
        ? `${round.saved_by_witch} 被女巫救下，平安夜`
        : hasProtectionRole && round.attacked && round.protected === round.attacked
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
          {hasProtectionRole ? (
            <div>
              <dt className="font-medium text-slate-500">守护</dt>
              <dd className="break-words">{round.protected ?? "无"}</dd>
            </div>
          ) : null}
          {hasSeerRole ? (
            <div>
              <dt className="font-medium text-slate-500">查验</dt>
              <dd className="break-words">{round.investigated ?? "无"}</dd>
            </div>
          ) : null}
          {hasWitchRole ? (
            <>
              <div>
                <dt className="font-medium text-slate-500">解药</dt>
                <dd className="break-words">
                  {round.saved_by_witch ?? "未使用"}
                </dd>
              </div>
              <div>
                <dt className="font-medium text-slate-500">毒药</dt>
                <dd className="break-words">{round.poisoned ?? "未使用"}</dd>
              </div>
            </>
          ) : null}
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

      <ActionCardGroup
        ariaLabel="夜晚行动"
        className="mt-3"
        columns={{ initial: "1", sm: "3" }}
        emptyText="无夜晚行动"
        items={items}
        onSelect={onSelect}
        selectedItem={selectedItem}
      />
    </section>
  );
}

function hasNightRole(
  ruleSet: RuleSetSummary | null,
  players: RawPlayer[],
  matches: (role: string) => boolean,
) {
  const ruleRoles = ruleSet?.roles ?? [];
  const hasRoleSource = ruleRoles.length > 0 || players.length > 0;
  const roleNames =
    ruleRoles.length > 0
      ? ruleRoles.filter((role) => role.count > 0).map((role) => role.role)
      : players.map((player) => player.role);

  return !hasRoleSource || roleNames.some(matches);
}

function isProtectionRole(role: string) {
  const normalized = role.toLowerCase();

  return (
    role === "守卫" ||
    role === "医生" ||
    normalized.includes("guard") ||
    normalized.includes("doctor")
  );
}

function isSeerRole(role: string) {
  return role === "预言家" || role.toLowerCase().includes("seer");
}

function isWitchRole(role: string) {
  return role === "女巫" || role.toLowerCase().includes("witch");
}
