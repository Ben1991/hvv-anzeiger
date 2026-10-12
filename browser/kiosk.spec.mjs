import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { spawn } from 'node:child_process';
import net from 'node:net';
import { fileURLToPath } from 'node:url';

let server, base, log = '';
test.beforeAll(async () => {
  const reservation = net.createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  base = `http://127.0.0.1:${port}`;
  server = spawn(process.env.HVV_BROWSER_PYTHON || 'python', ['-m', 'browser.kiosk_server', '--port', String(port)], {
    cwd:fileURLToPath(new URL('../', import.meta.url)), windowsHide:true, stdio:'pipe'
  });
  server.on('error', error => { log += String(error); });
  server.stderr.on('data', data => { log += data.toString(); });
});
test.afterAll(async () => { server?.kill(); });
async function open(page) {
  await expect.poll(async () => {
    try { return (await page.request.get(base + '/display')).status(); }
    catch { return log; }
  }).toBe(200);
  await page.goto(base + '/display');
}

test('semantic display passes axe, keyboard, reduced motion and responsive screenshots', async ({page}, info) => {
  await page.emulateMedia({reducedMotion:'reduce'});
  await open(page);
  await expect(page.getByRole('list')).toHaveCount(1);
  await expect(page.getByRole('listitem')).toHaveCount(3);
  await expect(page.getByRole('listitem').nth(0)).toContainText('Verspätung: +3 min');
  await expect(page.getByRole('listitem').nth(1)).toContainText('Ausfall');
  const contrasts = await page.locator('.line').first().evaluate(badge => {
    const original = badge.className;
    const luminance = rgb => {
      const values = rgb.match(/\d+/g).slice(0,3).map(Number).map(v => {
        const n = v / 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4;
      });
      return .2126 * values[0] + .7152 * values[1] + .0722 * values[2];
    };
    const result = ['bus','u1','u2','u3','u4','sbahn','s2','s3','s5','s7','akn','regional','xpress','night','ferry','neutral'].map(token => {
      badge.className = `line line-badge line-badge-${token}`;
      const style = getComputedStyle(badge);
      const a = luminance(style.color), b = luminance(style.backgroundColor);
      return {token, ratio:(Math.max(a,b) + .05) / (Math.min(a,b) + .05)};
    });
    badge.className = original;
    return result;
  });
  for (const {token,ratio} of contrasts) expect(ratio, token).toBeGreaterThanOrEqual(4.5);
  expect((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa','wcag22aa']).analyze()).violations).toEqual([]);
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', {name:'Standardansicht'})).toBeFocused();
  expect(await page.locator('a.display-exit').evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid');
  await page.getByRole('button', {name:'Aktualisierung pausieren'}).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', {name:'Aktualisierung fortsetzen'})).toHaveAttribute('aria-pressed','true');
  expect(await page.evaluate(() => getComputedStyle(document.querySelector('.display-shell')).animationName)).toBe('none');
  for (const [label, width, height] of [['desktop',1280,960],['mobile',390,844]]) {
    await page.setViewportSize({width,height});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const screenshot = info.outputPath(`kiosk-${label}.png`);
    await page.screenshot({path:screenshot,fullPage:true,animations:'disabled'});
    await info.attach(`kiosk-${label}`, {path:screenshot,contentType:'image/png'});
    expect((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations).toEqual([]);
  }
  // Text-only zoom 200% stresses reflow in addition to a narrow viewport.
  await page.addStyleTag({content:':root{font-size:200%}'});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('link',{name:'Standardansicht'})).toBeVisible();
  expect((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze()).violations).toEqual([]);
});

test('offline refresh retains rows, backs off, expires and recovers without reloading', async ({page}) => {
  await page.clock.install();
  await open(page);
  const original = await page.locator('#display-board').textContent();
  let attempts = 0;
  await page.route('**/api/display', route => { attempts++; return route.abort(); });
  await page.clock.runFor(16000);
  await expect(page.locator('#display-state')).toContainText('Verbindung unterbrochen');
  expect(await page.locator('#display-board').textContent()).toBe(original);
  expect(attempts).toBe(1);
  await page.clock.runFor(20000);
  expect(attempts).toBe(1);
  await page.clock.runFor(11000);
  await expect.poll(() => attempts).toBe(2);
  await page.clock.runFor(255000);
  await expect(page.locator('#display-board')).toContainText('Letzter Stand zu alt');
  await expect(page.locator('#display-age')).not.toHaveText('unbekannt');
  await page.unroute('**/api/display');
  await page.clock.runFor(300000);
  await expect(page.getByRole('listitem')).toHaveCount(3);
  await expect(page.locator('#display-state')).toContainText('Daten aktuell');
  await expect(page.getByRole('button',{name:'Aktualisierung pausieren'})).toBeVisible();
});

test('authentication failure stops retries and fullscreen denial preserves the page', async ({page}) => {
  await page.clock.install();
  await open(page);
  const button = page.getByRole('button',{name:'Vollbild',exact:true});
  if (await button.isVisible()) {
    await button.click();
    await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(true);
    await page.getByRole('button',{name:'Vollbild verlassen',exact:true}).click();
    await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(false);
    await page.evaluate(() => { document.documentElement.requestFullscreen = () => Promise.reject(new Error('denied')); });
    await button.click();
    await expect(page.getByRole('status')).toContainText('Vollbild nicht verfügbar');
    await expect(page.getByRole('listitem')).toHaveCount(3);
  }
  let attempts = 0;
  await page.route('**/api/display', route => { attempts++; return route.fulfill({status:401,body:'Unauthorized'}); });
  await page.clock.runFor(16000);
  await expect(page.locator('#display-state')).toContainText('Anmeldung erforderlich');
  await page.clock.runFor(300000);
  expect(attempts).toBe(1);
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
});

test('ordinary refresh stays quiet and status changes are announced once', async ({page}) => {
  await page.clock.install();
  await open(page);
  const data = await (await page.request.get(base + '/api/display')).json();
  await page.route('**/api/display', route => route.fulfill({json:data}));
  await page.clock.runFor(16000);
  await expect(page.getByRole('status')).toBeEmpty();
  data.signal = 'changed';
  data.change_summary = 'Abfahrtsstatus geändert: 2 Ausfälle, 1 Verspätungen.';
  await page.clock.runFor(16000);
  await expect(page.getByRole('status')).toHaveText(data.change_summary);
  await page.evaluate(() => {
    window.announcementChanges = 0;
    new MutationObserver(() => window.announcementChanges++).observe(document.querySelector('#display-announcement'), {childList:true,subtree:true});
  });
  await page.clock.runFor(16000);
  expect(await page.evaluate(() => window.announcementChanges)).toBe(0);
});
