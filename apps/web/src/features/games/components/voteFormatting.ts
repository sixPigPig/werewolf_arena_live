export function formatVoteCount(count: number) {
  return Number.isInteger(count) ? String(count) : count.toFixed(1);
}
