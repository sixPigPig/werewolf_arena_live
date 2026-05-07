import { Theme } from "@radix-ui/themes";
import type { ReactNode } from "react";

type AppThemeProps = {
  children: ReactNode;
};

export function AppTheme({ children }: AppThemeProps) {
  return (
    <Theme
      accentColor="gray"
      className="min-h-screen bg-slate-50 text-slate-950"
      grayColor="slate"
      panelBackground="solid"
      radius="medium"
    >
      {children}
    </Theme>
  );
}
