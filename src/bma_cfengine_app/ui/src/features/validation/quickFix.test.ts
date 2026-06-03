/**
 * ve-5 QuickFix protocol — TS-side tests.
 *
 * AC 2: at least one worker validator emits a populated QuickFix field.
 * AC 3: store exposes getErrorCount(sessionId) selector.
 */

import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { DiagnosticPayload, QuickFix } from "../deals/store/diagnostics-types";
import { useDealStore } from "../deals/store/useDealStore";
import { getErrorCount } from "../deals/store/selectors";
import { iterDiagnosticValidators } from "./diagnosticRegistry";
import "./structuralValidators";

describe("ve-5 QuickFix protocol (TS)", () => {
  beforeEach(() => {
    useDealStore.setState(useDealStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("test_worker_validator_emits_quick_fix", () => {
    // AC 2: at least one validator emits a populated QuickFix on a relevant fixture.
    // BOND_NAME_DUPLICATE is the chosen exemplar — duplicate bonds A1/A1.
    const dealWithDuplicates: unknown = {
      bonds: [
        { name: "Tranche_A", kind: "CASH_PAY" },
        { name: "Tranche_A", kind: "CASH_PAY" },
      ],
      accounts: [],
      fees: [],
      triggers: [],
      waterfall_rules: [],
      collateral_groups: [],
      deal_knobs: {},
    };

    let emittedFix: QuickFix | undefined;
    let emittedCode: string | undefined;

    for (const validator of iterDiagnosticValidators()) {
      if (validator.code !== "BOND_NAME_DUPLICATE") continue;
      const results = validator.fn(dealWithDuplicates);
      for (const r of results) {
        if (r.fix) {
          emittedFix = r.fix;
          emittedCode = r.code;
          break;
        }
      }
    }

    expect(emittedCode).toBe("BOND_NAME_DUPLICATE");
    expect(emittedFix).toBeDefined();
    expect(typeof emittedFix?.action_id).toBe("string");
    expect(emittedFix?.action_id.length).toBeGreaterThan(0);
    expect(emittedFix?.params).toBeDefined();
    expect(typeof emittedFix?.params).toBe("object");
  });

  test("test_diagnostic_payload_with_no_fix_remains_valid_type", () => {
    // AC 1: QuickFix is additive optional. Existing 5-field payloads still
    // satisfy the DiagnosticPayload type without a fix.
    const payload: DiagnosticPayload = {
      code: "BOND_NAME_EMPTY",
      severity: "error",
      path: "deal.bonds[0].name",
      message: "Bond name must not be empty.",
      payload: {},
    };
    expect(payload.fix).toBeUndefined();
  });
});

describe("ve-5 getErrorCount selector (TS)", () => {
  beforeEach(() => {
    useDealStore.setState(useDealStore.getInitialState(), true);
  });

  test("test_getErrorCount_returns_error_severity_sum", () => {
    // AC 3: getErrorCount(sessionId) returns the count of severity='error' diagnostics.
    const sid = "main";
    useDealStore.getState().setDiagnostics(sid, [
      {
        code: "A",
        severity: "error",
        path: "$.a",
        message: "a",
        payload: {},
      },
      {
        code: "B",
        severity: "warning",
        path: "$.b",
        message: "b",
        payload: {},
      },
      {
        code: "C",
        severity: "error",
        path: "$.c",
        message: "c",
        payload: {},
      },
      {
        code: "D",
        severity: "info",
        path: "$.d",
        message: "d",
        payload: {},
      },
    ]);

    expect(getErrorCount(sid)).toBe(2);
  });

  test("test_getErrorCount_returns_zero_when_no_errors", () => {
    const sid = "main";
    useDealStore.getState().setDiagnostics(sid, [
      {
        code: "B",
        severity: "warning",
        path: "$.b",
        message: "b",
        payload: {},
      },
      {
        code: "D",
        severity: "info",
        path: "$.d",
        message: "d",
        payload: {},
      },
    ]);

    expect(getErrorCount(sid)).toBe(0);
  });

  test("test_getErrorCount_returns_zero_for_unknown_session", () => {
    // Defensive: unknown session returns 0, not undefined or NaN.
    expect(getErrorCount("nonexistent_session_id")).toBe(0);
  });
});
