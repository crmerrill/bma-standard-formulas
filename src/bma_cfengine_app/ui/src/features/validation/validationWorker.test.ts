/**
 * ve-1-worker-host: Vitest suite for the validation Web Worker logic.
 * AC 1 — a TS Web Worker hosts the validation registry execution.
 * AC 2 — the worker receives the deal payload and executes all registered validators.
 * AC 4 — the worker returns DiagnosticPayload[] back to the main thread.
 *
 * NOTE: Vitest/jsdom cannot instantiate a real Web Worker, so we test the
 * exported `runValidators` helper that the worker's onmessage handler delegates
 * to.  The onmessage wiring (AC 1) is verified structurally by the presence of
 * the self.onmessage assignment in validationWorker.ts.
 */

import { describe, it, expect } from "vitest";

// T1: this import will FAIL until validationWorker.ts is created (I commit).
import { runValidators } from "./validationWorker";

// structuralValidators.ts is imported as a side-effect inside validationWorker.ts,
// so BOND_NAME_EMPTY is already registered by the time runValidators is called.

describe("test_worker_executes_validators_and_returns_payloads", () => {
  it("returns BOND_NAME_EMPTY for a bond with an empty name (AC 2, 4)", () => {
    const deal = {
      bonds: [{ name: "" }],
    };
    const results = runValidators(deal);
    expect(results.some((d) => d.code === "BOND_NAME_EMPTY")).toBe(true);
  });

  it("emits diagnostic with correct path and severity for empty bond name", () => {
    const deal = {
      bonds: [{ name: "" }, { name: "ValidBond" }],
    };
    const results = runValidators(deal);
    const diag = results.find((d) => d.code === "BOND_NAME_EMPTY");
    expect(diag).toBeDefined();
    expect(diag!.severity).toBe("error");
    expect(diag!.path).toBe("deal.bonds[0].name");
  });

  it("returns no BOND_NAME_EMPTY diagnostics when all bonds have names (AC 2, 4)", () => {
    const deal = {
      bonds: [{ name: "TrancheA" }, { name: "TrancheB" }],
    };
    const results = runValidators(deal);
    expect(results.filter((d) => d.code === "BOND_NAME_EMPTY")).toHaveLength(0);
  });

  it("returns an array (DiagnosticPayload[]) for a deal with no bonds (AC 4)", () => {
    const deal = { bonds: [] };
    const results = runValidators(deal);
    expect(Array.isArray(results)).toBe(true);
    expect(results).toHaveLength(0);
  });
});
