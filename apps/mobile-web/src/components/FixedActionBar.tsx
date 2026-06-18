import type { ReactNode } from "react";

type FixedActionBarProps = {
  children: ReactNode;
};

export function FixedActionBar({ children }: FixedActionBarProps) {
  return <div className="mobile-fixed-action-bar">{children}</div>;
}
