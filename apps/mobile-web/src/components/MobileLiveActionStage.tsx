import {
  AlertTriangle,
  Eye,
  FlaskConical,
  Gavel,
  Hourglass,
  Mic,
  Moon,
  PawPrint,
  Shield,
  Skull,
  Sparkles,
  Trophy,
  type LucideIcon,
} from "lucide-react";

import {
  resolveAvatarImageUrl,
  type GodViewPlayer,
  type GodViewState,
} from "@werewolf-arena/game-client";

import type {
  MobileLiveFocusKind,
  MobileLiveFocusPresentation,
  MobileLiveFocusTone,
} from "./mobileLiveActionModel";

type MobileLiveActionStageProps = {
  presentation: MobileLiveFocusPresentation;
  currentPlayer: GodViewPlayer | null;
  godViewState: GodViewState;
};

export function MobileLiveActionStage({
  presentation,
  currentPlayer,
  godViewState,
}: MobileLiveActionStageProps) {
  if (presentation.kind === "speech") {
    return renderSpeech(presentation, currentPlayer, godViewState);
  }
  return renderAction(presentation, currentPlayer, godViewState);
}

function renderSpeech(
  presentation: MobileLiveFocusPresentation,
  currentPlayer: GodViewPlayer | null,
  godViewState: GodViewState,
) {
  const avatarImageUrl = currentPlayer
    ? resolveAvatarImageUrl({ avatar_image_url: currentPlayer.avatarImageUrl })
    : null;
  const name = currentPlayer?.name ?? presentation.actorName ?? "等待玩家行动";
  const seat = currentPlayer?.seatNumber
    ? `${currentPlayer.seatNumber}号`
    : presentation.actorSeat
      ? `${presentation.actorSeat}号`
      : "等待";
  const status = currentPlayer?.stageStatus.label ?? godViewState.currentSeatLabel;
  const speechLabel = presentation.eyebrow || "白天发言";
  const phase = `${speechLabel}阶段`;

  return (
    <section
      aria-atomic="true"
      aria-label="当前舞台"
      aria-live="polite"
      className="mobile-live-center-stage mobile-live-action-kind-speech mobile-live-action-tone-info"
      role="status"
    >
      <span className="mobile-sr-only">{presentation.accessibleText}</span>
      <div aria-hidden="true" className="mobile-live-presenter">
        {avatarImageUrl ? (
          <img alt="" src={avatarImageUrl} />
        ) : (
          <span>
            {currentPlayer
              ? avatarInitial(currentPlayer.name, currentPlayer.seatNumber)
              : "?"}
          </span>
        )}
        {currentPlayer ? (
          <span className="mobile-live-presenter-mic">
            <Mic aria-hidden="true" size={14} strokeWidth={2.8} />
          </span>
        ) : null}
      </div>
      <span aria-hidden="true">{seat}</span>
      <strong aria-hidden="true">{name}</strong>
      <em aria-hidden="true">{status}</em>
      <p aria-hidden="true">{speechLabel}</p>
      <small aria-hidden="true">{phase}</small>
    </section>
  );
}

function renderAction(
  presentation: MobileLiveFocusPresentation,
  currentPlayer: GodViewPlayer | null,
  godViewState: GodViewState,
) {
  const {
    kind,
    tone,
    eyebrow,
    title,
    detail,
    progress,
    actorSeat,
    actorName,
    accessibleText,
  } = presentation;

  const className = [
    "mobile-live-center-stage",
    `mobile-live-action-kind-${kind}`,
    `mobile-live-action-tone-${tone}`,
  ].join(" ");

  const presenter = renderPresenter({
    kind,
    actorSeat,
    actorName,
    currentPlayer,
    godViewState,
    tone,
  });

  return (
    <section
      aria-atomic="true"
      aria-label="当前舞台"
      aria-live="polite"
      className={className}
      role="status"
    >
      <span className="mobile-sr-only">{accessibleText}</span>
      <div aria-hidden="true" className="mobile-live-presenter">
        {presenter}
      </div>
      <span aria-hidden="true">{actorDisplay(actorName, actorSeat, eyebrow)}</span>
      <strong aria-hidden="true">{title}</strong>
      <em aria-hidden="true" className="mobile-live-action-detail">
        {detail || "-"}
      </em>
      {progress ? <p aria-hidden="true">{progress}</p> : null}
      <small aria-hidden="true">{`${eyebrow} · ${phaseLabel(kind)}`}</small>
    </section>
  );
}

function renderPresenter({
  kind,
  actorSeat,
  actorName,
  currentPlayer,
  godViewState,
  tone,
}: {
  kind: MobileLiveFocusKind;
  actorSeat: number | null;
  actorName: string | null;
  currentPlayer: GodViewPlayer | null;
  godViewState: GodViewState;
  tone: MobileLiveFocusTone;
}) {
  const teamActor = actorName === "狼人阵营" || actorName === "未知行动者";
  const hasSingleActor =
    (kind === "night-action" || kind === "vote-action") &&
    actorSeat !== null &&
    !teamActor;

  if (hasSingleActor) {
    const actor =
      currentPlayer && currentPlayer.seatNumber === actorSeat
        ? currentPlayer
        : (godViewState.players.find(
            (player) => player.seatNumber === actorSeat,
          ) ?? null);
    const avatarImageUrl = actor
      ? resolveAvatarImageUrl({ avatar_image_url: actor.avatarImageUrl })
      : null;
    if (avatarImageUrl) {
      return <img alt="" src={avatarImageUrl} />;
    }
    if (actor) {
      return <span>{avatarInitial(actor.name, actor.seatNumber)}</span>;
    }
  }

  const Icon = toneIcon(kind, tone);
  return <Icon strokeWidth={2} />;
}

function toneIcon(kind: MobileLiveFocusKind, tone: MobileLiveFocusTone): LucideIcon {
  if (kind === "night-result" && tone === "success") {
    return Moon;
  }
  if (kind === "night-result") {
    return Skull;
  }
  if (kind === "vote-result") {
    return Gavel;
  }
  if (kind === "terminal") {
    return Trophy;
  }
  if (kind === "skill") {
    return Sparkles;
  }
  if (kind === "waiting") {
    return Hourglass;
  }
  if (tone === "danger") {
    return PawPrint;
  }
  if (tone === "success") {
    return Shield;
  }
  if (tone === "info") {
    return Eye;
  }
  if (tone === "warning") {
    return FlaskConical;
  }
  if (tone === "neutral") {
    return AlertTriangle;
  }
  return Hourglass;
}

function phaseLabel(kind: MobileLiveFocusKind) {
  const map: Record<MobileLiveFocusKind, string> = {
    waiting: "待命",
    speech: "公开发言",
    "night-action": "夜间行动",
    "night-result": "夜间结算",
    "vote-action": "白天投票",
    "vote-result": "投票结算",
    skill: "技能触发",
    terminal: "终局",
  };
  return map[kind];
}

function avatarInitial(name: string, seatNumber: number) {
  const trimmed = name.trim();
  return trimmed ? trimmed.slice(0, 1) : String(seatNumber);
}

function actorDisplay(
  actorName: string | null,
  actorSeat: number | null,
  fallback: string,
) {
  if (!actorName) {
    return fallback;
  }
  if (actorSeat !== null && !/^\d+\s*号/.test(actorName)) {
    return `${actorSeat}号 ${actorName}`;
  }
  return actorName;
}
