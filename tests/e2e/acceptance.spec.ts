import { expect, test } from "@playwright/test";

const SCRIPTED_TURNS = [
  "Review this fictional project and identify the strongest expansion opportunity.",
  "Focus on the operational pain behind that opportunity and strengthen the supporting signals.",
  "Refine the value proposition, list the missing evidence, and give me the next customer action.",
] as const;

test("rapid three-turn acceptance preserves FIFO versions and one canonical card", async ({
  page,
}) => {
  const nonLocalRequests: string[] = [];
  page.on("request", (request) => {
    const host = new URL(request.url()).hostname;
    if (host !== "127.0.0.1" && host !== "localhost") {
      nonLocalRequests.push(request.url());
    }
  });

  await page.goto("/");
  const input = page.getByLabel("Send the same analysis command path");
  const send = page.getByRole("button", { name: "Send turn" });

  for (const transcript of SCRIPTED_TURNS) {
    await input.fill(transcript);
    await send.click();
  }

  const turnItems = page.locator(".turn-item");
  await expect(turnItems).toHaveCount(3);
  await expect(
    turnItems.filter({ hasText: SCRIPTED_TURNS[1] }).locator(".turn-status"),
  ).toHaveText("Queued · 1 in queue", { timeout: 500 });
  await expect(
    turnItems.filter({ hasText: SCRIPTED_TURNS[2] }).locator(".turn-status"),
  ).toHaveText("Queued · 2 in queue", { timeout: 500 });

  await expect(page.locator(".document-panel .version-pill")).toHaveText(
    "Version 3",
  );
  await expect(page.locator(".document-panel")).toHaveCount(1);
  await expect(turnItems.locator(".turn-status")).toHaveText([
    "Complete",
    "Complete",
    "Complete",
  ]);

  await page.getByText("Version history").click();
  const historyItems = page.locator(".version-history > ol > li");
  await expect(historyItems).toHaveCount(3);
  await expect(historyItems.locator(".version-row strong")).toHaveText([
    "Version 3 · current",
    "Version 2",
    "Version 1",
  ]);
  await expect(
    page.getByText("Create the initial evidence-bounded opportunity."),
  ).toBeVisible();
  await expect(
    page.getByText("Strengthen the operational context and supporting signals."),
  ).toBeVisible();
  await expect(
    page.getByText("Refine validation value, evidence gaps, and next action."),
  ).toBeVisible();

  const browserStorage = await page.evaluate(async () => ({
    local: localStorage.length,
    session: sessionStorage.length,
    indexedDatabases:
      typeof indexedDB.databases === "function"
        ? (await indexedDB.databases()).length
        : 0,
    caches: "caches" in window ? (await caches.keys()).length : 0,
  }));
  expect(browserStorage).toEqual({
    local: 0,
    session: 0,
    indexedDatabases: 0,
    caches: 0,
  });
  expect(nonLocalRequests).toEqual([]);
});

test("voice-disabled acceptance labels local behavior without claiming live audio", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("Voice Unavailable")).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Start voice.*not configured/i }),
  ).toBeDisabled();
  await expect(page.getByText("Public preview voice transport")).toBeVisible();
  await expect(
    page.getByText("Audio is never stored by this application"),
  ).toBeVisible();
});
