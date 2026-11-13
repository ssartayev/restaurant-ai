const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({ channel: "chromium" });
  try {
    const page = await browser.newPage();
    const base = process.env.BASE_URL || "http://127.0.0.1:8002";
    await page.goto(base + "/recordings");
    await page.getByRole("heading", { name: "Recording review" }).waitFor();
    const file = page.getByLabel("Choose recording");
    await file.setInputFiles({
      name: "invalid.mp4",
      mimeType: "video/mp4",
      buffer: Buffer.from("invalid recording"),
    });
    await page.getByRole("status").filter({ hasText: "Could not open the recording" }).waitFor();
    if (process.env.CCTV_TEST_VIDEO) {
      await file.setInputFiles(process.env.CCTV_TEST_VIDEO);
      await page.locator(".camera .table-marker").first().waitFor({ timeout: 120000 });
      await page.locator(".camera .object-box").first().waitFor();
      await page.locator(".person-label").first().click();
      await page.getByRole("button", {name: "Mark selected person as waiter"}).click();
      await page.getByText("Waiter · staff marked", {exact: true}).first().waitFor();
      await page.getByRole("button", {name: "Clear waiter marks"}).click();
      if (await page.getByText("Waiter · staff marked", {exact: true}).count()) throw new Error("Staff mark did not clear");

      const overlaysContained = await page.locator(".object-box").evaluateAll((boxes) =>
        boxes.every((box) => {
          const camera = box.closest(".camera");
          if (!camera) return false;
          const bounds = camera.getBoundingClientRect(), rect = box.getBoundingClientRect();
          return rect.left >= bounds.left - 1 && rect.top >= bounds.top - 1 &&
            rect.right <= bounds.right + 1 && rect.bottom <= bounds.bottom + 1;
        }));
      if (!overlaysContained) throw new Error("Object overlays escaped the video");

      await page.locator("video").evaluate((video) => video.play());
      await page.waitForFunction(() => document.querySelector("video").currentTime > 0);
      const labels = await page.locator(".camera .table-marker").allTextContents();
      await page.locator("video").evaluate((video) => video.pause());
      const stats = page.locator(".playback-statistics");
      async function seekTo(seconds) {
        await page.locator("video").evaluate((video, at) => { video.currentTime = at; }, seconds);
        await page.waitForFunction((at) => Math.abs(Number(document.querySelector(".playback-statistics").dataset.playbackTime) - at) < .1, seconds);
      }
      await seekTo(0);
      const firstTotals = await stats.locator("tbody tr").allTextContents();
      if ((await stats.locator("tbody tr td:first-of-type").allTextContents()).some(value => value !== "0:00"))
        throw new Error("Future occupancy leaked into start-of-video totals");
      await seekTo(25.5);
      const laterTotals = await stats.locator("tbody tr").allTextContents();
      if (JSON.stringify(firstTotals) === JSON.stringify(laterTotals))
        throw new Error("Statistics did not advance with footage");
      await seekTo(0);
      if (JSON.stringify(firstTotals) !== JSON.stringify(await stats.locator("tbody tr").allTextContents()))
        throw new Error("Statistics failed to rewind");
      await seekTo(25.5);
      if (JSON.stringify(laterTotals) !== JSON.stringify(await stats.locator("tbody tr").allTextContents()))
        throw new Error("Seeking counted occupancy twice");

      await page.getByRole("button", { name: "2D floor plan" }).click();
      if (await page.locator(".object-box").count()) throw new Error("Detection boxes leaked into floor plan");
      const marker = page.locator(".floor-view .table-marker").first();
      const originalPosition = await marker.getAttribute("style");
      const bounds = await marker.boundingBox();
      await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
      await page.mouse.down();
      await page.mouse.move(bounds.x + bounds.width / 2 + 55, bounds.y + bounds.height / 2 + 25);
      await page.mouse.up();
      if (originalPosition === await marker.getAttribute("style")) throw new Error("Floor position did not change");
      await page.getByLabel("Table number").fill("Patio 1");
      const floorLabels = await page.locator(".floor-view .table-marker").allTextContents();
      if (labels.length !== floorLabels.length) throw new Error("Floor and camera table counts differ");
      await page.getByRole("button", { name: "Camera", exact: true }).click();
      await page.locator(".camera .table-marker").first().waitFor();
      await page.locator(".camera .table-marker").filter({ hasText: "Patio 1" }).waitFor();
      if (originalPosition !== await page.locator(".camera .table-marker").first().getAttribute("style")) {
        throw new Error("Dragging changed the camera position");
      }
      await page.getByRole("link", {name: "Live board", exact: true}).click();
      await page.getByRole("heading", {name: "Live board", exact: true}).waitFor();
      await page.locator(".floor-view .table-marker").filter({hasText: "Patio 1"}).waitFor();
      if (await page.locator(".floor-view .table-marker").count() !== labels.length) throw new Error("Board uses a different floor");
      const boardTime = await page.locator(".playback-statistics").getAttribute("data-playback-time");
      await page.getByRole("link", {name: "Recordings", exact: true}).click();
      if (await page.locator(".playback-statistics").getAttribute("data-playback-time") !== boardTime) throw new Error("Navigation reset video time");
      await page.getByRole("button", {name: "Close footage"}).click();
      console.log("Tables shown in both views and Live board:", labels.length);
    }
    const closeFootage = page.getByRole("button", { name: "Close footage" });
    if (await closeFootage.isVisible()) await closeFootage.click();
    await page.getByRole("link", { name: "Live board" }).click();
    await page.getByRole("button", { name: "Start sample restaurant" }).click();
    await page.getByLabel("Dish").fill("Noodles");
    await page.getByRole("button", { name: "Send to kitchen" }).click();
    for (const status of ["preparing", "ready", "served"]) {
      await page.getByRole("button", { name: "Mark " + status, exact: true }).click();
    }
    await page.getByText("No open tickets.").waitFor();
    await page.getByRole("link", { name: "History" }).click();
    await page.getByLabel("Period").selectOption("year");
    await page.locator(".report-metrics").getByText("Kitchen tickets", { exact: true }).waitFor();
    await page.locator(".heatmap").waitFor();
    await page.getByRole("link", { name: "Assistant" }).click();
    await page.getByRole("heading", { name: "Assistant" }).waitFor();
    await page.getByRole("button", { name: "Weekly summary" }).click();
    await page.getByText("Saved report", { exact: true }).waitFor();
    await page.reload();
    await page.getByText("Saved report", { exact: true }).waitFor();
    await page.getByLabel("Question").fill("what about is this website");
    await page.getByRole("button", { name: "Send" }).click();
    await page.getByText(/^Mise helps restaurant staff/).waitFor();
    await page.getByLabel("Question").fill("What is the busiest time and busiest day?");
    await page.getByRole("button", { name: "Send" }).click();
    await page.getByText(/Busiest day of the week:|No party arrivals were recorded in the selected period./).waitFor();
    if (await page.getByLabel("Question").inputValue()) throw new Error("Sent question stayed in the composer");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByLabel("Question").fill("What was our kitchen prep time?");
    if (!(await page.getByRole("button", { name: "Send" }).isEnabled())) throw new Error("Manual composer is disabled");
    if (!(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))) {
      throw new Error("Assistant overflows a mobile viewport");
    }
    console.log("Camera, kitchen, History charts, and persisted Assistant shortcut passed");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
