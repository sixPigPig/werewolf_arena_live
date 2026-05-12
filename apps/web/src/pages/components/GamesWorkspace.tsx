import { Callout, Heading } from "../../components/ui";
import { withGlassPanel } from "../../components/ui/glass";
import { CreateGameRunForm } from "../../features/games/components/CreateGameRunForm";
import { SessionList } from "../../features/games/components/SessionList";
import type { GameSessionsResponse } from "../../features/games/types";
import type { RefObject } from "react";

type GamesWorkspaceProps = {
  createFormRef: RefObject<HTMLDivElement | null>;
  data: GameSessionsResponse | undefined;
  isError: boolean;
  isPending: boolean;
  isResumeError: boolean;
  resumingSessionId: string | null;
  onResumeSession: (sessionId: string) => void;
};

export function GamesWorkspace({
  createFormRef,
  data,
  isError,
  isPending,
  isResumeError,
  resumingSessionId,
  onResumeSession,
}: GamesWorkspaceProps) {
  return (
    <main
      className="games-workspace-module mx-auto w-full max-w-none px-4 py-8"
      data-testid="games-workspace-module"
    >
      <Heading as="h1" size="6">狼人杀对局复盘</Heading>

      <div className="mt-6" ref={createFormRef}>
        <CreateGameRunForm />
      </div>

      <div className="mt-6">
        {isPending ? (
          <p
            className={withGlassPanel(
              "games-sessions-module rounded-lg p-4 text-sm text-slate-300",
            )}
            data-testid="games-sessions-module"
          >
            正在读取对局列表...
          </p>
        ) : isError ? (
          <p
            className={withGlassPanel(
              "games-sessions-module rounded-lg p-4 text-sm text-red-300",
            )}
            data-testid="games-sessions-module"
          >
            无法读取对局列表
          </p>
        ) : data ? (
          <>
            <SessionList
              onResumeSession={onResumeSession}
              resumingSessionId={resumingSessionId}
              sessions={data.sessions}
            />
            {isResumeError ? (
              <Callout.Root className="mt-2" color="red" size="1" variant="soft">
                <Callout.Text>无法继续对局</Callout.Text>
              </Callout.Root>
            ) : null}
          </>
        ) : null}
      </div>
    </main>
  );
}
