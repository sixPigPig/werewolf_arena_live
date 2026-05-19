import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, SelectField } from "../../../components/ui";
import type { LiveDirectorSpeed } from "../hooks/useLiveDirector";
import type { LiveNavStatus } from "../liveNavStatus";
import type { GameRun, LiveStageRun, RuleSetSummary } from "../types";
import { LiveNavStatusBadge } from "./LiveNavStatusBadge";

type LiveNavSettingsMenuProps = {
  backlogCount: number;
  canResumeRun: boolean;
  isPaused: boolean;
  isResuming: boolean;
  onCatchUpToLatest: () => void;
  onResumeRun: () => void;
  onSpeedChange: (speed: LiveDirectorSpeed) => void;
  onTogglePaused: () => void;
  run: GameRun | LiveStageRun;
  speed: LiveDirectorSpeed;
  status: LiveNavStatus;
  title?: string;
};

export function LiveNavSettingsMenu({
  backlogCount,
  canResumeRun,
  isPaused,
  isResuming,
  onCatchUpToLatest,
  onResumeRun,
  onSpeedChange,
  onTogglePaused,
  run,
  speed,
  status,
  title = "实时设置",
}: LiveNavSettingsMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const rule = normalizeRule(run);
  const roleSummary =
    rule.role_summary ??
    rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");

  const closeMenu = useCallback(() => {
    setIsOpen(false);
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    closeButtonRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const dialog = dialogRef.current;
      if (!dialog) {
        return;
      }

      const focusableElements = getFocusableElements(dialog);
      if (focusableElements.length === 0) {
        event.preventDefault();
        return;
      }

      const activeElement = document.activeElement;
      const activeIndex =
        activeElement instanceof HTMLElement
          ? focusableElements.indexOf(activeElement)
          : -1;
      const nextIndex = event.shiftKey
        ? activeIndex <= 0
          ? focusableElements.length - 1
          : activeIndex - 1
        : activeIndex === -1 || activeIndex === focusableElements.length - 1
          ? 0
          : activeIndex + 1;

      event.preventDefault();
      focusableElements[nextIndex]?.focus();
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [closeMenu, isOpen]);

  return (
    <div className="live-nav-settings relative flex shrink-0" data-testid="live-nav-settings">
      <button
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={title}
        className="flex h-10 w-10 items-center justify-center rounded-md border border-slate-500/35 bg-white/5 text-base font-semibold text-slate-100 shadow-[inset_0_0_12px_rgba(255,255,255,0.04)] transition hover:border-amber-300/55 hover:bg-amber-300/10 focus:outline-none focus:ring-2 focus:ring-amber-300/70"
        onClick={() => setIsOpen((value) => !value)}
        ref={triggerRef}
        type="button"
      >
        <span aria-hidden="true">⚙</span>
      </button>

      {isOpen ? (
        <>
          <div
            aria-hidden="true"
            className="fixed inset-0 z-[55]"
            data-testid="live-settings-backdrop"
            onMouseDown={closeMenu}
          />
          <section
            aria-labelledby="live-settings-title"
            aria-modal="true"
            className="fixed right-3 top-[calc(var(--arena-nav-height,var(--app-top-nav-height,56px))+0.75rem)] z-[60] max-h-[calc(100vh-var(--arena-nav-height,var(--app-top-nav-height,56px))-1.5rem)] w-[min(24rem,calc(100vw-1.5rem))] overflow-y-auto rounded-lg border border-slate-500/35 bg-slate-950/95 p-4 text-slate-100 shadow-[0_18px_70px_rgba(0,0,0,0.45)] backdrop-blur-md"
            data-testid="live-settings-dialog"
            onMouseDown={(event) => event.stopPropagation()}
            ref={dialogRef}
            role="dialog"
          >
            <header className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-amber-50" id="live-settings-title">
                {title}
              </h2>
              <button
                aria-label={`关闭${title}`}
                className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-500/35 text-slate-200 transition hover:border-amber-300/55 hover:text-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-300/70"
                onClick={closeMenu}
                ref={closeButtonRef}
                type="button"
              >
                <span aria-hidden="true">×</span>
              </button>
            </header>

            <section
              aria-labelledby="live-settings-info-title"
              className="border-b border-slate-700/70 pb-4"
            >
              <h3
                className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400"
                id="live-settings-info-title"
              >
                对局信息
              </h3>
              <dl className="grid gap-2 text-sm">
                <InfoRow label="对局 ID" mono value={run.session_id} />
                <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-2">
                  <dt className="text-slate-400">状态</dt>
                  <dd>
                    <LiveNavStatusBadge status={status} />
                  </dd>
                </div>
                <InfoRow label="规则" value={rule.name} />
                <InfoRow label="版本" value={formatRuleVersion(rule.version)} />
                <InfoRow label="人数" value={`${rule.player_count} 人`} />
              </dl>
              {roleSummary ? (
                <p className="mt-3 text-xs leading-5 text-slate-300">{roleSummary}</p>
              ) : null}
              {rule.rule_tags && rule.rule_tags.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {rule.rule_tags.map((tag) => (
                    <Badge color="amber" key={tag} variant="surface">
                      {tag}
                    </Badge>
                  ))}
                </div>
              ) : null}
            </section>

            <section
              aria-labelledby="live-settings-controls-title"
              className="border-b border-slate-700/70 py-4"
            >
              <h3
                className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400"
                id="live-settings-controls-title"
              >
                观战控制
              </h3>
              {canResumeRun ? (
                <Button
                  className="w-full"
                  disabled={isResuming}
                  intent="primary"
                  loading={isResuming}
                  onClick={onResumeRun}
                  skin="gothic"
                  type="button"
                >
                  继续对局
                </Button>
              ) : (
                <div className="grid gap-3">
                  <div className="grid grid-cols-2 gap-2">
                    <Button onClick={onTogglePaused} skin="gothic" type="button">
                      {isPaused ? "继续播放" : "暂停"}
                    </Button>
                    <Button
                      disabled={backlogCount === 0}
                      onClick={onCatchUpToLatest}
                      skin="gothic"
                      type="button"
                    >
                      追到最新
                    </Button>
                  </div>
                  <label className="grid gap-1.5 text-xs font-semibold text-slate-300">
                    播放速度
                    <SelectField
                      aria-label="播放速度"
                      onChange={(event) =>
                        onSpeedChange(Number(event.target.value) as LiveDirectorSpeed)
                      }
                      value={String(speed)}
                    >
                      <option value="1">1x</option>
                      <option value="2">2x</option>
                    </SelectField>
                  </label>
                  <p className="text-xs text-slate-400">
                    {backlogCount > 0
                      ? `当前落后 ${backlogCount} 条事件`
                      : "当前已在最新事件"}
                  </p>
                </div>
              )}
            </section>

            <section aria-labelledby="live-settings-navigation-title" className="pt-4">
              <h3
                className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400"
                id="live-settings-navigation-title"
              >
                导航操作
              </h3>
              <Button asChild className="w-full" skin="gothic" variant="surface">
                <Link to="/games">返回大厅</Link>
              </Button>
            </section>
          </section>
        </>
      ) : null}
    </div>
  );
}

function InfoRow({
  label,
  mono = false,
  value,
}: {
  label: string;
  mono?: boolean;
  value: string;
}) {
  return (
    <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-2">
      <dt className="text-slate-400">{label}</dt>
      <dd
        className={mono ? "truncate font-mono text-slate-100" : "truncate text-slate-100"}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}

function normalizeRule(run: GameRun | LiveStageRun): RuleSetSummary {
  return (
    run.rule_set ?? {
      id: "live",
      name: "实时对局",
      player_count:
        "player_configs" in run ? (run.player_configs?.length ?? 0) : 0,
      roles: [],
      version: "-",
    }
  );
}

function formatRuleVersion(version: string) {
  return version === "-" ? version : `v${version}`;
}

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function getFocusableElements(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    (element) =>
      !element.hasAttribute("disabled") && element.getAttribute("aria-hidden") !== "true",
  );
}
