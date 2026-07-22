import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

test.describe("Admin 运营工作台", () => {
  test("总览通过键盘跳转、导航和 axe 基线", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "仅桌面端运行");
    const navigationStartedAt = Date.now();
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "运营总览" }),
    ).toBeVisible();
    const overviewReadyMs = Date.now() - navigationStartedAt;

    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: "跳到主要内容" });
    await expect(skipLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#admin-main-content")).toBeFocused();

    const accessibility = await new AxeBuilder({ page })
      .include(".admin-app-shell")
      .analyze();
    expect(accessibility.violations).toEqual([]);

    const performancePath = testInfo.outputPath("overview-performance.json");
    await writeFile(performancePath, JSON.stringify({ overviewReadyMs }, null, 2));
    await testInfo.attach("overview-performance.json", {
      path: performancePath,
      contentType: "application/json",
    });
    expect(overviewReadyMs).toBeLessThan(5_000);
  });

  test("导航至玩家草稿并保留人工保存边界", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "仅桌面端运行");
    await page.goto("/");
    const playersLink = page.getByRole("link", {
      name: "虚拟玩家 草稿、发布与归档",
    });
    await expect(playersLink).toBeVisible();
    await playersLink.click();
    await expect(page.getByRole("heading", { name: "虚拟玩家" })).toBeVisible();

    const createLink = page.getByRole("link", { name: "新建玩家草稿" });
    await expect(createLink).toBeVisible();
    await createLink.click();
    await expect(
      page.getByRole("heading", { name: "新建玩家草稿" }),
    ).toBeVisible();

    const generateButton = page.getByRole("button", { name: "AI 生成草稿" });
    await expect(generateButton).toBeEnabled();
    await generateButton.click();
    await expect(
      page.getByText("AI 草稿已填入，请审核后保存"),
    ).toBeVisible();
    await expect(page.getByLabel("玩家名称")).toHaveValue("月影听风");
    const speakerSelect = page.getByRole("combobox", { name: /^玩家音色 / });
    await speakerSelect.click();
    await expect(page.getByText("voice_type", { exact: true })).toBeVisible();
    await expect(page.getByText("音色名称", { exact: true })).toBeVisible();
    const viviOption = page.getByRole("option", {
      name: "zh_female_vv_uranus_bigtts Vivi 2.0",
    });
    await expect(viviOption).toBeVisible();
    await viviOption.click();
    await expect(speakerSelect).toContainText("zh_female_vv_uranus_bigtts");
    await expect(page.getByRole("button", { name: "保存草稿" })).toBeEnabled();
    await expect(page).toHaveURL(/\/content\/players\/new$/);
  });

  test("移动端侧栏能打开、导航并自动收起", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-chromium", "仅移动端运行");
    await page.goto("/");
    const menuButton = page.getByRole("button", { name: "打开导航" });
    await expect(menuButton).toBeVisible();
    await menuButton.click();
    const sidebar = page.locator(".admin-ant-mobile-drawer");
    await expect(sidebar).toBeVisible();

    const jobsLink = sidebar.getByRole("link", {
      name: "任务中心 持久任务状态与失败诊断",
    });
    await expect(jobsLink).toBeVisible();
    await jobsLink.click();
    await expect(page.getByRole("heading", { name: "后台任务" })).toBeVisible();
    await expect(sidebar).toBeHidden();
  });
});
