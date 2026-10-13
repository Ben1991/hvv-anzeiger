import { expect, test } from "@playwright/test";
import { spawn } from "node:child_process";
import { copyFile, mkdir, readFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

test("configuration export, preview, cancel, import and restore work end to end", async ({ page }, testInfo) => {
  // A separate service and configuration keep other UI tests read-only.
  const config = testInfo.outputPath("config.json");
  await mkdir(path.dirname(config), { recursive: true });
  const repo = fileURLToPath(new URL("../", import.meta.url));
  await copyFile(path.join(repo, "browser/fixtures/config-filtered.json"), config);
  const reservation = net.createServer();
  await new Promise((resolve) => reservation.listen(0, "127.0.0.1", resolve));
  const port = reservation.address().port;
  await new Promise((resolve) => reservation.close(resolve));
  const server = spawn(process.env.HVV_BROWSER_PYTHON || "python", [
    "-m", "hvv_display.web", "--host", "127.0.0.1", "--port", String(port),
    "--config", config, "--cache", testInfo.outputPath("stations.json"),
    "--credentials", testInfo.outputPath("missing-credentials.env"),
  ], { cwd: repo, windowsHide: true, stdio: "pipe" });
  let startupError = "";
  server.on("error", (error) => { startupError = String(error); });
  server.stderr.on("data", (data) => { startupError += data.toString(); });
  const base = `http://127.0.0.1:${port}`;
  try {
    await expect.poll(async () => {
      try { return (await page.request.get(base + "/config-backup")).status(); }
      catch { return startupError; }
    }, { timeout: 10000 }).toBe(200);
    await page.goto(base + "/settings");
    await page.getByRole("link", { name: "Sicherung & Wiederherstellung" }).click();
    await expect(page.getByRole("heading", { name: "Sicherung & Wiederherstellung" })).toBeVisible();
    const downloaded = page.waitForEvent("download");
    await page.getByRole("link", { name: "Redigierte Konfiguration herunterladen" }).click();
    const download = await downloaded;
    const envelope = JSON.parse(await readFile(await download.path(), "utf8"));
    expect(envelope).toMatchObject({ format: "hvv-anzeiger-config", schema_version: 1 });
    const oldRotate = envelope.config.display.rotate;
    envelope.config.display.rotate = (oldRotate + 1) % 4;
    const input = { name: "hvv-sicherung.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(envelope)) };
    await page.locator("#config-file").setInputFiles(input);
    await page.getByRole("button", { name: "Import prüfen" }).click();
    await expect(page.getByRole("heading", { name: "Änderungen prüfen" })).toBeVisible();
    await expect(page.getByRole("table")).toContainText("Bilddrehung");
    expect(JSON.parse(await readFile(config, "utf8")).display.rotate).toBe(oldRotate);
    await page.getByRole("button", { name: "Abbrechen", exact: true }).click();
    expect(JSON.parse(await readFile(config, "utf8")).display.rotate).toBe(oldRotate);
    await page.locator("#config-file").setInputFiles(input);
    await Promise.all([
      page.waitForURL("**/config/preview"),
      page.getByRole("button", { name: "Import prüfen" }).click(),
    ]);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("button", { name: "Änderungen anwenden" }).click();
    await expect(page.getByRole("heading", { name: "Änderungen prüfen" })).toBeVisible();
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Änderungen anwenden" }).click();
    await expect(page.getByText("Gespeichert. Der Anzeigedienst übernimmt")).toBeVisible();
    expect(JSON.parse(await readFile(config, "utf8")).display.rotate).toBe(envelope.config.display.rotate);
    await page.getByRole("button", { name: "Wiederherstellung prüfen" }).first().click();
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Änderungen anwenden" }).click();
    expect(JSON.parse(await readFile(config, "utf8")).display.rotate).toBe(oldRotate);
    await expect(page.getByRole("button", { name: "Wiederherstellung prüfen" })).toHaveCount(2);
  } finally {
    server.kill();
  }
});
