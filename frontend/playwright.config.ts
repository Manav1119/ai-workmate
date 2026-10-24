import { defineConfig, devices } from "@playwright/test";

// Expects the API (port 8000, seeded database) and the web app (port 3000) to be running.
// Locally: see README "End-to-end tests". CI starts both before running this suite.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
        launchOptions: process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
      },
    },
  ],
});
