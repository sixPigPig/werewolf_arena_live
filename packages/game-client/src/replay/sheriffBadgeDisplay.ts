const BADGE_TRANSFER_PREFIX = "移交给";
const BADGE_DESTROY_CHOICE = "撕毁警徽";

export function badgeTransferTarget(choice: string | null | undefined) {
  const trimmedChoice = choice?.trim();
  if (!trimmedChoice || trimmedChoice === BADGE_DESTROY_CHOICE) {
    return null;
  }

  if (trimmedChoice.startsWith(BADGE_TRANSFER_PREFIX)) {
    return trimmedChoice.slice(BADGE_TRANSFER_PREFIX.length).trim() || null;
  }

  return trimmedChoice;
}

export function isSelfBadgeTransfer(
  actor: string | null | undefined,
  choice: string | null | undefined,
) {
  const target = badgeTransferTarget(choice);
  return Boolean(actor && target && actor.trim() === target);
}
