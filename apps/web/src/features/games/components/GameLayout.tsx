import type { ReactNode } from "react";

type GameLayoutProps = {
  players: ReactNode;
  timeline: ReactNode;
  debug: ReactNode;
};

export function GameLayout({ players, timeline, debug }: GameLayoutProps) {
  return (
    <main className="mx-auto grid w-full max-w-7xl gap-4 px-4 py-6 lg:grid-cols-[18rem_minmax(0,1fr)_22rem]">
      <div className="min-w-0">{players}</div>
      <div className="min-w-0">{timeline}</div>
      <div className="min-w-0 lg:sticky lg:top-4 lg:self-start">{debug}</div>
    </main>
  );
}
