import { expect, test } from "@playwright/test";

test("dashboard, display mode, and settings have stable product surfaces", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Abfahrten · HVV-Anzeiger/);
  await expect(page.getByRole("heading", { name: "Abfahrten" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Displaymodus" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Einstellungen" })).toBeVisible();

  await page.getByRole("link", { name: "Displaymodus" }).click();
  await expect(page.locator("body")).toHaveClass(/display-page/);
  await expect(page.locator("a.display-exit")).toBeVisible();
  await expect(page.locator('meta[http-equiv="refresh"]')).toHaveAttribute(
    "content",
    "15",
  );
  await expect(page).toHaveScreenshot("display-desktop.png", {
    animations: "disabled",
    caret: "hide",
    maxDiffPixelRatio: 0.1,
  });

  await page.locator("a.display-exit").click();
  await page.getByRole("link", { name: "Einstellungen" }).click();
  await expect(page).toHaveTitle(/Einstellungen · HVV-Anzeiger/);
  await expect(page.getByRole("heading", { name: "Einstellungen" })).toBeVisible();
  await expect(page.locator("#display\\.time_mode")).toBeVisible();
  await expect(page.locator('[data-load-lines]')).toHaveCount(2);
  await expect(
    page.locator("summary", { hasText: "Legacy-Konfiguration" }),
  ).toHaveCount(2);
  await expect(page).toHaveScreenshot("settings-desktop.png", {
    animations: "disabled",
    caret: "hide",
    maxDiffPixelRatio: 0.1,
  });
});
