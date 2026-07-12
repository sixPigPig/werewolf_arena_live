import { expect, test, type Page } from "@playwright/test";

import { installMobileApiFixtures } from "./support/mobile-api-fixtures";

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
  await installMobileApiFixtures(page);
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
