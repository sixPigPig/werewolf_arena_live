import { Text } from "../components/ui";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
import { getGamePlayback } from "../features/games/api/getGamePlayback";

export function GamePlaybackPage() {
  const { sessionId } = useParams();
  const { data, isError, isPending } = useQuery({
    queryKey: ["game-playback", sessionId],
    queryFn: () => getGamePlayback(sessionId!),
    enabled: Boolean(sessionId),
  });

  return (
    <>
      <ArenaGlobalNav
        primaryAction={<ArenaNavButton to={`/games/${sessionId}`}>查看复盘</ArenaNavButton>}
        secondaryAction={<ArenaNavButton to="/games/history">返回历史</ArenaNavButton>}
      />
      <main className="min-h-screen px-4 py-8 text-slate-100">
        <h1 className="sr-only">历史回放</h1>
        {isPending ? <Text className="text-slate-300">正在准备历史播放台...</Text> : null}
        {isError ? <Text className="text-red-300">无法读取历史回放</Text> : null}
        {data ? <Text className="text-slate-300">历史回放</Text> : null}
      </main>
    </>
  );
}
