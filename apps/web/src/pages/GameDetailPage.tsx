import { Callout, Text } from "../components/ui";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
import { getGameDetail } from "../features/games/api/getGameDetail";
import { GameDetailWorkbench } from "./components/GameDetailWorkbench";

export function GameDetailPage() {
  const { sessionId } = useParams();

  const { data, isError, isFetching, isPending, refetch } = useQuery({
    queryKey: ["games", sessionId],
    queryFn: () => getGameDetail(sessionId!),
    enabled: Boolean(sessionId),
  });
  const topNav = (
    <ArenaGlobalNav
      primaryAction={
        <ArenaNavButton
          color="gray"
          disabled={isFetching}
          loading={isFetching && !isPending}
          onClick={() => void refetch()}
        >
          刷新复盘
        </ArenaNavButton>
      }
      secondaryAction={
        <>
          {sessionId ? (
            <ArenaNavButton to={`/games/playback/${sessionId}`}>
              放到播放台
            </ArenaNavButton>
          ) : null}
          <ArenaNavButton to="/games">返回大厅</ArenaNavButton>
        </>
      }
    />
  );

  if (isPending) {
    return (
      <>
        {topNav}
        <main className="mx-auto w-full max-w-none px-4 py-8">
          <Text color="gray" size="2">正在读取对局...</Text>
        </main>
      </>
    );
  }

  if (isError || !data) {
    return (
      <>
        {topNav}
        <main className="mx-auto w-full max-w-none px-4 py-8">
          <Callout.Root color="red" size="1" variant="soft">
            <Callout.Text>无法读取该对局</Callout.Text>
          </Callout.Root>
        </main>
      </>
    );
  }

  return (
    <>
      {topNav}
      <GameDetailWorkbench game={data} />
    </>
  );
}
