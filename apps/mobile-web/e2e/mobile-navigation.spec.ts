import { expect, test, type Page } from "@playwright/test";

const emptyProfilePage = {
  items: [],
  pagination: { page: 1, page_size: 100, total: 0, pages: 0 },
};

async function installApiFixtures(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === "/api/v1/public/session") {
      await route.fulfill({
        json: {
          csrf_token: "mobile-e2e-csrf",
          session_expires_at: "2099-01-01T00:00:00Z",
        },
      });
      return;
    }

    if (path === "/api/v1/public/me/favorite-player-profiles") {
      await route.fulfill({ json: { profile_ids: [] } });
      return;
    }

    if (path === "/api/v1/public/player-profiles") {
      await route.fulfill({ json: emptyProfilePage });
      return;
    }

    if (path === "/api/v1/games/rule-sets") {
      await route.fulfill({
        json: {
          rule_sets: [
            {
              id: "starter_6",
              version: "e2e",
              name: "新手 6 人快局",
              player_count: 6,
              role_summary: "1 狼人 / 1 预言家 / 1 守卫 / 3 村民",
              roles: [],
            },
          ],
        },
      });
      return;
    }

    if (path === "/api/v1/games") {
      await route.fulfill({ json: { sessions: [] } });
      return;
    }

    await route.fulfill({ status: 404, json: { detail: "Unhandled E2E fixture" } });
  });
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

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("mobile-only primary navigation stays usable without horizontal overflow", async ({
  page,
}) => {
  await page.goto("/games");
  await expect(page.getByRole("heading", { name: "狼人杀对局大厅" })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.getByRole("link", { name: "玩家图鉴" }).click();
  await expect(page.getByRole("heading", { name: "玩家图鉴" })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.getByRole("link", { name: "对局记录" }).click();
  await expect(page.getByRole("heading", { name: "对局历史" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
