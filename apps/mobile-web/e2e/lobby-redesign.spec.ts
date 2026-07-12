import { expect, test } from "@playwright/test";

import { installMobileApiFixtures } from "./support/mobile-api-fixtures";

test("lobby exposes one rule summary and one fixed launch action", async ({
  page,
}) => {
  await installMobileApiFixtures(page);
  await page.goto("/games");

  const summary = page.getByRole("region", { name: "当前规则" });
  await expect(summary).toContainText("经典 8 人局");
  await expect(page.getByRole("group", { name: "规则选择指示" })).toHaveCount(0);
  await expect(page.locator(".mobile-lobby-rule-scroll")).toHaveCount(0);
  await expect(
    page.locator(".mobile-lobby-launch-bar").getByRole("button"),
  ).toHaveCount(1);

  await summary.getByRole("button", { name: "更换规则" }).click();
  const picker = page.getByRole("dialog", { name: "选择规则" });
  await picker.getByRole("button", { name: "选择规则 新手 6 人快局" }).click();

  await expect(summary).toContainText("新手 6 人快局");
  await expect(
    page.getByRole("button", { name: "选择 6 号座位，当前为 待选择" }),
  ).toBeVisible();
});

test("player confirmation advances inside the same modal", async ({ page }) => {
  await installMobileApiFixtures(page);
  await page.goto("/games");

  await page
    .getByRole("button", { name: "选择 1 号座位，当前为 待选择" })
    .click();
  const picker = page.getByRole("dialog", { name: "玩家卡牌库" });
  await picker
    .getByRole("button", { name: "为 1 号座位候选 暗巷观星" })
    .click();
  await picker.getByRole("button", { name: "确认并下一位" }).click();

  await expect(picker.getByText(/当前选择：2号座位/)).toBeVisible();
  await expect(picker.getByRole("searchbox", { name: "搜索玩家" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "选择 1 号座位，当前为 暗巷观星" }),
  ).toBeVisible();
});

test("combined filters stay inside the modal and support keyboard activation", async ({
  page,
}) => {
  await installMobileApiFixtures(page);
  await page.goto("/games");
  await page
    .getByRole("button", { name: "选择 1 号座位，当前为 待选择" })
    .click();

  const dialog = page.getByRole("dialog", { name: "玩家卡牌库" });
  await dialog
    .getByRole("button", { name: "筛选玩家，当前 全部玩家、全部策略" })
    .click();

  const favoriteTrigger = dialog.getByRole("button", {
    name: "收藏筛选，当前 全部玩家",
  });
  await favoriteTrigger.click();
  const favoritePopup = dialog
    .locator(".mobile-bottom-select-picker-popup")
    .filter({ hasText: "选择收藏筛选" });
  await expect(favoritePopup.getByText("选择收藏筛选")).toBeVisible();
  const favoriteNext = favoritePopup.getByRole("button", {
    name: "选择下一项：只看收藏",
  });
  await expect(favoriteNext).toHaveAttribute("tabindex", "0");
  await favoriteNext.focus();
  await page.keyboard.press("Enter");
  await expect(
    favoritePopup.getByRole("button", { name: "当前选择的是：只看收藏" }),
  ).toBeVisible();
  const favoriteConfirm = favoritePopup.getByRole("button", { name: "确定" });
  await favoriteConfirm.focus();
  await page.keyboard.press("Enter");
  await expect(favoritePopup).toHaveCount(0);
  await expect(
    dialog.getByRole("button", { name: "收藏筛选，当前 只看收藏" }),
  ).toBeVisible();

  const strategyTrigger = dialog.getByRole("button", {
    name: "策略筛选，当前 全部策略",
  });
  await strategyTrigger.click();
  const strategyPopup = dialog
    .locator(".mobile-bottom-select-picker-popup")
    .filter({ hasText: "选择策略筛选" });
  await expect(strategyPopup.getByText("选择策略筛选")).toBeVisible();
  const strategyNext = strategyPopup.getByRole("button", {
    name: "选择下一项：分析型",
  });
  await strategyNext.focus();
  await page.keyboard.press("Enter");
  await expect(
    strategyPopup.getByRole("button", { name: "当前选择的是：分析型" }),
  ).toBeVisible();
  const strategyConfirm = strategyPopup.getByRole("button", { name: "确定" });
  await strategyConfirm.focus();
  await page.keyboard.press("Enter");
  await expect(strategyPopup).toHaveCount(0);
  await expect(
    dialog.getByRole("button", { name: "策略筛选，当前 分析型" }),
  ).toBeVisible();
});

test("small lobby has readable non-overlapping content and an isolated picker", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "small-mobile", "320x568 geometry contract");
  await installMobileApiFixtures(page);
  await page.goto("/games");

  const secondRowSeat = page.locator(".mobile-lobby-seat-card").nth(4);
  const launchBar = page.locator(".mobile-lobby-launch-region");
  const launchBarContent = page.locator(".mobile-lobby-launch-bar");
  const launchButton = page.locator(".mobile-lobby-launch-button");
  const tabBar = page.getByRole("navigation", { name: "移动端主导航" });
  const advanced = page.locator(".mobile-lobby-advanced");
  const [seatBox, launchBox, tabBox] = await Promise.all([
    secondRowSeat.boundingBox(),
    launchBar.boundingBox(),
    tabBar.boundingBox(),
  ]);
  expect(seatBox).not.toBeNull();
  expect(launchBox).not.toBeNull();
  expect(tabBox).not.toBeNull();
  expect((seatBox?.y ?? 0) + (seatBox?.height ?? 0)).toBeLessThanOrEqual(
    launchBox?.y ?? 0,
  );
  expect((launchBox?.y ?? 0) + (launchBox?.height ?? 0)).toBeLessThanOrEqual(
    tabBox?.y ?? 0,
  );
  const launchWidths = await launchBarContent.evaluate((element) => {
    const style = getComputedStyle(element);
    const contentWidth =
      element.getBoundingClientRect().width -
      Number.parseFloat(style.paddingLeft) -
      Number.parseFloat(style.paddingRight);
    const buttonWidth =
      element.querySelector("button")?.getBoundingClientRect().width ?? 0;
    return { buttonWidth, contentWidth };
  });
  expect(launchWidths.buttonWidth).toBeCloseTo(launchWidths.contentWidth, 0);
  await expect(launchButton).toBeVisible();

  await page.locator(".mobile-content-region").evaluate((element) => {
    element.scrollTo({ top: element.scrollHeight });
  });
  const [advancedBox, launchBoxAfterScroll] = await Promise.all([
    advanced.boundingBox(),
    launchBar.boundingBox(),
  ]);
  expect((advancedBox?.y ?? 0) + (advancedBox?.height ?? 0)).toBeLessThanOrEqual(
    launchBoxAfterScroll?.y ?? 0,
  );
  expect(
    await secondRowSeat.locator("strong").evaluate((element) =>
      Number.parseFloat(getComputedStyle(element).fontSize),
    ),
  ).toBeGreaterThanOrEqual(12);

  const defaultTextSelectors = [
    ".mobile-lobby-rule-summary-copy p",
    ".mobile-lobby-seat-summary",
    ".mobile-lobby-advanced summary",
    ".mobile-lobby-launch-bar > span",
  ];
  for (const selector of defaultTextSelectors) {
    const fontSize = await page.locator(selector).evaluate((element) =>
      Number.parseFloat(getComputedStyle(element).fontSize),
    );
    expect(fontSize, `${selector} font size`).toBeGreaterThanOrEqual(12);
  }

  const defaultTargetSelectors = [
    ".mobile-lobby-rule-summary > button",
    ".mobile-lobby-lineup-actions > button",
    ".mobile-lobby-advanced summary",
    ".mobile-lobby-launch-button",
  ];
  for (const selector of defaultTargetSelectors) {
    const boxes = await page.locator(selector).evaluateAll((elements) =>
      elements.map((element) => {
        const rect = element.getBoundingClientRect();
        return { height: rect.height, width: rect.width };
      }),
    );
    for (const box of boxes) {
      expect(box.width, `${selector} width`).toBeGreaterThanOrEqual(44);
      expect(box.height, `${selector} height`).toBeGreaterThanOrEqual(44);
    }
  }

  const firstSeat = page.getByRole("button", {
    name: "选择 1 号座位，当前为 待选择",
  });
  await firstSeat.click();
  const dialog = page.getByRole("dialog", { name: "玩家卡牌库" });
  const modalLayerBox = await page.locator(".mobile-lobby-modal-layer").boundingBox();
  const viewport = page.viewportSize();
  expect(modalLayerBox).not.toBeNull();
  expect(modalLayerBox?.x).toBe(0);
  expect(modalLayerBox?.y).toBe(0);
  expect(modalLayerBox?.width).toBe(viewport?.width);
  expect(modalLayerBox?.height).toBe(viewport?.height);
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".mobile-lobby-content")).toHaveAttribute("inert", "");
  await expect(page.getByRole("navigation", { name: "移动端主导航" })).toBeHidden();

  const visibleRows = await page.locator(".mobile-profile-row").evaluateAll((rows) =>
    rows.filter((row) => {
      const rect = row.getBoundingClientRect();
      return rect.bottom > 0 && rect.top < window.innerHeight;
    }).length,
  );
  expect(visibleRows).toBeGreaterThanOrEqual(5);

  const pickerTextSelectors = [
    ".mobile-lobby-modal-header p",
    ".mobile-profile-filter-trigger",
    ".mobile-profile-row-copy small",
    ".mobile-profile-refresh-status span",
  ];
  for (const selector of pickerTextSelectors) {
    const fontSize = await page.locator(selector).first().evaluate((element) =>
      Number.parseFloat(getComputedStyle(element).fontSize),
    );
    expect(fontSize, `${selector} font size`).toBeGreaterThanOrEqual(12);
  }

  const targetSelectors = [
    ".mobile-lobby-modal-header button",
    ".mobile-profile-filter-trigger",
    ".mobile-profile-row > button:last-child",
    ".mobile-profile-picker-footer button",
  ];
  for (const selector of targetSelectors) {
    const box = await page.locator(selector).first().boundingBox();
    expect(box?.width ?? 0, `${selector} width`).toBeGreaterThanOrEqual(44);
    expect(box?.height ?? 0, `${selector} height`).toBeGreaterThanOrEqual(44);
  }

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(firstSeat).toBeFocused();
});

test("smart fill and advanced settings produce the preserved create payload", async ({
  page,
}) => {
  const { createRequests } = await installMobileApiFixtures(page);
  await page.goto("/games");

  await page.getByRole("button", { name: "智能补齐" }).click();
  await page.getByRole("button", { name: "随机补齐" }).click();
  const launch = page.locator(".mobile-lobby-launch-bar").getByRole("button");
  await expect(launch).toHaveAccessibleName("开始对局");

  await page.getByText("高级设置 · 随机种子 / 8轮").click();
  await page.getByRole("spinbutton", { name: "种子" }).fill("42");
  await page.getByRole("spinbutton", { name: "最大轮数" }).fill("10");
  await launch.click();

  await expect.poll(() => createRequests.length).toBe(1);
  expect(createRequests[0]).toMatchObject({
    rule_set_id: "classic_8",
    seed: 42,
    max_rounds: 10,
  });
  expect(createRequests[0].player_configs).toHaveLength(8);
  expect(createRequests[0].player_configs?.map((config) => config.seat)).toEqual([
    1, 2, 3, 4, 5, 6, 7, 8,
  ]);
});
