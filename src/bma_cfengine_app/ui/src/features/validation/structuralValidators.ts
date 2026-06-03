/**
 * Structural validators for deal payloads — owner='both' (Python + TS parity).
 *
 * These validators mirror the Python implementations in
 * src/bma_standard_formulas/diagnostics/structural_validators.py and must
 * produce identical (code, path) output for the same input deal payload.
 *
 * Adding a validator here requires:
 *   1. A matching @diagnostic_code decorator in the Python structural_validators module.
 *   2. A new row in docs/architecture/diagnostic_catalog.md.
 *   3. Verifying python -m bma_standard_formulas.diagnostics.check exits 0.
 */

import { registerDiagnosticValidator } from "./diagnosticRegistry";
import type { DiagnosticPayload } from "../deals/store/diagnostics-types";

registerDiagnosticValidator({
  code: "BOND_NAME_EMPTY",
  severity: "error",
  pathSchema: "deal.bonds[*].name",
  owner: "both",
  fn(deal: unknown): DiagnosticPayload[] {
    const d = deal as Record<string, unknown>;
    const bonds = Array.isArray(d.bonds) ? d.bonds : [];
    const results: DiagnosticPayload[] = [];
    for (let i = 0; i < bonds.length; i++) {
      const bond = bonds[i] as Record<string, unknown>;
      const name = typeof bond.name === "string" ? bond.name : "";
      if (!name.trim()) {
        results.push({
          code: "BOND_NAME_EMPTY",
          severity: "error",
          path: `deal.bonds[${i}].name`,
          message: `Bond at index ${i} has an empty or missing name.`,
          payload: { index: i },
        });
      }
    }
    return results;
  },
});
