// WCAG 2.2 relative-luminance contrast ratio, used to check
// docs/INTERFACE_DESIGN.md section 13's tokens against section 10's AA
// target (4.5:1 normal text) directly against the real tokens.css values,
// not a hand-copied duplicate of them.

function srgbToLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex: string): number {
  const normalized = hex.replace("#", "");
  const r = parseInt(normalized.slice(0, 2), 16);
  const g = parseInt(normalized.slice(2, 4), 16);
  const b = parseInt(normalized.slice(4, 6), 16);
  return (
    0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b)
  );
}

export function contrastRatio(foreground: string, background: string): number {
  const l1 = relativeLuminance(foreground);
  const l2 = relativeLuminance(background);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

export function parseTokenBlock(css: string, blockPattern: RegExp): Record<string, string> {
  const match = blockPattern.exec(css);
  if (match === null) {
    throw new Error(`no block matched ${blockPattern}`);
  }
  const body = match[1];
  const tokens: Record<string, string> = {};
  for (const line of body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6});/g)) {
    tokens[line[1]] = line[2];
  }
  return tokens;
}
