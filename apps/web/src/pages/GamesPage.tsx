import { Button } from "../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AppTopNav } from "../app/AppTopNav";
import { listGames } from "../features/games/api/listGames";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { GamesWorkspace } from "./components/GamesWorkspace";

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
              size="1"
              type="button"
              variant="surface"
            >
              刷新列表
            </Button>
            <Button highContrast onClick={focusCreateForm} size="1" type="button">
              新建对局
            </Button>
          </>
        }
      />
      <GamesWorkspace
        createFormRef={createFormRef}
        data={data}
        isError={isError}
        isPending={isPending}
        isResumeError={resumeMutation.isError}
        onResumeSession={(sessionId) => resumeMutation.mutate(sessionId)}
        resumingSessionId={resumingSessionId}
      />
    </>
  );
}
