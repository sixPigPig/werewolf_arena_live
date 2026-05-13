import { Callout, Heading } from "../components/ui";
import { withGlassPanel } from "../components/ui/glass";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
import { listGames } from "../features/games/api/listGames";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { SessionList } from "../features/games/components/SessionList";

const HISTORY_PAGE_SIZE = 7;

export function GameHistoryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [historyPage, setHistoryPage] = useState(1);
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
  const sessions = data?.sessions ?? [];
  const totalPages = Math.max(1, Math.ceil(sessions.length / HISTORY_PAGE_SIZE));
  const currentPage = Math.min(historyPage, totalPages);
  const pageStart = (currentPage - 1) * HISTORY_PAGE_SIZE;
  const visibleSessions = sessions.slice(pageStart, pageStart + HISTORY_PAGE_SIZE);
  const refreshSessions = () => {
    setHistoryPage(1);
    void refetch();
  };

  return (
    <>
      <ArenaGlobalNav
        primaryAction={
          <ArenaNavButton
            color="red"
            disabled={isFetching}
            loading={isFetching && !isPending}
            onClick={refreshSessions}
          >
            刷新列表
          </ArenaNavButton>
        }
        secondaryAction={<ArenaNavButton to="/games">返回大厅</ArenaNavButton>}
        tone="ornate"
      />
      <main
        className="games-history-module history-page-shell mx-auto w-full max-w-none px-4 py-8"
        data-testid="games-history-module"
      >
        <header className="history-page-header">
          <span aria-hidden="true" className="history-title-rule" />
          <span aria-hidden="true" className="history-title-gem" />
          <Heading as="h1" className="history-page-title" size="6">
            对局历史
          </Heading>
          <span aria-hidden="true" className="history-title-rule" />
        </header>

        <section aria-label="对局历史列表" className="history-board">
          <span aria-hidden="true" className="history-board-crest" />
          {isPending ? (
            <p
              className={withGlassPanel(
                "games-sessions-module history-state-panel text-sm text-slate-300",
              )}
              data-testid="games-sessions-module"
            >
              正在读取对局列表...
            </p>
          ) : isError ? (
            <p
              className={withGlassPanel(
                "games-sessions-module history-state-panel text-sm text-red-300",
              )}
              data-testid="games-sessions-module"
            >
              无法读取对局列表
            </p>
          ) : data ? (
            <>
              <SessionList
                onResumeSession={(sessionId) => resumeMutation.mutate(sessionId)}
                resumingSessionId={resumingSessionId}
                sessions={visibleSessions}
                variant="ornate"
              />
              <HistoryPagination
                currentPage={currentPage}
                onPageChange={setHistoryPage}
                totalPages={totalPages}
              />
              {resumeMutation.isError ? (
                <Callout.Root className="mt-2" color="red" size="1" variant="soft">
                  <Callout.Text>无法继续对局</Callout.Text>
                </Callout.Root>
              ) : null}
            </>
          ) : null}
        </section>
      </main>
    </>
  );
}

type HistoryPaginationProps = {
  currentPage: number;
  onPageChange: (page: number) => void;
  totalPages: number;
};

function HistoryPagination({
  currentPage,
  onPageChange,
  totalPages,
}: HistoryPaginationProps) {
  if (totalPages <= 1) {
    return null;
  }

  const pages = getPaginationItems(currentPage, totalPages);

  return (
    <nav aria-label="对局历史分页" className="history-pagination">
      <button
        aria-label="上一页"
        className="history-page-control"
        disabled={currentPage === 1}
        onClick={() => onPageChange(currentPage - 1)}
        type="button"
      >
        {"<"}
      </button>
      {pages.map((item) =>
        item.type === "ellipsis" ? (
          <span
            aria-hidden="true"
            className="history-page-ellipsis"
            key={item.key}
          >
            ...
          </span>
        ) : (
          <button
            aria-current={item.page === currentPage ? "page" : undefined}
            className="history-page-number"
            key={item.page}
            onClick={() => onPageChange(item.page)}
            type="button"
          >
            {item.page}
          </button>
        ),
      )}
      <button
        aria-label="下一页"
        className="history-page-control"
        disabled={currentPage === totalPages}
        onClick={() => onPageChange(currentPage + 1)}
        type="button"
      >
        {">"}
      </button>
    </nav>
  );
}

type PaginationItem =
  | { page: number; type: "page" }
  | { key: string; type: "ellipsis" };

function getPaginationItems(
  currentPage: number,
  totalPages: number,
): PaginationItem[] {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => ({
      page: index + 1,
      type: "page",
    }));
  }

  if (currentPage <= 3) {
    return [
      { page: 1, type: "page" },
      { page: 2, type: "page" },
      { page: 3, type: "page" },
      { key: "end", type: "ellipsis" },
      { page: totalPages, type: "page" },
    ];
  }

  if (currentPage >= totalPages - 2) {
    return [
      { page: 1, type: "page" },
      { key: "start", type: "ellipsis" },
      { page: totalPages - 2, type: "page" },
      { page: totalPages - 1, type: "page" },
      { page: totalPages, type: "page" },
    ];
  }

  return [
    { page: 1, type: "page" },
    { key: "start", type: "ellipsis" },
    { page: currentPage, type: "page" },
    { key: "end", type: "ellipsis" },
    { page: totalPages, type: "page" },
  ];
}
