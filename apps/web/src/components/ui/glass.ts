export const glassPanelClass =
  "glass-panel border border-slate-200/20 shadow-[0_18px_50px_rgba(0,0,0,0.22)]";

export const glassSubtlePanelClass =
  "glass-panel glass-panel-subtle border border-slate-200/15 shadow-[0_12px_34px_rgba(0,0,0,0.18)]";

export function withGlassPanel(
  ...classes: Array<string | false | null | undefined>
) {
  return [glassPanelClass, ...classes].filter(Boolean).join(" ");
}
