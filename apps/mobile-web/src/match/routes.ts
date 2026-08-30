import type { RouteObject } from "react-router-dom";

export const liveRoute: RouteObject = {
  path: "v2/games/:gameId/live",
  lazy: async () => {
    const { LivePage } = await import("./live/LivePage");
    return { Component: LivePage };
  },
};

export const godViewRoute: RouteObject = {
  path: "v2/games/:gameId/live/god",
  lazy: async () => {
    const { GodViewPage } = await import("./god-view/GodViewPage");
    return { Component: GodViewPage };
  },
};
