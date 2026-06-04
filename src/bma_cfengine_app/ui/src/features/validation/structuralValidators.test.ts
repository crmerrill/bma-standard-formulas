/**
 * ve-2-worker-validator-coverage: Vitest tests for the 6 new TS structural validators.
 *
 * Each test loads a parity fixture, runs the relevant TS validator function, and
 * asserts the output matches the expected (code, path) tuples.
 */

import { describe, it, expect } from "vitest";
import { iterDiagnosticValidators } from "./diagnosticRegistry";
import type { DiagnosticPayload } from "../deals/store/diagnostics-types";

// Import validators to trigger registration (runs once at module load).
import "./structuralValidators";

import fs from "node:fs";
import path from "node:path";

const FIXTURES_DIR = path.resolve(
  __dirname,
  "../../../../../../tests/fixtures/diagnostic_parity",
);

function loadFixture(name: string): {
  deal: unknown;
  expected_diagnostics: { code: string; path: string }[];
} {
  const raw = fs.readFileSync(path.join(FIXTURES_DIR, `${name}.json`), "utf-8");
  return JSON.parse(raw);
}

function runAllValidators(deal: unknown): DiagnosticPayload[] {
  const results: DiagnosticPayload[] = [];
  for (const desc of iterDiagnosticValidators()) {
    if (desc.owner === "backend") continue;
    results.push(...desc.fn(deal));
  }
  return results;
}

describe("ve-2: worker validators catch specific errors", () => {
  it("BOND_NAME_DUPLICATE: detects duplicate bond names", () => {
    const fixture = loadFixture("bond_name_duplicate");
    const results = runAllValidators(fixture.deal);
    const actual = results
      .filter((r) => r.code === "BOND_NAME_DUPLICATE")
      .map((r) => ({ code: r.code, path: r.path }));
    expect(actual).toEqual(fixture.expected_diagnostics);
  });

  it("REFERENCE_BROKEN: detects broken from_sources and to_targets references", () => {
    const fixture = loadFixture("reference_broken");
    const results = runAllValidators(fixture.deal);
    const actual = results
      .filter((r) => r.code === "REFERENCE_BROKEN")
      .map((r) => ({ code: r.code, path: r.path }));
    expect(actual).toEqual(
      expect.arrayContaining(fixture.expected_diagnostics),
    );
    expect(actual.length).toBe(fixture.expected_diagnostics.length);
  });

  it("MULTI_TARGET_WEIGHT_SUM_INVALID: detects target_weights not summing to 1.0", () => {
    const fixture = loadFixture("multi_target_weight_sum_invalid");
    const results = runAllValidators(fixture.deal);
    const actual = results
      .filter((r) => r.code === "MULTI_TARGET_WEIGHT_SUM_INVALID")
      .map((r) => ({ code: r.code, path: r.path }));
    expect(actual).toEqual(fixture.expected_diagnostics);
  });

  it("KIND_SCHEDULE_SOURCE_INCONSISTENT: detects PAC/TAC missing schedule or non-PAC/TAC having schedule", () => {
    const fixture = loadFixture("kind_schedule_source_inconsistent");
    const results = runAllValidators(fixture.deal);
    const actual = results
      .filter((r) => r.code === "KIND_SCHEDULE_SOURCE_INCONSISTENT")
      .map((r) => ({ code: r.code, path: r.path }));
    expect(actual).toEqual(
      expect.arrayContaining(fixture.expected_diagnostics),
    );
    expect(actual.length).toBe(fixture.expected_diagnostics.length);
  });

  it("NLA_SUBORDINATION_INCONSISTENT: detects NLA and subordination mismatch", () => {
    const fixture = loadFixture("nla_subordination_inconsistent");
    const results = runAllValidators(fixture.deal);
    const actual = results
      .filter((r) => r.code === "NLA_SUBORDINATION_INCONSISTENT")
      .map((r) => ({ code: r.code, path: r.path }));
    expect(actual).toEqual(
      expect.arrayContaining(fixture.expected_diagnostics),
    );
    expect(actual.length).toBe(fixture.expected_diagnostics.length);
  });

  it("MULTI_GROUP_ROUTING_INVALID: detects group-prefixed sources not in collateral_groups", () => {
    const fixture = loadFixture("multi_group_routing_invalid");
    const results = runAllValidators(fixture.deal);
    const actual = results
      .filter((r) => r.code === "MULTI_GROUP_ROUTING_INVALID")
      .map((r) => ({ code: r.code, path: r.path }));
    const expected = fixture.expected_diagnostics.filter(
      (d) => d.code === "MULTI_GROUP_ROUTING_INVALID",
    );
    expect(actual).toEqual(expected);
  });
});
