import {
  type ReactNode,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  Gavel,
  Moon,
  Shield,
  Skull,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import type { GodViewEventLine, GodViewState } from "@werewolf-arena/game-client";

export type MobileLiveEventRailProps = {
  backgroundRef: RefObject<HTMLElement | null>;
  eventLines: GodViewEventLine[];
  godViewState: GodViewState;
  onCloseSheet: () => void;
  onSelectEvent: (eventId: number) => void;
  onToggleSheet: () => void;
  sheetOpen: boolean;
  triggerRef: RefObject<HTMLButtonElement | null>;
};

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  'a[href]',
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function MobileLiveEventRail({
  backgroundRef,
  eventLines,
  godViewState,
  onCloseSheet,
  onSelectEvent,
  onToggleSheet,
  sheetOpen,
  triggerRef,
}: MobileLiveEventRailProps) {
  const moments = useMemo(
    () => [...eventLines].sort((left, right) => left.id - right.id),
    [eventLines],
  );
  const latestId = moments.length > 0 ? moments[moments.length - 1].id : null;
  const scrollRef = useRef<HTMLOListElement | null>(null);
  const [stuckToLatest, setStuckToLatest] = useState(true);
  const [acknowledgedLatestId, setAcknowledgedLatestId] = useState<number | null>(
    latestId,
  );

  // Keep the DOM scroll pinned to the newest chip while the user remains at the end.
  useEffect(() => {
    if (!stuckToLatest) {
      return;
    }
    const node = scrollRef.current;
    if (node) {
      node.scrollLeft = node.scrollWidth;
    }
    // Acknowledge the newest chip so the "new events" indicator clears while pinned.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAcknowledgedLatestId((current) =>
      current === latestId ? current : latestId,
    );
  }, [latestId, stuckToLatest]);

  const handleScroll = () => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    const atEnd =
      node.scrollWidth - node.scrollLeft - node.clientWidth <= 8;
    setStuckToLatest(atEnd);
    if (atEnd && latestId !== null) {
      setAcknowledgedLatestId(latestId);
    }
  };

  const hasNew =
    latestId !== null &&
    acknowledgedLatestId !== null &&
    latestId > acknowledgedLatestId &&
    !stuckToLatest;

  const totalCount = moments.length;
  const allButtonName = `查看全部战报，共 ${totalCount} 条`;

  return (
    <>
      <section aria-label="本轮战报" className="mobile-live-event-rail">
        <span className="mobile-live-event-rail-label">本轮战报</span>
        <ol
          aria-relevant="additions"
          aria-live="polite"
          className="mobile-live-event-rail-chips"
          onScroll={handleScroll}
          ref={scrollRef}
          role="log"
        >
          {totalCount === 0 ? (
            <li aria-disabled="true" className="mobile-live-event-rail-empty">
              等待首个关键事件
            </li>
          ) : (
            moments.map((moment) => (
              <li
                aria-current={moment.id === latestId ? "true" : undefined}
                className={[
                  "mobile-live-event-chip",
                  `mobile-live-event-chip-tone-${moment.tone}`,
                  moment.id === latestId ? "mobile-live-event-chip-current" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                data-event-id={moment.id}
                key={moment.id}
              >
                <span
                  aria-hidden="true"
                  className="mobile-live-event-chip-icon"
                >
                  {renderRailIcon(moment)}
                </span>
                <span className="mobile-live-event-chip-text">{moment.text}</span>
              </li>
            ))
          )}
        </ol>
        {hasNew ? (
          <span aria-live="polite" className="mobile-live-event-rail-new">
            有新事件
          </span>
        ) : null}
        <button
          className="mobile-live-event-rail-all"
          disabled={totalCount === 0}
          onClick={onToggleSheet}
          ref={triggerRef}
          type="button"
          aria-label={allButtonName}
        >
          全部
        </button>
      </section>
      {sheetOpen ? (
        <EventSheet
          backgroundRef={backgroundRef}
          eventLines={moments}
          godViewState={godViewState}
          onClose={onCloseSheet}
          onSelectEvent={onSelectEvent}
          restoreFocusRef={triggerRef}
        />
      ) : null}
    </>
  );
}

function renderRailIcon(moment: GodViewEventLine): ReactNode {
  const Icon = railIconFor(moment);
  return <Icon aria-hidden="true" size={13} strokeWidth={2.2} />;
}

function railIconFor(moment: GodViewEventLine): LucideIcon {
  if (moment.tone === "danger") {
    return moment.phase === "vote" ? Gavel : Skull;
  }
  if (moment.tone === "success") {
    return moment.phase === "night" ? Moon : Shield;
  }
  if (moment.tone === "info") {
    return Sparkles;
  }
  if (moment.tone === "warning") {
    return Gavel;
  }
  return AlertTriangle;
}

type EventSheetProps = {
  backgroundRef: RefObject<HTMLElement | null>;
  eventLines: GodViewEventLine[];
  godViewState: GodViewState;
  onClose: () => void;
  onSelectEvent: (eventId: number) => void;
  restoreFocusRef: RefObject<HTMLElement | null>;
};

function EventSheet({
  backgroundRef,
  eventLines,
  godViewState,
  onClose,
  onSelectEvent,
  restoreFocusRef,
}: EventSheetProps) {
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
    if (!dialog || !background) {
      return;
    }

    background.inert = true;
    background.setAttribute("inert", "");
    const focusInitial = () => {
      const focusable = focusableElements(dialog);
      (focusable[0] ?? dialog).focus();
    };
    focusInitial();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const focusable = focusableElements(dialog);
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
      document.removeEventListener("keydown", handleKeyDown);
      background.inert = false;
      background.removeAttribute("inert");
      // eslint-disable-next-line react-hooks/exhaustive-deps
      const restoreTarget = restoreFocusRef.current;
      if (restoreTarget && document.contains(restoreTarget)) {
        restoreTarget.focus();
      }
    };
  }, [backgroundRef, restoreFocusRef]);

  const groups = useMemo(
    () => groupEvents(eventLines, godViewState),
    [eventLines, godViewState],
  );

  return createPortal(
    <div className="mobile-live-event-sheet-layer">
      <button
        aria-label="关闭战报"
        className="mobile-live-event-sheet-backdrop"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <section
        aria-labelledby="mobile-live-event-sheet-title"
        aria-modal="true"
        className="mobile-live-event-sheet"
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <header className="mobile-live-event-sheet-header">
          <h2 id="mobile-live-event-sheet-title">本轮战报</h2>
          <button
            className="mobile-live-event-sheet-close"
            onClick={onClose}
            type="button"
          >
            关闭
          </button>
        </header>
        <div className="mobile-live-event-sheet-body">
          {groups.map((group, index) => (
            <section
              aria-label={group.title}
              className="mobile-live-event-sheet-group"
              key={`${group.title}-${index}`}
            >
              <h3 className="mobile-live-event-sheet-group-title">{group.title}</h3>
              <ul className="mobile-live-event-sheet-list">
                {group.items.map((moment) => (
                  <li key={moment.id}>
                    <button
                      className={[
                        "mobile-live-event-sheet-row",
                        `mobile-live-event-sheet-row-tone-${moment.tone}`,
                      ].join(" ")}
                      onClick={() => onSelectEvent(moment.id)}
                      type="button"
                      aria-label={`跳转到战报：${moment.text}`}
                    >
                      <span aria-hidden="true" className="mobile-live-event-sheet-row-icon">
                        {renderRailIcon(moment)}
                      </span>
                      <span className="mobile-live-event-sheet-row-time">
                        {moment.time}
                      </span>
                      <span className="mobile-live-event-sheet-row-text">
                        {moment.text}
                      </span>
                      {moment.detail ? (
                        <span className="mobile-live-event-sheet-row-detail">
                          {moment.detail}
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
              {group.voteDetail ? (
                <p className="mobile-live-event-sheet-vote-detail">
                  {group.voteDetail}
                </p>
              ) : null}
            </section>
          ))}
        </div>
      </section>
    </div>,
    document.body,
  );
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((element) => !element.hidden && element.tabIndex >= 0);
}

type EventGroup = {
  title: string;
  items: GodViewEventLine[];
  voteDetail: string | null;
};

function groupEvents(
  eventLines: GodViewEventLine[],
  godViewState: GodViewState,
): EventGroup[] {
  const groups: EventGroup[] = [];
  for (const moment of eventLines) {
    const title = groupTitleFor(moment);
    const last = groups[groups.length - 1];
    if (last && last.title === title) {
      last.items.push(moment);
    } else {
      groups.push({ title, items: [moment], voteDetail: null });
    }
  }
  // Enrich the latest vote group with the full tally from God View, if available.
  const tallies = godViewState.vote.tallies;
  if (tallies.length > 0) {
    for (let index = groups.length - 1; index >= 0; index -= 1) {
      const group = groups[index];
      if (group.title.includes("投票")) {
        group.voteDetail = tallies
          .map(
            (tally) =>
              `${tally.target} ${formatCount(tally.count)}票（${tally.voters.join("、")}）`,
          )
          .join("；");
        break;
      }
    }
  }
  return groups;
}

function formatCount(value: number): string {
  return String(Number(value.toFixed(2)));
}

function groupTitleFor(moment: GodViewEventLine): string {
  const round = moment.round;
  const phase = moment.phase;
  if (phase === "vote") {
    return round ? `第 ${round} 天 投票` : "投票";
  }
  if (phase === "night") {
    return round ? `第 ${round} 夜` : "夜间";
  }
  if (phase === "day") {
    return round ? `第 ${round} 天` : "白天";
  }
  if (phase === "summary") {
    return "结算";
  }
  return round ? `第 ${round} 轮` : "战报";
}
