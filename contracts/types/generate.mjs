// Generate TypeScript types from the committed JSON Schemas.
//
// Output must be byte-stable so --check can act as a drift gate. The generator
// version is pinned exactly in package.json for the same reason: an upgrade that
// changes output surfaces as reviewable drift rather than a silent change.

import { readFileSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const schemaDir = join(here, "..", "schemas");
const outDir = join(here, "generated");

const BANNER = [
  "/* eslint-disable */",
  "/**",
  " * Generated from contracts/schemas. Do not edit by hand.",
  " * Regenerate with: npm run generate",
  " */",
].join("\n");

// The root type name comes from the schema title, which the Python generator
// writes as an identifier for exactly this reason.
function rootTypeFor(file) {
  const schema = JSON.parse(readFileSync(join(schemaDir, file), "utf8"));
  if (typeof schema.title !== "string" || !/^[A-Z][A-Za-z0-9]*$/.test(schema.title)) {
    throw new Error(`${file}: schema title must be an identifier, got ${schema.title}`);
  }
  return schema.title;
}

async function render(file) {
  const schema = JSON.parse(readFileSync(join(schemaDir, file), "utf8"));
  const body = await compile(schema, rootTypeFor(file), {
    additionalProperties: false,
    bannerComment: "",
    declareExternallyReferenced: true,
    enableConstEnums: false,
    format: true,
    strictIndexSignatures: false,
    unknownAny: true,
  });
  return `${BANNER}\n\n${body.trimEnd()}\n`;
}

const files = readdirSync(schemaDir)
  .filter((name) => name.endsWith(".schema.json"))
  .sort();

if (files.length === 0) {
  console.error("no schemas found; run the Python generator first");
  process.exit(1);
}

const mode = process.argv.includes("--check")
  ? "check"
  : process.argv.includes("--write")
    ? "write"
    : null;
if (mode === null) {
  console.error("usage: node generate.mjs --write | --check");
  process.exit(2);
}

const rendered = new Map();
for (const file of files) {
  rendered.set(file.replace(/\.schema\.json$/, ".ts"), await render(file));
}

// Only the root artifact type is re-exported per module. A wildcard barrel would
// collide on shared property-derived names such as DataType and BoundaryNote.
const indexLines = [BANNER, ""];
for (const file of files) {
  const module = file.replace(/\.schema\.json$/, "");
  indexLines.push(`export type { ${rootTypeFor(file)} } from "./${module}.js";`);
}
rendered.set("index.ts", `${indexLines.join("\n")}\n`);

if (mode === "write") {
  mkdirSync(outDir, { recursive: true });
  for (const [name, text] of [...rendered.entries()].sort()) {
    writeFileSync(join(outDir, name), text, "utf8");
  }
  console.log(`wrote ${rendered.size} TypeScript modules to generated/`);
  process.exit(0);
}

const problems = [];
const existing = new Set(
  readdirSync(outDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".ts"))
    .map((entry) => entry.name),
);
for (const name of [...existing].sort()) {
  if (!rendered.has(name)) problems.push(`${name}: present but no longer generated`);
}
for (const [name, text] of [...rendered.entries()].sort()) {
  const path = join(outDir, name);
  let actual = null;
  try {
    actual = readFileSync(path, "utf8");
  } catch {
    problems.push(`${name}: missing; run npm run generate`);
    continue;
  }
  if (actual !== text) problems.push(`${name}: differs from the generated type`);
}
for (const problem of problems) console.error(`FAIL ${problem}`);
if (problems.length > 0) {
  console.error("TypeScript type drift detected; run: npm run generate");
  process.exit(1);
}
console.log(`${rendered.size} TypeScript modules match the schemas`);
