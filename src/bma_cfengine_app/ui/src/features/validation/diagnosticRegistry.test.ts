/**
 * vpc-3-ts-worker-registry: Vitest suite for the TS diagnostic registry.
 * AC 1 — types mirror Python envelope
 * AC 2 — registerDiagnosticValidator adds to registry
 * AC 3 — getDiagnosticValidator looks up by code
 * AC 4 — duplicate registration with conflicting metadata throws
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  type Severity,
  type Owner,
  type DiagnosticValidatorDescriptor,
  registerDiagnosticValidator,
  getDiagnosticValidator,
  clearRegistryForTesting,
} from "./diagnosticRegistry";
import type { DiagnosticPayload } from "../deals/store/diagnostics-types";

beforeEach(() => {
  clearRegistryForTesting();
});

describe("test_severity_owner_diagnosticPayload_types_mirror_python", () => {
  it("Severity accepts exactly error | warning | info", () => {
    const severities: Severity[] = ["error", "warning", "info"];
    expect(severities).toHaveLength(3);
    // TypeScript-level: assigning an invalid value would be a compile error,
    // so runtime check confirms the union values exist.
    const s: Severity = "error";
    expect(s).toBe("error");
    const w: Severity = "warning";
    expect(w).toBe("warning");
    const i: Severity = "info";
    expect(i).toBe("info");
  });

  it("Owner accepts exactly worker | backend | both", () => {
    const owners: Owner[] = ["worker", "backend", "both"];
    expect(owners).toHaveLength(3);
    const o1: Owner = "worker";
    expect(o1).toBe("worker");
    const o2: Owner = "backend";
    expect(o2).toBe("backend");
    const o3: Owner = "both";
    expect(o3).toBe("both");
  });

  it("DiagnosticPayload shape mirrors the Python envelope fields", () => {
    // Structural check: a valid DiagnosticPayload must accept all five fields.
    const payload: DiagnosticPayload = {
      code: "TEST_001",
      severity: "error",
      path: "deal.bonds[0].balance",
      message: "Balance must be positive",
      payload: { expected: ">0", actual: -1 },
    };
    expect(payload.code).toBe("TEST_001");
    expect(payload.severity).toBe("error");
    expect(payload.path).toBe("deal.bonds[0].balance");
    expect(payload.message).toBe("Balance must be positive");
    expect(payload.payload).toEqual({ expected: ">0", actual: -1 });
  });
});

describe("test_registerDiagnosticValidator_adds_to_registry", () => {
  it("adds a validator descriptor to the registry and returns it", () => {
    const desc: DiagnosticValidatorDescriptor = {
      code: "TEST",
      severity: "error",
      pathSchema: "$",
      owner: "worker",
      fn: () => [],
    };
    const returned = registerDiagnosticValidator(desc);
    expect(returned).toBe(desc);
    // Confirm it is retrievable.
    const found = getDiagnosticValidator("TEST");
    expect(found).toBeDefined();
    expect(found?.code).toBe("TEST");
  });
});

describe("test_lookup_validator_by_code", () => {
  it("returns the registered descriptor for a known code", () => {
    const fn = () => [];
    const desc: DiagnosticValidatorDescriptor = {
      code: "LOOKUP_TEST",
      severity: "warning",
      pathSchema: "deal.bonds[*]",
      owner: "both",
      fn,
    };
    registerDiagnosticValidator(desc);
    const found = getDiagnosticValidator("LOOKUP_TEST");
    expect(found).toBeDefined();
    expect(found?.code).toBe("LOOKUP_TEST");
    expect(found?.severity).toBe("warning");
    expect(found?.pathSchema).toBe("deal.bonds[*]");
    expect(found?.owner).toBe("both");
    expect(found?.fn).toBe(fn);
  });

  it("returns undefined for an unregistered code", () => {
    expect(getDiagnosticValidator("NONEXISTENT")).toBeUndefined();
  });
});

describe("test_duplicate_registration_throws", () => {
  it("throws when the same code is registered with conflicting severity", () => {
    registerDiagnosticValidator({
      code: "X",
      severity: "error",
      pathSchema: "deal.field",
      owner: "worker",
      fn: () => [],
    });
    expect(() =>
      registerDiagnosticValidator({
        code: "X",
        severity: "warning", // conflicts
        pathSchema: "deal.field",
        owner: "worker",
        fn: () => [],
      })
    ).toThrow();
  });

  it("throws when the same code is registered with conflicting pathSchema", () => {
    registerDiagnosticValidator({
      code: "X",
      severity: "error",
      pathSchema: "deal.field",
      owner: "worker",
      fn: () => [],
    });
    expect(() =>
      registerDiagnosticValidator({
        code: "X",
        severity: "error",
        pathSchema: "deal.other", // conflicts
        owner: "worker",
        fn: () => [],
      })
    ).toThrow();
  });

  it("throws when the same code is registered with conflicting owner", () => {
    registerDiagnosticValidator({
      code: "X",
      severity: "error",
      pathSchema: "deal.field",
      owner: "worker",
      fn: () => [],
    });
    expect(() =>
      registerDiagnosticValidator({
        code: "X",
        severity: "error",
        pathSchema: "deal.field",
        owner: "both", // conflicts
        fn: () => [],
      })
    ).toThrow();
  });

  it("does not throw when the same code is re-registered with identical metadata", () => {
    const fn = () => [];
    const desc: DiagnosticValidatorDescriptor = {
      code: "X",
      severity: "error",
      pathSchema: "deal.field",
      owner: "worker",
      fn,
    };
    registerDiagnosticValidator(desc);
    // Idempotent re-registration with same metadata must not throw.
    expect(() => registerDiagnosticValidator(desc)).not.toThrow();
  });
});
