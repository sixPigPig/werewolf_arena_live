export const v2GameRecordKeys = {
  all: ["admin", "v2", "game-records"] as const,
  detail: (gameId: string) =>
    ["admin", "v2", "game-records", "detail", gameId] as const,
  event: (gameId: string, eventId: number) =>
    [
      "admin",
      "v2",
      "game-records",
      "detail",
      gameId,
      "events",
      eventId,
    ] as const,
  modelRequest: (gameId: string, attemptId: string) =>
    [
      "admin",
      "v2",
      "game-records",
      "detail",
      gameId,
      "model-requests",
      attemptId,
    ] as const,
  list: (page: number) =>
    ["admin", "v2", "game-records", "list", page] as const,
};
