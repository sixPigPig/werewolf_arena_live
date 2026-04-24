import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { getGameDetail } from "../features/games/api/getGameDetail";
import { DebugPanel } from "../features/games/components/DebugPanel";
import { GameLayout } from "../features/games/components/GameLayout";
import { PlayerPanel } from "../features/games/components/PlayerPanel";
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
        <p className="text-sm text-slate-600">正在读取对局...</p>
      </main>
    );
  }

  if (isError || !data) {
    return (
      <main className="mx-auto w-full max-w-4xl px-4 py-8">
        <p className="text-sm text-red-700">无法读取该对局</p>
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
      players={<PlayerPanel game={data} />}
      timeline={
        <RoundTimeline
          debugItems={data.debugItems}
          onSelect={(item) =>
            setSelection({ itemId: item.id, sessionId: data.sessionId })
          }
          rounds={data.rounds}
          selectedItem={visibleSelectedItem}
        />
      }
    />
  );
}
