import { expect, test } from "@playwright/test";

// One baseline per (viewport, theme) project in playwright.config.ts.
// docs/INTERFACE_DESIGN.md section 15: "Screenshot changes require explicit
// review; snapshots are not blindly updated."
test("fixture gallery", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "pgproof fixture gallery" })).toBeVisible();
  await expect(page).toHaveScreenshot("gallery.png", { fullPage: true });
});
