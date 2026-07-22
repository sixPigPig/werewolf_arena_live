import type { RouteObject } from "react-router-dom";

export const liveV2Route: RouteObject = {
  path: "v2/games/:gameId/live",
  lazy: async () => {
    const { LiveV2Page } = await import("./live/LiveV2Page");
    return { Component: LiveV2Page };
  },
};
