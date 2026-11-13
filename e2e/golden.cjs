// Browser end-to-end test of the hosted-demo acceptance path.
// Usage: BASE_URL=http://localhost:8000 node e2e/golden.cjs   (the API must serve the built web app)
// Exits non-zero on the first failed step. Writes screenshots to e2e/artifacts/.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.BASE_URL || "http://localhost:8000";
const OUT = path.join(__dirname, "artifacts");
const results = [];

async function step(name, fn) {
  const t = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - t });
    console.log(`  ok   ${name} (${Date.now() - t} ms)`);
  } catch (e) {
    results.push({ name, ok: false, error: String(e) });
    console.log(`  FAIL ${name}\n       ${e}`);
    throw e;
  }
}

const tableState = (page, label, state) =>
  page.waitForSelector(`[data-testid="table-${label}"][data-state="${state}"]`, { timeout: 15000 });

async function startDemo(browser, viewport) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.goto(BASE);
  await page.click('[data-testid="start-demo"]');
  await page.waitForSelector('[data-testid="demo-bar"]');
  return { ctx, page };
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  let failed = false;
  try {
    const { page } = await startDemo(browser, { width: 1366, height: 900 });

    await step("1. reviewer enters a private demo restaurant with seeded data", async () => {
      await tableState(page, "T7", "occupied");
      await tableState(page, "T2", "ready");
      await tableState(page, "T5", "needs_clearing");
      if ((await page.locator('[data-testid^="table-"]').count()) !== 12) throw new Error("expected 12 tables");
      if ((await page.locator('[data-testid^="party-"]:not(input):not(button)').count()) < 5) throw new Error("expected 5 waiting parties");
      await page.waitForSelector('[data-testid="connection"]:has-text("Live")');
    });

    await step("2. staged scenario: camera seats a walk-in at T2", async () => {
      await page.selectOption('[data-testid="demo-speed"]', "10");
      await page.click('[data-testid="demo-play"]');
      await tableState(page, "T2", "occupied");
    });

    await step("3. party leaves T7: Needs clearing and exactly one alert", async () => {
      await tableState(page, "T7", "needs_clearing");
      await page.waitForSelector('[data-testid="toast"]:has-text("T7 needs clearing")');
      const n = await page.locator('[data-testid="alerts"] li:has-text("T7")').count();
      if (n !== 1) throw new Error(`expected 1 alert for T7, got ${n}`);
      await page.screenshot({ path: path.join(OUT, "dashboard.png") });
    });

    await step("4. staff acknowledge the alert and mark the table Ready", async () => {
      await page.click('[data-testid="ack-T7"]');
      await page.waitForSelector('[data-testid="table-T7"] :text("Ack:")');
      await page.click('[data-testid="ready-T7"]');
      await tableState(page, "T7", "ready");
      await page.waitForSelector('[data-testid="manual-T7"]');
    });

    await step("5. the next eligible party is suggested and the host seats them", async () => {
      const text = await page.textContent('[data-testid="seat-T7"]');
      if (!text.includes("Kim (4)")) throw new Error(`expected Kim (4) to be suggested, got "${text}"`);
      await page.click('[data-testid="seat-T7"]');
      await tableState(page, "T7", "occupied");
      await page.waitForSelector('[data-testid="party-Kim"]', { state: "detached" });
      await page.waitForSelector('[data-testid="party-Lee"]');
    });

    await step("6. table history shows every step with its source", async () => {
      await page.click('[data-testid="history-T7"]');
      const sheet = page.locator('[data-testid="history"]');
      await sheet.locator("text=Needs clearing → Ready").first().waitFor();
      await sheet.locator("text=Occupied → Needs clearing").first().waitFor();
      await sheet.locator("text=Ready → Occupied").first().waitFor();
      await sheet.locator("button:has-text('Close')").click();
    });

    await step("7. camera outage: banner, manual operation, recovery without surprise changes", async () => {
      await tableState(page, "T12", "needs_clearing"); // the dinner scenario has finished
      await page.click('[data-testid="demo-outage"]');
      await page.waitForSelector('[data-testid="offline-banner"]');
      await page.click('[data-testid="table-T1"] button:has-text("Party left")');
      await tableState(page, "T1", "needs_clearing");
      await page.waitForSelector('[data-testid="offline-banner"]', { state: "detached", timeout: 15000 });
      await page.waitForSelector('[data-testid="demo-note"]:has-text("Automation resumes")');
      await tableState(page, "T1", "needs_clearing");
      await tableState(page, "T3", "occupied");
    });

    await step("8. reset restores the seed without affecting another viewer", async () => {
      const second = await startDemo(browser, { width: 1024, height: 768 }); // tablet
      await second.page.click('[data-testid="ready-T5"]');
      await tableState(second.page, "T5", "ready");
      const t0 = Date.now();
      await page.click('[data-testid="demo-reset"]');
      await tableState(page, "T7", "occupied");
      await tableState(page, "T5", "needs_clearing");
      await page.waitForSelector('[data-testid="party-Kim"]');
      if (Date.now() - t0 > 5000) throw new Error("reset took longer than 5 s");
      await second.page.waitForTimeout(500);
      await tableState(second.page, "T5", "ready"); // viewer two keeps their own state
      await second.page.screenshot({ path: path.join(OUT, "tablet.png") });
      await second.ctx.close();
    });

    await step("9. roles: floor staff cannot edit the waitlist or open setup", async () => {
      await page.selectOption('[data-testid="demo-role"]', "staff");
      await page.waitForSelector('[data-testid="role"]:has-text("staff")');
      if (await page.locator('[data-testid="party-add"]').count()) throw new Error("staff can add parties");
      if (await page.locator('a[href="#/setup"]').count()) throw new Error("staff can see Setup");
      await page.selectOption('[data-testid="demo-role"]', "host");
      await page.waitForSelector('[data-testid="party-add"]');
      await page.fill('[data-testid="party-name"]', "Walk-in");
      await page.fill('[data-testid="party-size"]', "2");
      await page.click('[data-testid="party-add"]');
      await page.waitForSelector('[data-testid="party-Walk-in"]');
      await page.selectOption('[data-testid="demo-role"]', "admin");
      await page.waitForSelector('a[href="#/setup"]');
    });

    await step("10. admin setup and analytics", async () => {
      await page.click('a[href="#/setup"]');
      await page.fill('[data-testid="new-table-label"]', "T13");
      await page.click('[data-testid="new-table-add"]');
      await page.click('[data-testid="tab-zones"]');
      await page.selectOption('[data-testid="zone-table"]', { label: "T13" });
      const box = await page.locator('[data-testid="zone-canvas"]').boundingBox();
      for (const [x, y] of [[0.82, 0.1], [0.95, 0.1], [0.95, 0.3], [0.82, 0.3]]) {
        await page.mouse.click(box.x + box.width * x, box.y + box.height * y);
      }
      await page.click('[data-testid="zone-add"]');
      await page.waitForSelector('[data-testid="toast"]:has-text("Zone saved for T13")');
      await page.screenshot({ path: path.join(OUT, "zones.png") });
      await page.click('a[href="#/analytics"]');
      await page.waitForFunction(() => Number(document.querySelector('[data-testid="tile-turns"]')?.textContent) > 50);
      await page.screenshot({ path: path.join(OUT, "analytics.png") });
      await page.click('a[href="#/"]');
      await page.waitForSelector('[data-testid="table-T13"][data-state="ready"]');
    });
  } catch (e) {
    failed = true;
  } finally {
    await browser.close();
    const lines = ["# End-to-end results", "", `Target: ${BASE}`, "", "| Step | Result |", "|---|---|",
      ...results.map((r) => `| ${r.name} | ${r.ok ? "pass" : "FAIL: " + r.error.split("\n")[0]} |`)];
    fs.writeFileSync(path.join(OUT, "results.md"), lines.join("\n") + "\n");
    console.log(failed ? "\nE2E FAILED" : `\nE2E passed: ${results.length} steps`);
    process.exit(failed ? 1 : 0);
  }
})();
