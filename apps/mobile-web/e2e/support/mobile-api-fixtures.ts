import type { Page } from "@playwright/test";
import type {
  LineupPreviewRequest,
  PublicPlayerProfile,
  RuleSetSummary,
} from "@werewolf-arena/game-client";

import type { GameCreateRequest } from "../../src/match/contracts";

export const mobileRuleSets: RuleSetSummary[] = [
  {
    id: "classic_8",
    version: "e2e",
    name: "经典 8 人局",
    player_count: 8,
    role_summary: "2 狼人 / 1 预言家 / 1 守卫 / 4 村民",
    roles: [],
  },
  {
    id: "starter_6",
    version: "e2e",
    name: "新手 6 人快局",
    player_count: 6,
    role_summary: "1 狼人 / 1 预言家 / 1 守卫 / 3 村民",
    roles: [],
  },
];

const profileNames = [
  "暗巷观星",
  "暗牌验心",
  "票台换票",
  "狼啸听风",
  "警徽定狼",
  "警徽低语",
  "雾灯守灯",
  "守夜潜行",
];

export const mobileProfiles: PublicPlayerProfile[] = profileNames.map(
  (displayName, index) => ({
    id: `profile-${index + 1}`,
    display_name: displayName,
    model: "e2e-model",
    personality_id: "balanced",
    personality_text: "沉稳控场",
    appearance_id: "default",
    avatar_image_url: "",
    short_description: "先盘逻辑再给站边",
    background_story: "",
    speaking_style: "",
    strategy_profile: index % 2 === 0 ? "analysis" : "balanced",
    risk_tolerance: 3,
    bluffing_tendency: 3,
    trust_tendency: 3,
    leadership_tendency: 3,
    talkativeness: 3,
    example_messages: [],
    display_order: index + 1,
    featured: false,
    tags: index % 2 === 0 ? ["逻辑"] : ["均衡"],
  }),
);

type MobileApiFixtureOptions = {
  favoriteProfileIds?: string[];
  profiles?: PublicPlayerProfile[];
  ruleSets?: RuleSetSummary[];
};

export async function installMobileApiFixtures(
  page: Page,
  options: MobileApiFixtureOptions = {},
) {
  const favoriteProfileIds = new Set(
    options.favoriteProfileIds ?? ["profile-1"],
  );
  const profiles = options.profiles ?? mobileProfiles;
  const ruleSets = options.ruleSets ?? mobileRuleSets;
  const createRequests: GameCreateRequest[] = [];

  await page.route("**/api/v2/games", async (route) => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.fulfill({
        status: 404,
        json: { detail: `Unhandled fixture: ${new URL(request.url()).pathname}` },
      });
      return;
    }
    const body = request.postDataJSON() as GameCreateRequest;
    createRequests.push(body);
    await route.fulfill({
      json: {
        game_id: "v2_game_0123456789abcdef",
        run_id: "v2_run_0123456789abcdef",
        status: "waiting_to_start",
        audio_mode: body.audio_mode,
        snapshot_url: "/api/v2/live/games/v2_game_0123456789abcdef/snapshot",
        websocket_url: "/api/v2/live/games/v2_game_0123456789abcdef/ws",
        director_snapshot_url:
          "/api/v2/director/games/v2_game_0123456789abcdef/snapshot",
        director_websocket_url: "/api/v2/director/games/v2_game_0123456789abcdef/ws",
        god_view_snapshot_url:
          "/api/v2/god-view/games/v2_game_0123456789abcdef/identity-snapshot",
        god_view_websocket_url:
          "/api/v2/god-view/games/v2_game_0123456789abcdef/ws",
        god_view_access_token: "a".repeat(43),
      },
    });
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === "/api/v1/public/session") {
      await route.fulfill({
        json: {
          viewer: { kind: "guest" },
          csrf_token: "mobile-e2e-csrf",
          session_expires_at: "2099-01-01T00:00:00Z",
        },
      });
      return;
    }

    if (path === "/api/v1/public/me/favorite-player-profiles") {
      await route.fulfill({ json: { profile_ids: [...favoriteProfileIds] } });
      return;
    }

    if (path.startsWith("/api/v1/public/me/favorite-player-profiles/")) {
      const profileId = decodeURIComponent(path.split("/").at(-1) ?? "");
      const isFavorite = request.method() === "PUT";

      if (isFavorite) favoriteProfileIds.add(profileId);
      else favoriteProfileIds.delete(profileId);

      await route.fulfill({
        json: { profile_id: profileId, is_favorite: isFavorite },
      });
      return;
    }

    if (path === "/api/v1/public/player-profiles") {
      await route.fulfill({
        json: {
          items: profiles,
          pagination: {
            page: 1,
            page_size: 100,
            total: profiles.length,
            pages: 1,
          },
        },
      });
      return;
    }

    if (path === "/api/v1/games/rule-sets") {
      await route.fulfill({ json: { rule_sets: ruleSets } });
      return;
    }

    if (path === "/api/v1/games/lineup-preview" && request.method() === "POST") {
      const body = request.postDataJSON() as LineupPreviewRequest;
      const playerConfigs = body.player_configs ?? [];
      await route.fulfill({
        json: {
          player_configs: playerConfigs,
          lineup_quality_report: {
            schema_version: 1,
            policy_mode: "repair",
            player_count: playerConfigs.length,
            configured_count: playerConfigs.filter((item) => item.profile_id)
              .length,
            is_blocked: false,
            was_repaired: false,
            style_bucket_count: 1,
            required_style_bucket_count: 1,
            violations: [],
          },
          rule_set_revision_id: "revision-e2e",
        },
      });
      return;
    }

    if (path === "/api/v1/games") {
      await route.fulfill({ json: { sessions: [] } });
      return;
    }

    await route.fulfill({
      status: 404,
      json: { detail: `Unhandled fixture: ${path}` },
    });
  });

  return { createRequests };
}
