import { Button, Callout, Heading } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AppTopNav } from "../app/AppTopNav";
import { listGames } from "../features/games/api/listGames";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { CreateGameRunForm } from "../features/games/components/CreateGameRunForm";
import { SessionList } from "../features/games/components/SessionList";

export function GamesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const createFormRef = useRef<HTMLDivElement>(null);
  const [resumingSessionId, setResumingSessionId] = useState<string | null>(null);
  const { data, isError, isFetching, isPending, refetch } = useQuery({
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
  const focusCreateForm = () => {
    createFormRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    createFormRef.current
      ?.querySelector<HTMLElement>(
        "button, input, [tabindex]:not([tabindex='-1'])",
      )
      ?.focus();
  };

  return (
    <>
      <AppTopNav
        actions={
          <>
            <Button
              color="gray"
              disabled={isFetching}
              loading={isFetching && !isPending}
              onClick={() => void refetch()}
              type="button"
              variant="surface"
            >
              刷新列表
            </Button>
            <Button highContrast onClick={focusCreateForm} type="button">
              新建对局
            </Button>
          </>
        }
      />
      <main className="mx-auto w-full max-w-none px-4 py-8">
        <Heading as="h1" size="6">狼人杀对局复盘</Heading>

        <div className="mt-6" ref={createFormRef}>
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
                <Callout.Root
                  className="mt-2"
                  color="red"
                  size="1"
                  variant="soft"
                >
                  <Callout.Text>无法继续对局</Callout.Text>
                </Callout.Root>
              ) : null}
            </>
          ) : null}
        </div>
      </main>
    </>
  );
}
