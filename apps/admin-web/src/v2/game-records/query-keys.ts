export const v2GameRecordKeys = {
  all: ["admin", "v2", "game-records"] as const,
  detail: (gameId: string) =>
    ["admin", "v2", "game-records", "detail", gameId] as const,
  list: (page: number) =>
    ["admin", "v2", "game-records", "list", page] as const,
};
