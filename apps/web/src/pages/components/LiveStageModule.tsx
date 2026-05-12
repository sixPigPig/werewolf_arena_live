import type { ReactNode } from "react";

type LiveStageModuleProps = {
  roster: ReactNode;
  stage: ReactNode;
  timeline: ReactNode;
};

export function LiveStageModule({
  roster,
  stage,
  timeline,
}: LiveStageModuleProps) {
  return (
    <div
      className="live-stage-layout live-stage-module grid gap-4 md:grid-cols-[20rem_minmax(0,1fr)] xl:grid-cols-[20rem_minmax(0,1fr)_22rem]"
      data-testid="live-stage-layout"
    >
      <div className="live-roster-column min-w-0 md:sticky md:top-4 md:self-start">
        {roster}
      </div>
      <div className="live-stage-column min-w-0 space-y-3">{stage}</div>
      {timeline}
    </div>
  );
}
