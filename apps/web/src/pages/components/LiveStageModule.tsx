import type { ReactNode } from "react";

type LiveStageModuleProps = {
  roster: ReactNode;
  stage: ReactNode;
  timeline: ReactNode;
  bottom?: ReactNode;
};

export function LiveStageModule({
  bottom,
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
      {bottom ? (
        <div className="live-god-bottom-board min-w-0 md:col-span-2 xl:col-span-3">
          {bottom}
        </div>
      ) : null}
    </div>
  );
}
