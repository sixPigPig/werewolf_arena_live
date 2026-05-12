import type { ReactNode } from "react";

type LivePageShellProps = {
  children: ReactNode;
};

export function LivePageShell({ children }: LivePageShellProps) {
  return (
    <div
      className="live-page-shell-module live-game-content mx-auto w-full max-w-none"
      data-testid="live-page-shell-module"
    >
      {children}
    </div>
  );
}
