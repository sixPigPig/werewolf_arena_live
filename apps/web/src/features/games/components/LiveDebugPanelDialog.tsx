import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";

import type { LiveDebugTrace } from "../liveDebugTrace";
import { LiveDebugTraceRail } from "./LiveDebugTraceRail";

type LiveDebugPanelDialogProps = {
  isOpen: boolean;
  onClose: () => void;
  onSelectTrace?: (trace: LiveDebugTrace | null) => void;
  selectedTraceId?: string | null;
  traces: LiveDebugTrace[];
};

type PanelRect = {
  height: number;
  width: number;
  x: number;
  y: number;
};

type PanelInteraction = {
  kind: "drag" | "resize";
  startRect: PanelRect;
  startX: number;
  startY: number;
};

const DEFAULT_PANEL_HEIGHT = 620;
const DEFAULT_PANEL_WIDTH = 540;
const MIN_PANEL_HEIGHT = 320;
const MIN_PANEL_WIDTH = 360;
const VIEWPORT_MARGIN = 12;
const DEFAULT_TOP = 72;

export function LiveDebugPanelDialog({
  isOpen,
  onClose,
  onSelectTrace,
  selectedTraceId,
  traces,
}: LiveDebugPanelDialogProps) {
  const [rect, setRect] = useState<PanelRect>(() => initialPanelRect());
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const interactionRef = useRef<PanelInteraction | null>(null);
  const previousUserSelectRef = useRef<string | null>(null);

  const beginInteraction = useCallback(
    (kind: PanelInteraction["kind"], event: ReactMouseEvent<HTMLElement>) => {
      if (event.button !== 0) {
        return;
      }

      event.preventDefault();
      interactionRef.current = {
        kind,
        startRect: clampPanelRect(rect),
        startX: event.clientX,
        startY: event.clientY,
      };

      previousUserSelectRef.current = document.body.style.userSelect;
      document.body.style.userSelect = "none";
    },
    [rect],
  );

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    closeButtonRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const finishInteraction = () => {
      interactionRef.current = null;
      if (previousUserSelectRef.current !== null) {
        document.body.style.userSelect = previousUserSelectRef.current;
        previousUserSelectRef.current = null;
      }
    };

    const handleMouseMove = (event: MouseEvent) => {
      const interaction = interactionRef.current;
      if (!interaction) {
        return;
      }

      const deltaX = event.clientX - interaction.startX;
      const deltaY = event.clientY - interaction.startY;
      if (interaction.kind === "drag") {
        setRect(
          clampPanelRect({
            ...interaction.startRect,
            x: interaction.startRect.x + deltaX,
            y: interaction.startRect.y + deltaY,
          }),
        );
        return;
      }

      setRect(
        resizePanelRect(interaction.startRect, {
          deltaX,
          deltaY,
        }),
      );
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", finishInteraction);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", finishInteraction);
      finishInteraction();
    };
  }, [isOpen]);

  if (!isOpen) {
    return null;
  }

  const panelRect = clampPanelRect(rect);

  return (
    <section
      aria-labelledby="live-debug-panel-title"
      aria-modal={false}
      className="live-debug-panel-dialog fixed z-[65] flex min-w-0 flex-col overflow-hidden rounded-lg border border-sky-300/25 bg-slate-950/95 text-slate-100 shadow-[0_24px_80px_rgba(0,0,0,0.5)] backdrop-blur-md"
      data-testid="live-debug-panel-dialog"
      role="dialog"
      style={{
        height: `${panelRect.height}px`,
        left: `${panelRect.x}px`,
        top: `${panelRect.y}px`,
        width: `${panelRect.width}px`,
      }}
    >
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-sky-300/15 bg-slate-950/70 px-3 py-2">
        <div
          aria-label="拖动调试面板"
          className="min-w-0 flex-1 cursor-move select-none py-1"
          data-testid="live-debug-panel-drag-handle"
          onMouseDown={(event) => beginInteraction("drag", event)}
          role="button"
          tabIndex={0}
        >
          <h2
            className="truncate text-sm font-semibold text-amber-50"
            id="live-debug-panel-title"
          >
            调试面板
          </h2>
        </div>
        <button
          aria-label="关闭调试面板"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-slate-500/35 text-slate-200 transition hover:border-sky-300/55 hover:text-sky-100 focus:outline-none focus:ring-2 focus:ring-sky-300/70"
          onClick={onClose}
          ref={closeButtonRef}
          type="button"
        >
          <span aria-hidden="true">×</span>
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-hidden">
        <LiveDebugTraceRail
          listClassName="min-h-0 flex-1 space-y-2 overflow-auto p-3"
          onSelectTrace={onSelectTrace}
          selectedTraceId={selectedTraceId}
          surface="embedded"
          traces={traces}
        />
      </div>

      <button
        aria-label="调整调试面板大小"
        className="absolute bottom-1.5 right-1.5 h-5 w-5 cursor-nwse-resize rounded-sm border-b-2 border-r-2 border-sky-200/45 bg-transparent focus:outline-none focus:ring-2 focus:ring-sky-300/70"
        data-testid="live-debug-panel-resize-handle"
        onMouseDown={(event) => beginInteraction("resize", event)}
        type="button"
      />
    </section>
  );
}

function initialPanelRect(): PanelRect {
  const viewport = viewportSize();
  const width = Math.min(DEFAULT_PANEL_WIDTH, viewport.width - VIEWPORT_MARGIN * 2);
  const height = Math.min(
    DEFAULT_PANEL_HEIGHT,
    viewport.height - DEFAULT_TOP - VIEWPORT_MARGIN,
  );

  return {
    height,
    width,
    x: Math.max(VIEWPORT_MARGIN, viewport.width - width - 24),
    y: Math.min(DEFAULT_TOP, Math.max(VIEWPORT_MARGIN, viewport.height - height)),
  };
}

function resizePanelRect(
  startRect: PanelRect,
  delta: { deltaX: number; deltaY: number },
) {
  const viewport = viewportSize();
  return clampPanelRect({
    ...startRect,
    height: clamp(
      startRect.height + delta.deltaY,
      MIN_PANEL_HEIGHT,
      Math.max(MIN_PANEL_HEIGHT, viewport.height - startRect.y - VIEWPORT_MARGIN),
    ),
    width: clamp(
      startRect.width + delta.deltaX,
      MIN_PANEL_WIDTH,
      Math.max(MIN_PANEL_WIDTH, viewport.width - startRect.x - VIEWPORT_MARGIN),
    ),
  });
}

function clampPanelRect(rect: PanelRect): PanelRect {
  const viewport = viewportSize();
  const width = clamp(
    rect.width,
    MIN_PANEL_WIDTH,
    Math.max(MIN_PANEL_WIDTH, viewport.width - VIEWPORT_MARGIN * 2),
  );
  const height = clamp(
    rect.height,
    MIN_PANEL_HEIGHT,
    Math.max(MIN_PANEL_HEIGHT, viewport.height - VIEWPORT_MARGIN * 2),
  );

  return {
    height,
    width,
    x: clamp(
      rect.x,
      VIEWPORT_MARGIN,
      Math.max(VIEWPORT_MARGIN, viewport.width - width - VIEWPORT_MARGIN),
    ),
    y: clamp(
      rect.y,
      VIEWPORT_MARGIN,
      Math.max(VIEWPORT_MARGIN, viewport.height - height - VIEWPORT_MARGIN),
    ),
  };
}

function viewportSize() {
  if (typeof window === "undefined") {
    return { height: 768, width: 1024 };
  }

  return {
    height: window.innerHeight || 768,
    width: window.innerWidth || 1024,
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
