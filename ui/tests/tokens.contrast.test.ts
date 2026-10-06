import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { contrastRatio, parseTokenBlock } from "./contrast";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "../src/styles/tokens.css"), "utf-8");

const LIGHT = parseTokenBlock(css, /^:root\s*\{([^}]*)\}/m);
const DARK = parseTokenBlock(css, /:root\[data-theme="dark"\]\s*\{([^}]*)\}/);

// docs/INTERFACE_DESIGN.md section 10: WCAG 2.2 AA, 4.5:1 for normal text.
const AA_NORMAL_TEXT = 4.5;

const TEXT_ON_SURFACE_PAIRS: Array<[string, string]> = [
  ["text-primary", "surface-page"],
  ["text-primary", "surface-base"],
  ["text-primary", "surface-raised"],
  ["text-secondary", "surface-page"],
  ["accent-primary", "surface-page"],
  ["semantic-success", "surface-page"],
  ["semantic-warning", "surface-page"],
  ["semantic-danger", "surface-page"],
  ["semantic-info", "surface-page"],
];

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
])("%s theme tokens", (_name, tokens) => {
  it.each(TEXT_ON_SURFACE_PAIRS)("%s on %s meets AA for normal text", (text, surface) => {
    const ratio = contrastRatio(tokens[text], tokens[surface]);
    expect(ratio).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
  });

  it("code.text on code.surface meets AA for normal text", () => {
    const ratio = contrastRatio(tokens["code-text"], tokens["code-surface"]);
    expect(ratio).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
  });
});
