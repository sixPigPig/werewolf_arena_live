import { useState } from "react";

import { DebugPanel } from "../../features/games/components/DebugPanel";
import { GameLayout } from "../../features/games/components/GameLayout";
import { PlayerPanel } from "../../features/games/components/PlayerPanel";
import { RuleSetSummary } from "../../features/games/components/RuleSetSummary";
import { RoundTimeline } from "../../features/games/components/RoundTimeline";
import type { GameReplay } from "../../features/games/types";

type GameDetailWorkbenchProps = {
  game: GameReplay;
};

export function GameDetailWorkbench({ game }: GameDetailWorkbenchProps) {
  const [selection, setSelection] = useState<{
    itemId: string;
    sessionId: string;
  } | null>(null);
  const selectedItem =
    selection?.sessionId === game.sessionId
      ? game.debugItems.find((item) => item.id === selection.itemId)
      : undefined;
  const visibleSelectedItem = selectedItem ?? game.debugItems[0] ?? null;

  return (
    <GameLayout
      debug={<DebugPanel item={visibleSelectedItem} />}
      header={<RuleSetSummary ruleSet={game.ruleSet} />}
      players={<PlayerPanel game={game} />}
      timeline={
        <RoundTimeline
          debugItems={game.debugItems}
          onSelect={(item) =>
            setSelection({ itemId: item.id, sessionId: game.sessionId })
          }
          players={game.players}
          ruleSet={game.ruleSet}
          rounds={game.rounds}
          selectedItem={visibleSelectedItem}
          winner={game.winner}
        />
      }
    />
  );
}
