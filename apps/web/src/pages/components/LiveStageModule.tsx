import type { ReactNode } from "react";

type LiveStageModuleProps = {
  top: ReactNode;
  left: ReactNode;
  stage: ReactNode;
  right: ReactNode;
  bottom?: ReactNode;
};

export function LiveStageModule({
  bottom,
  left,
  right,
  stage,
  top,
}: LiveStageModuleProps) {
  return (
    <div
      className="live-stage-layout live-stage-module god-view-broadcast-layout grid gap-3"
      data-testid="live-stage-layout"
    >
      <div className="god-view-top-zone min-w-0" data-testid="god-view-top-zone">
        {top}
      </div>
      <div className="god-view-left-zone min-w-0" data-testid="god-view-left-zone">
        {left}
      </div>
      <div className="god-view-stage-zone min-w-0" data-testid="god-view-stage-zone">
        {stage}
      </div>
      <div className="god-view-right-zone min-w-0" data-testid="god-view-right-zone">
        {right}
      </div>
      {bottom ? (
        <div
          className="god-view-bottom-zone live-god-bottom-board min-w-0"
          data-testid="god-view-bottom-zone"
        >
          {bottom}
        </div>
      ) : null}
    </div>
  );
}
