import { forwardRef } from "react";

type LiveNavDebugPanelButtonProps = {
  isOpen: boolean;
  onClick: () => void;
};

export const LiveNavDebugPanelButton = forwardRef<
  HTMLButtonElement,
  LiveNavDebugPanelButtonProps
>(function LiveNavDebugPanelButton({ isOpen, onClick }, ref) {
  return (
    <button
      aria-expanded={isOpen}
      aria-haspopup="dialog"
      aria-label="调试面板"
      className="flex h-10 w-10 items-center justify-center rounded-md border border-slate-500/35 bg-white/5 font-mono text-sm font-semibold text-slate-100 shadow-[inset_0_0_12px_rgba(255,255,255,0.04)] transition hover:border-sky-300/55 hover:bg-sky-300/10 focus:outline-none focus:ring-2 focus:ring-sky-300/70"
      onClick={onClick}
      ref={ref}
      title="调试面板"
      type="button"
    >
      <span aria-hidden="true">{"{}"}</span>
    </button>
  );
});
