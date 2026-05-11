import type { ReactNode } from "react";

type GameLayoutProps = {
  header?: ReactNode;
  players: ReactNode;
  timeline: ReactNode;
  debug: ReactNode;
};

export function GameLayout({ header, players, timeline, debug }: GameLayoutProps) {
  return (
    <main className="mx-auto grid w-full max-w-none gap-4 px-4 py-6 lg:grid-cols-[20rem_minmax(0,1fr)_22rem]">
      {header ? <div className="min-w-0 lg:col-span-3">{header}</div> : null}
      <div className="min-w-0">{players}</div>
      <div className="min-w-0">{timeline}</div>
      <div className="min-w-0 lg:sticky lg:top-4 lg:self-start">{debug}</div>
    </main>
  );
}
