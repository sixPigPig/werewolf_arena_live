import { Heading } from "../../components/ui";
import { CreateGameRunForm } from "../../features/games/components/CreateGameRunForm";
import type { RefObject } from "react";

type GamesWorkspaceProps = {
  createFormRef: RefObject<HTMLDivElement | null>;
};

export function GamesWorkspace({
  createFormRef,
}: GamesWorkspaceProps) {
  return (
    <main
      className="games-workspace-module mx-auto w-full max-w-none px-4 py-8"
      data-testid="games-workspace-module"
    >
      <Heading as="h1" size="6">狼人杀对局大厅</Heading>

      <div className="mt-6" ref={createFormRef}>
        <CreateGameRunForm />
      </div>
    </main>
  );
}
