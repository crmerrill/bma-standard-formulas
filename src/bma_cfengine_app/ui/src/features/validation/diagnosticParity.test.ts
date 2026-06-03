/**
 * vpc-5-parity-fixture-set: Vitest parity runner for JSON diagnostic fixtures.
 *
 * For each fixture in tests/fixtures/diagnostic_parity/*.json the runner:
 *   1. Loads the deal payload from fixture.deal.
 *   2. Runs every registered TS validator with owner in {worker, both}.
 *   3. Asserts the resulting (code, path) tuples exactly match
 *      fixture.expected_diagnostics.
 *
 * AC 5: Validators with owner='backend' are excluded — only worker/both codes
 * are subject to cross-stack parity checks.
 *
 * To add coverage for a new validator module, import it below the
 * "Validator module registration" comment so its registerDiagnosticValidator
 * calls execute before the tests run.
 */

import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";

// ---------------------------------------------------------------------------
// Validator module registration
// ---------------------------------------------------------------------------
// Importing a validator module causes its top-level registerDiagnosticValidator
// calls to execute, populating the registry before any test runs.
// Add new validator module imports here as they are introduced.
// At T1 (test-only commit) this import fails intentionally — the file does
// not yet exist, causing the test suite to be RED until the implementation
// commit adds structuralValidators.ts.
import "./structuralValidators";

import { iterDiagnosticValidators } from "./diagnosticRegistry";

// ---------------------------------------------------------------------------
// Fixture loading
// ---------------------------------------------------------------------------

const __dirname = dirname(fileURLToPath(import.meta.url));

// Resolve repo-root-relative path from the test file location.
// test file:  src/bma_cfengine_app/ui/src/features/validation/
// repo root:  six levels up (validation → features → src(ui) → ui → bma_cfengine_app → src → root)
const FIXTURES_DIR = resolve(
  __dirname,
  "../../../../../../tests/fixtures/diagnostic_parity",
);

type FixtureExpected = { code: string; path: string };
type Fixture = {
  name: string;
  description: string;
  deal: unknown;
  expected_diagnostics: FixtureExpected[];
};

function loadFixtures(): Fixture[] {
  try {
    return readdirSync(FIXTURES_DIR)
      .filter((f) => f.endsWith(".json"))
      .sort()
      .map((f) => JSON.parse(readFileSync(join(FIXTURES_DIR, f), "utf-8")) as Fixture);
  } catch {
    return [];
  }
}

const fixtures = loadFixtures();

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("diagnostic parity fixtures", () => {
  it("fixture directory contains at least one fixture file", () => {
    expect(fixtures.length).toBeGreaterThan(0);
  });

  for (const fixture of fixtures) {
    it(`parity: ${fixture.name}`, () => {
      const expected = new Set(
        fixture.expected_diagnostics.map((d) => `${d.code}::${d.path}`),
      );

      const actual = new Set<string>();
      for (const desc of iterDiagnosticValidators()) {
        // AC 5: skip backend-only validators
        if (desc.owner !== "worker" && desc.owner !== "both") continue;
        for (const result of desc.fn(fixture.deal)) {
          actual.add(`${result.code}::${result.path}`);
        }
      }

      expect(actual).toEqual(expected);
    });
  }
});
