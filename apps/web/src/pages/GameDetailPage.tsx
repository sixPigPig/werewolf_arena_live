import { Callout, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { getGameDetail } from "../features/games/api/getGameDetail";
import { DebugPanel } from "../features/games/components/DebugPanel";
import { GameLayout } from "../features/games/components/GameLayout";
import { PlayerPanel } from "../features/games/components/PlayerPanel";
import { RuleSetSummary } from "../features/games/components/RuleSetSummary";
import { RoundTimeline } from "../features/games/components/RoundTimeline";

export function GameDetailPage() {
  const { sessionId } = useParams();
  const [selection, setSelection] = useState<{
    itemId: string;
    sessionId: string;
  } | null>(null);

  const { data, isError, isPending } = useQuery({
    queryKey: ["games", sessionId],
    queryFn: () => getGameDetail(sessionId!),
    enabled: Boolean(sessionId),
  });

  if (isPending) {
    return (
      <main className="mx-auto w-full max-w-4xl px-4 py-8">
        <Text color="gray" size="2">正在读取对局...</Text>
      </main>
    );
  }

  if (isError || !data) {
    return (
      <main className="mx-auto w-full max-w-4xl px-4 py-8">
        <Callout.Root color="red" size="1" variant="soft">
          <Callout.Text>无法读取该对局</Callout.Text>
        </Callout.Root>
      </main>
    );
  }

  const selectedItem =
    selection?.sessionId === data.sessionId
      ? data.debugItems.find((item) => item.id === selection.itemId)
      : undefined;
  const visibleSelectedItem =
    selectedItem ??
    data.debugItems[0] ??
    null;

  return (
    <GameLayout
      debug={<DebugPanel item={visibleSelectedItem} />}
      header={<RuleSetSummary ruleSet={data.ruleSet} />}
      players={<PlayerPanel game={data} />}
      timeline={
        <RoundTimeline
          debugItems={data.debugItems}
          onSelect={(item) =>
            setSelection({ itemId: item.id, sessionId: data.sessionId })
          }
          players={data.players}
          ruleSet={data.ruleSet}
          rounds={data.rounds}
          selectedItem={visibleSelectedItem}
          winner={data.winner}
        />
      }
    />
  );
}
