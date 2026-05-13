import { Button, Callout, Text } from "../components/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { AppTopNav } from "../app/AppTopNav";
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
    <AppTopNav
      actions={
        <Button
          color="gray"
          disabled={isFetching}
          loading={isFetching && !isPending}
          onClick={() => void refetch()}
          size="1"
          skin="gothic"
          type="button"
          variant="surface"
        >
          刷新复盘
        </Button>
      }
      utilityActions={
        <Button asChild color="gray" size="1" skin="gothic" variant="surface">
          <Link to="/games">返回大厅</Link>
        </Button>
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
