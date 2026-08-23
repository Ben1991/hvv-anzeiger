import { chromium } from "playwright";

const baseURL = process.env.HVV_BROWSER_BASE_URL || "http://127.0.0.1:18080";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  colorScheme: "dark",
  viewport: { width: 1440, height: 1000 },
});

await page.goto(baseURL + "/");
await page.screenshot({ path: "docs/web-dashboard.png", fullPage: true });

await page.goto(baseURL + "/settings");
await page.screenshot({ path: "docs/web-settings.png", fullPage: true });
await page
  .locator("section.card", { hasText: "Haltestellen und Linien" })
  .screenshot({ path: "docs/web-stations.png" });

await browser.close();
