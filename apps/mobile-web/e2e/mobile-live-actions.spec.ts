import { expect, test, type Page } from "@playwright/test";

import { installMobileApiFixtures } from "./support/mobile-api-fixtures";
import type { LiveGameEvent } from "@werewolf-arena/game-client";

function playbackEvent(
  id: number,
  overrides: Partial<LiveGameEvent>,
): LiveGameEvent {
  return {
    id,
    type: overrides.type ?? "game_started",
    run_id: "run-e2e",
    session_id: "session-e2e",
    created_at: overrides.created_at ?? "2026-07-13T00:00:00Z",
    round: overrides.round ?? null,
    phase: overrides.phase ?? null,
    actor: overrides.actor ?? null,
    action: overrides.action ?? null,
    payload: overrides.payload ?? {},
  };
}

function buildPlaybackEvents(): LiveGameEvent[] {
  return [
    playbackEvent(1, {
      type: "game_started",
      round: 1,
      phase: "night",
      payload: {
        players: [
          { name: "1号 暗巷观星", role: "werewolf", model: "e2e-model" },
          { name: "2号 暗牌验心", role: "werewolf", model: "e2e-model" },
          { name: "3号 票台换票", role: "seer", model: "e2e-model" },
          { name: "4号 狼啸听风", role: "guard", model: "e2e-model" },
          { name: "5号 警徽定狼", role: "witch", model: "e2e-model" },
          { name: "6号 警徽低语", role: "villager", model: "e2e-model" },
          { name: "7号 雾灯守灯", role: "villager", model: "e2e-model" },
          { name: "8号 守夜潜行", role: "villager", model: "e2e-model" },
        ],
      },
    }),
    playbackEvent(2, {
      type: "phase_started",
      round: 1,
      phase: "night",
      payload: { active_players: ["1号 暗巷观星", "2号 暗牌验心", "3号 票台换票", "4号 狼啸听风", "5号 警徽定狼"] },
    }),
    playbackEvent(3, {
      type: "action_parsed",
      round: 1,
      phase: "night",
      actor: "1号 暗巷观星",
      action: "werewolf_kill_vote",
      payload: { choice: "8号 守夜潜行", vote_round: 1 },
    }),
    playbackEvent(4, {
      type: "action_parsed",
      round: 1,
      phase: "night",
      actor: "2号 暗牌验心",
      action: "werewolf_kill_vote",
      payload: { choice: "8号 守夜潜行", vote_round: 1 },
    }),
    playbackEvent(5, {
      type: "action_parsed",
      round: 1,
      phase: "night",
      actor: null,
      action: "remove",
      payload: { choice: "8号 守夜潜行", vote_round: 1, final_target: true },
    }),
    playbackEvent(6, {
      type: "action_parsed",
      round: 1,
      phase: "night",
      actor: "5号 警徽定狼",
      action: "witch_save",
      payload: { choice: "8号 守夜潜行" },
    }),
    playbackEvent(7, {
      type: "action_parsed",
      round: 1,
      phase: "night",
      actor: "5号 警徽定狼",
      action: "witch_poison",
      payload: { choice: "skip" },
    }),
    playbackEvent(8, {
      type: "state_updated",
      round: 1,
      phase: "night",
      payload: {
        active_players: [
          "1号 暗巷观星",
          "2号 暗牌验心",
          "3号 票台换票",
          "4号 狼啸听风",
          "5号 警徽定狼",
          "6号 警徽低语",
          "7号 雾灯守灯",
          "8号 守夜潜行",
        ],
        attacked: "8号 守夜潜行",
        eliminated: null,
        saved_by_witch: "8号 守夜潜行",
      },
    }),
    playbackEvent(9, {
      type: "phase_started",
      round: 1,
      phase: "vote",
      payload: {
        active_players: [
          "1号 暗巷观星",
          "2号 暗牌验心",
          "3号 票台换票",
          "4号 狼啸听风",
          "5号 警徽定狼",
          "6号 警徽低语",
          "7号 雾灯守灯",
          "8号 守夜潜行",
        ],
      },
    }),
    playbackEvent(10, {
      type: "action_parsed",
      round: 1,
      phase: "vote",
      actor: "6号 警徽低语",
      action: "vote",
      payload: { choice: "1号 暗巷观星" },
    }),
    playbackEvent(11, {
      type: "action_parsed",
      round: 1,
      phase: "vote",
      actor: "7号 雾灯守灯",
      action: "vote",
      payload: { choice: "1号 暗巷观星" },
    }),
    playbackEvent(12, {
      type: "action_parsed",
      round: 1,
      phase: "vote",
      actor: "8号 守夜潜行",
      action: "vote",
      payload: { choice: "2号 暗牌验心" },
    }),
    playbackEvent(13, {
      type: "state_updated",
      round: 1,
      phase: "vote",
      payload: {
        active_players: [
          "2号 暗牌验心",
          "3号 票台换票",
          "4号 狼啸听风",
          "5号 警徽定狼",
          "6号 警徽低语",
          "7号 雾灯守灯",
          "8号 守夜潜行",
        ],
        exiled: "1号 暗巷观星",
        votes: {
          "6号 警徽低语": "1号 暗巷观星",
          "7号 雾灯守灯": "1号 暗巷观星",
          "8号 守夜潜行": "2号 暗牌验心",
        },
      },
    }),
    playbackEvent(14, {
      type: "game_completed",
      round: 1,
      phase: "summary",
      payload: { winner: "好人阵营" },
    }),
  ];
}

async function installLiveReplayFixture(page: Page) {
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

    if (path === "/api/v1/games/session-e2e/playback") {
      await route.fulfill({
        json: {
          session_id: "session-e2e",
          status: "complete",
          rule_set: {
            id: "classic_8",
            version: "e2e",
            name: "经典 8 人局",
            player_count: 8,
            roles: [],
          },
          resumable: false,
          voices: [],
          events: buildPlaybackEvents(),
        },
      });
      return;
    }

    await route.fulfill({
      status: 404,
      json: { detail: `Unhandled fixture: ${path}` },
    });
  });
}

async function catchUpToLatest(page: Page) {
  await page.getByRole("button", { name: "最新" }).click();
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
}

test.describe("mobile live action visibility", () => {
  test("shows night action, vote, tally and exile from saved playback", async ({
    page,
  }) => {
    await installMobileApiFixtures(page);
    await installLiveReplayFixture(page);
    await page.goto("/games/session-e2e/live-replay");

    await catchUpToLatest(page);

    const stage = page.getByRole("status", { name: "当前舞台" });
    await expect(stage).toBeVisible();
    // The latest moment is the game completion; the rail should hold the exile.
    const rail = page.getByRole("log");
    await expect(rail).toContainText("被放逐");
    await expect(rail).toContainText("1号 刀票 -> 8号");
    await expect(rail).toContainText("2号 刀票 -> 8号");
    await expect(rail).toContainText("最终狼刀 -> 8号");

    await expectNoHorizontalOverflow(page);
  });

  test("opens the event sheet and restores focus on close", async ({
    page,
  }) => {
    await installMobileApiFixtures(page);
    await installLiveReplayFixture(page);
    await page.goto("/games/session-e2e/live-replay");
    await catchUpToLatest(page);

    const trigger = page.getByRole("button", { name: /查看全部战报，共 \d+ 条/ });
    await trigger.click();

    const dialog = page.getByRole("dialog", { name: "本轮战报" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("1号 刀票 -> 8号");
    await expect(dialog).toContainText("2号 刀票 -> 8号");
    await expect(dialog).toContainText("最终狼刀 -> 8号");
    await expect(dialog).toContainText("被放逐");

    await dialog.getByRole("button", { name: "关闭" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test("selecting an event seeks the replay and returns to latest", async ({
    page,
  }) => {
    await installMobileApiFixtures(page);
    await installLiveReplayFixture(page);
    await page.goto("/games/session-e2e/live-replay");
    await catchUpToLatest(page);

    await page.getByRole("button", { name: /查看全部战报，共 \d+ 条/ }).click();
    const dialog = page.getByRole("dialog", { name: "本轮战报" });
    await dialog
      .getByRole("button", { name: /跳转到战报：投票阶段开始/ })
      .click();

    await expect(dialog).toHaveCount(0);
    const stage = page.getByRole("status", { name: "当前舞台" });
    await expect(stage).toContainText("白天投票开始");

    await page.getByRole("button", { name: "最新" }).click();
    await expect(stage).toContainText("对局完成");
  });
});

test.describe("mobile live action responsive geometry", () => {
  for (const viewport of [
    { width: 320, height: 568, name: "small-mobile" },
    { width: 390, height: 844, name: "ios-mobile" },
    { width: 412, height: 915, name: "android-mobile" },
  ]) {
    test(`keeps one viewport with no overflow at ${viewport.name}`, async ({
      page,
    }) => {
      await page.setViewportSize({
        width: viewport.width,
        height: viewport.height,
      });
      await installMobileApiFixtures(page);
      await installLiveReplayFixture(page);
      await page.goto("/games/session-e2e/live-replay");
      await catchUpToLatest(page);

      await expectNoHorizontalOverflow(page);

      // Rail, subtitle region and control deck are distinct rows.
      const controlDeck = page.locator(
        'footer.mobile-live-control-deck[aria-label="实时观战操作"]',
      );
      await expect(controlDeck).toBeVisible();
    });
  }
});

test.describe("mobile live action reduced motion", () => {
  test("disables nonessential animation while keeping text visible", async ({
    page,
  }) => {
    await page.context().addInitScript(() => {
      const matchMedia = window.matchMedia;
      window.matchMedia = (query: string) => ({
        ...matchMedia(query),
        matches: query.includes("prefers-reduced-motion: reduce"),
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
        onchange: null,
        media: query,
      });
    });
    await installMobileApiFixtures(page);
    await installLiveReplayFixture(page);
    await page.goto("/games/session-e2e/live-replay");
    await catchUpToLatest(page);

    const stage = page.getByRole("status", { name: "当前舞台" });
    await expect(stage).toBeVisible();
    await expect(stage).toContainText(/对局完成|被放逐/);
  });
});
