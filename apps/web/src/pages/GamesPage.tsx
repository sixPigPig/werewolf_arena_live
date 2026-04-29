import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { listGames } from "../features/games/api/listGames";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { CreateGameRunForm } from "../features/games/components/CreateGameRunForm";
import { SessionList } from "../features/games/components/SessionList";

export function GamesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [resumingSessionId, setResumingSessionId] = useState<string | null>(null);
  const { data, isError, isPending } = useQuery({
    queryKey: ["games"],
    queryFn: listGames,
  });
  const resumeMutation = useMutation({
    mutationFn: resumeGameRun,
    onMutate: (sessionId) => {
      setResumingSessionId(sessionId);
    },
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["games"] });
      navigate(`/games/live/${run.run_id}`);
    },
    onSettled: () => {
      setResumingSessionId(null);
    },
  });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="text-2xl font-semibold text-slate-950">狼人杀对局复盘</h1>

      <div className="mt-6">
        <CreateGameRunForm />
      </div>

      <div className="mt-6">
        {isPending ? (
          <p className="text-sm text-slate-600">正在读取对局列表...</p>
        ) : isError ? (
          <p className="text-sm text-red-700">无法读取对局列表</p>
        ) : data ? (
          <>
            <SessionList
              onResumeSession={(sessionId) => resumeMutation.mutate(sessionId)}
              resumingSessionId={resumingSessionId}
              sessions={data.sessions}
            />
            {resumeMutation.isError ? (
              <p className="mt-2 text-sm text-red-700">无法继续对局</p>
            ) : null}
          </>
        ) : null}
      </div>
    </main>
  );
}
