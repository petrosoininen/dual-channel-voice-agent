import { expect, test } from "@playwright/test";

test("typed fallback updates one canonical document in voice-disabled mode", async ({
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
  await expect(
    page.getByRole("heading", { name: "Speak briefly. Build the complete case." }),
  ).toBeVisible();
  await expect(page.getByText("deterministic")).toBeVisible();
  await expect(page.getByText("off")).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Start voice.*not configured/i }),
  ).toBeDisabled();
  await expect(page.getByText("Voice Unavailable")).toBeVisible();

  const prompt =
    "Review this fictional project and identify the strongest expansion opportunity.";
  await page.getByLabel("Send the same analysis command path").fill(prompt);
  await page.getByRole("button", { name: "Send turn" }).click();

  await expect(page.getByText(prompt)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Opportunity assessment" }),
  ).toBeVisible();
  await expect(page.locator(".document-panel")).toHaveCount(1);
  await expect(page.getByText("Version 1", { exact: true })).toBeVisible();
  await expect(page.locator(".analysis-completion")).toContainText(
    "Updated the working document to version 1.",
  );
  await expect(page.locator(".analysis-completion")).toContainText(
    "canonical document remains authoritative",
  );
  expect(nonLocalRequests).toEqual([]);
});

test("mode is visible and immutable while typed input remains keyboard operable", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("server locked")).toBeVisible();
  await page
    .getByLabel("Send the same analysis command path")
    .fill("Synthetic keyboard request");
  await expect(
    page.getByLabel("Send the same analysis command path"),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Send turn" })).toBeFocused();
});

test("one document retains versions and revert creates a new version", async ({
  page,
}) => {
  await page.goto("/");
  const input = page.getByLabel("Send the same analysis command path");
  const send = page.getByRole("button", { name: "Send turn" });
  const turns = [
    "Review this fictional project and identify the strongest expansion opportunity.",
    "Focus on the operational pain behind that opportunity and strengthen the supporting signals.",
    "Refine the value proposition, list the missing evidence, and give me the next customer action.",
  ];
  for (const [index, prompt] of turns.entries()) {
    await input.fill(prompt);
    await send.click();
    await expect(
      page.locator(".document-panel .version-pill"),
    ).toHaveText(`Version ${index + 1}`);
  }

  await page.getByText("Version history").click();
  const versionOne = page
    .locator(".version-history li")
    .filter({ hasText: "Version 1" });
  await versionOne
    .getByRole("button", { name: "Restore as new version" })
    .click();
  await expect(page.locator(".document-panel .version-pill")).toHaveText(
    "Version 4",
  );
  await expect(page.getByText("Restored from version 1.")).toBeVisible();
  await expect(page.locator(".document-panel")).toHaveCount(1);
});
