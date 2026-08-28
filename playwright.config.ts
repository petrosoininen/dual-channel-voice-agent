import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:5184",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        "python -m uvicorn tests.e2e.acceptance_app:app --host 127.0.0.1 --port 8110",
      url: "http://127.0.0.1:8110/api/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npx vite --config vite.e2e.config.ts",
      url: "http://127.0.0.1:5184",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "installed-chrome",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
    {
      name: "installed-edge",
      use: { ...devices["Desktop Edge"], channel: "msedge" },
    },
  ],
});
