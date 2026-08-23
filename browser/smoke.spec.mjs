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
  const selectedLines = await page.locator("[data-selected-lines]").evaluateAll(
    (elements) =>
      elements.map((element) =>
        JSON.parse(element.getAttribute("data-selected-lines")),
      ),
  );
  expect(selectedLines[0]).toEqual([
    expect.objectContaining({
      id: "line:186",
      filterMode: "destination",
      filterStationIds: ["Master:2"],
    }),
  ]);
  await expect(
    page.locator("summary", { hasText: "Legacy-Konfiguration" }),
  ).toHaveCount(2);
  await expect(page).toHaveScreenshot("settings-desktop.png", {
    animations: "disabled",
    caret: "hide",
    maxDiffPixelRatio: 0.1,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  const mobileLayout = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(mobileLayout).toBe(true);
});
