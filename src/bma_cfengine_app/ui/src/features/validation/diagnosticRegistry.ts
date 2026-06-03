/**
 * vpc-3-ts-worker-registry: TS worker-side diagnostic validator registry.
 *
 * Mirrors the Python @diagnostic_code decorator + registry from
 * src/bma_standard_formulas/diagnostics/. The TS registry holds validator
 * descriptors with the same five-field metadata shape (code, severity,
 * pathSchema, owner, fn) so the parity contract (vpc-4 CI guard) can compare
 * Python and TS sides.
 */

import type { DiagnosticPayload } from "../deals/store/diagnostics-types";

export type Severity = "error" | "warning" | "info";
export type Owner = "worker" | "backend" | "both";

export type DiagnosticValidatorDescriptor = {
  code: string;
  severity: Severity;
  pathSchema: string;
  owner: Owner;
  fn: (deal: unknown) => DiagnosticPayload[];
};

const REGISTRY = new Map<string, DiagnosticValidatorDescriptor>();

/**
 * Register a diagnostic validator. Idempotent re-registration with identical
 * metadata is a no-op. Re-registering the same code with conflicting metadata
 * (severity / pathSchema / owner mismatch) throws.
 */
export function registerDiagnosticValidator(
  desc: DiagnosticValidatorDescriptor,
): DiagnosticValidatorDescriptor {
  const existing = REGISTRY.get(desc.code);
  if (existing) {
    if (
      existing.severity !== desc.severity ||
      existing.pathSchema !== desc.pathSchema ||
      existing.owner !== desc.owner
    ) {
      throw new Error(
        `Diagnostic code '${desc.code}' already registered with conflicting metadata ` +
          `(existing: severity=${existing.severity}, pathSchema=${existing.pathSchema}, owner=${existing.owner}; ` +
          `new: severity=${desc.severity}, pathSchema=${desc.pathSchema}, owner=${desc.owner})`,
      );
    }
  }
  REGISTRY.set(desc.code, desc);
  return desc;
}

/**
 * Look up a validator descriptor by code. Returns undefined if not registered.
 */
export function getDiagnosticValidator(
  code: string,
): DiagnosticValidatorDescriptor | undefined {
  return REGISTRY.get(code);
}

/**
 * Iterate all registered validators. Order is insertion order per Map semantics.
 */
export function iterDiagnosticValidators(): IterableIterator<
  DiagnosticValidatorDescriptor
> {
  return REGISTRY.values();
}

/**
 * Test-only: clear the registry. Production code should never call this.
 */
export function clearRegistryForTesting(): void {
  REGISTRY.clear();
}
