import {
  type ReactNode,
  type RefObject,
  useEffect,
  useRef,
} from "react";

type LobbyModalProps = {
  backgroundRef: RefObject<HTMLElement | null>;
  children: ReactNode;
  className: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
  labelledBy: string;
  onClose: () => void;
  restoreFocusRef: RefObject<HTMLElement | null>;
};

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function getFocusableElements(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((element) => !element.hidden && element.tabIndex >= 0);
}

export function LobbyModal({
  backgroundRef,
  children,
  className,
  initialFocusRef,
  labelledBy,
  onClose,
  restoreFocusRef,
}: LobbyModalProps) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    const background = backgroundRef.current as
      | (HTMLElement & { inert?: boolean })
      | null;
    if (!dialog || !background) return;

    background.inert = true;
    background.setAttribute("inert", "");
    const frame = window.requestAnimationFrame(() => {
      (initialFocusRef?.current ?? getFocusableElements(dialog)[0] ?? dialog).focus();
    });

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = getFocusableElements(dialog);
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      } else if (!(active instanceof Node) || !dialog.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleKeyDown);
      background.inert = false;
      background.removeAttribute("inert");
      // The target may intentionally advance from the originating seat to the final seat.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      const restoreTarget = restoreFocusRef.current;
      if (restoreTarget && document.contains(restoreTarget)) restoreTarget.focus();
    };
  }, [backgroundRef, initialFocusRef, restoreFocusRef]);

  return (
    <div className="mobile-lobby-modal-layer">
      <div aria-hidden="true" className="mobile-lobby-modal-backdrop" />
      <section
        aria-labelledby={labelledBy}
        aria-modal="true"
        className={["mobile-lobby-modal", className].join(" ")}
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        {children}
      </section>
    </div>
  );
}
