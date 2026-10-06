import { defineConfig, devices } from "@playwright/test";

// docs/INTERFACE_DESIGN.md section 15's browser-screenshot matrix: light and
// dark at 1440/1024/390 px. One project per (viewport, theme) pair so a
// baseline mismatch names exactly which combination regressed.
const VIEWPORTS: Record<string, { width: number; height: number }> = {
  "1440": { width: 1440, height: 900 },
  "1024": { width: 1024, height: 900 },
  "390": { width: 390, height: 844 },
};

export default defineConfig({
  testDir: "./tests/visual",
  snapshotPathTemplate: "{testDir}/__screenshots__/{projectName}/{arg}{ext}",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
  },
  webServer: {
    // Vite's default preview host resolves to the IPv6 loopback, which the
    // IPv4 probe above cannot reach; binding explicitly keeps both sides on
    // the same address.
    command: "npm run build && npm run preview -- --port 4173 --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: Object.entries(VIEWPORTS).flatMap(([name, viewport]) => [
    {
      name: `${name}-light`,
      use: { ...devices["Desktop Chrome"], viewport, colorScheme: "light" as const },
    },
    {
      name: `${name}-dark`,
      use: { ...devices["Desktop Chrome"], viewport, colorScheme: "dark" as const },
    },
  ]),
});
