// Validate the frozen fixtures against the generated JSON Schemas, in TypeScript's
// toolchain rather than Python's.
//
// docs/ARCHITECTURE.md section 7 requires the same fixtures to validate in both
// languages. This is the TypeScript half: an independent 2020-12 implementation
// (Ajv) reading the same committed schemas and the same committed fixtures.
//
// Contract-only. No React, no bundler, no application code.

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const schemaDir = join(here, "..", "schemas");
const validDir = join(here, "..", "fixtures", "valid");
const invalidDir = join(here, "..", "fixtures", "invalid");

// Cases JSON Schema cannot express. Graph edge integrity and cross-artifact
// traceability are structural joins, and the measurement/state coupling is a
// model invariant. Recorded rather than pretended: this list is asserted, so it
// cannot quietly grow.
const NOT_SCHEMA_ENFORCEABLE = new Set([
  "dangling-graph-edge",
  "recommendation-missing-evidence",
  "measurement-without-verified-state",
]);

const read = (path) => JSON.parse(readFileSync(path, "utf8"));

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);

const validators = new Map();
for (const file of readdirSync(schemaDir).filter((n) => n.endsWith(".schema.json")).sort()) {
  const artifactType = file.replace(/\.schema\.json$/, "");
  validators.set(artifactType, ajv.compile(read(join(schemaDir, file))));
}
if (validators.size === 0) {
  console.error("no schemas found; run the Python generator first");
  process.exit(1);
}

const problems = [];
const validatorFor = (document, label) => {
  const artifactType = document.artifact_type;
  if (typeof artifactType !== "string") {
    problems.push(`${label}: artifact_type is missing or not a string`);
    return null;
  }
  const validate = validators.get(artifactType);
  if (validate === undefined) {
    problems.push(`${label}: no generated schema for artifact_type ${artifactType}`);
    return null;
  }
  return validate;
};

// Every valid fixture must validate.
const validFiles = readdirSync(validDir).filter((n) => n.endsWith(".json")).sort();
if (validFiles.length !== validators.size) {
  problems.push(
    `expected one valid fixture per schema: ${validFiles.length} fixtures, ${validators.size} schemas`,
  );
}
let validated = 0;
for (const file of validFiles) {
  const label = `valid/${file}`;
  const document = read(join(validDir, file));
  const expectedType = file.replace(/\.json$/, "");
  if (document.artifact_type !== expectedType) {
    problems.push(`${label}: artifact_type ${document.artifact_type} does not match its filename`);
  }
  const validate = validatorFor(document, label);
  if (validate === null) continue;
  if (validate(document)) {
    validated += 1;
  } else {
    const messages = (validate.errors ?? [])
      .map((e) => `${e.instancePath || "/"} ${e.message}`)
      .join("; ");
    problems.push(`${label}: should validate but did not -> ${messages}`);
  }
}

// Every schema-enforceable invalid fixture must be rejected, and every case on
// the not-enforceable list must genuinely pass schema validation.
const invalidFiles = readdirSync(invalidDir).filter((n) => n.endsWith(".json")).sort();
let rejected = 0;
const unexpectedlyAccepted = [];
for (const file of invalidFiles) {
  const name = file.replace(/\.json$/, "");
  const label = `invalid/${file}`;
  const document = read(join(invalidDir, file));
  const validate = validatorFor(document, label);
  if (validate === null) continue;
  const passes = validate(document);
  if (NOT_SCHEMA_ENFORCEABLE.has(name)) {
    if (!passes) {
      problems.push(
        `${label}: listed as not schema-enforceable but JSON Schema rejected it; ` +
          "remove it from NOT_SCHEMA_ENFORCEABLE",
      );
    }
    continue;
  }
  if (passes) {
    unexpectedlyAccepted.push(name);
    problems.push(`${label}: should have been rejected by JSON Schema but validated`);
  } else {
    rejected += 1;
  }
}

for (const name of NOT_SCHEMA_ENFORCEABLE) {
  if (!invalidFiles.includes(`${name}.json`)) {
    problems.push(`NOT_SCHEMA_ENFORCEABLE names a missing fixture: ${name}`);
  }
}

for (const problem of problems) console.error(`FAIL ${problem}`);
if (problems.length > 0) {
  if (unexpectedlyAccepted.length > 0) {
    console.error(
      "Python and TypeScript disagree on: " + unexpectedlyAccepted.join(", ") +
        ". A rule Python enforces must be expressible in the generated schema.",
    );
  }
  process.exit(1);
}
console.log(
  `${validated} valid fixtures validated, ${rejected} invalid fixtures rejected, ` +
    `${NOT_SCHEMA_ENFORCEABLE.size} model-only cases recorded (Ajv 2020)`,
);
