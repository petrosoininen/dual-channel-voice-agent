import { readFile } from "node:fs/promises";
import { chromium } from "@playwright/test";

if (process.env.DCR_RUN_LIVE_BROWSER !== "1") {
  throw new Error("Live browser smoke requires explicit DCR_RUN_LIVE_BROWSER=1.");
}

const baseUrl = process.env.DCR_LIVE_BASE_URL ?? "";
const parsed = new URL(baseUrl);
if (
  parsed.protocol !== "http:" ||
  !["127.0.0.1", "localhost"].includes(parsed.hostname)
) {
  throw new Error("Live browser smoke accepts only a loopback URL.");
}

const turns = JSON.parse(
  await readFile(new URL("../fixtures/scripted-turns.json", import.meta.url), "utf8"),
);
const browser = await chromium.launch({
  headless: true,
  args: [
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
  ],
});

let voiceSessionConnected = false;
try {
  const context = await browser.newContext({
    permissions: ["microphone"],
  });
  const page = await context.newPage();
  await page.goto(baseUrl);
  await page.getByText("Workspace connected").waitFor({ timeout: 30_000 });

  await page.getByRole("button", { name: "Start voice" }).click();
  await page.getByText("Voice Listening").waitFor({ timeout: 60_000 });
  voiceSessionConnected = true;
  await page.getByRole("button", { name: "Stop voice" }).click();

  const input = page.getByLabel("Send the same analysis command path");
  const send = page.getByRole("button", { name: "Send turn" });
  for (const [index, turn] of turns.entries()) {
    await input.fill(turn.transcript);
    await send.click();
    await page
      .locator(".document-panel .version-pill")
      .getByText(`Version ${index + 1}`)
      .waitFor({ timeout: 180_000 });
  }
  const completedTurns = await page.locator(".turn-status.status-completed").count();
  if (completedTurns !== 3) {
    throw new Error("The live browser smoke did not complete exactly three turns.");
  }
  console.log(
    JSON.stringify({
      browserThreeTurn: true,
      completedTurns,
      voiceSessionConnected,
    }),
  );
  await context.close();
} finally {
  await browser.close();
}
