import { useQuery } from "@tanstack/react-query";

import { listGames } from "../features/games/api/listGames";
import { SessionList } from "../features/games/components/SessionList";

export function GamesPage() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["games"],
    queryFn: listGames,
  });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="text-2xl font-semibold text-slate-950">狼人杀对局复盘</h1>

      <div className="mt-6">
        {isLoading ? (
          <p className="text-sm text-slate-600">正在读取对局列表...</p>
        ) : null}
        {error ? (
          <p className="text-sm text-red-700">无法读取对局列表</p>
        ) : null}
        {data ? <SessionList sessions={data.sessions} /> : null}
      </div>
    </main>
  );
}
