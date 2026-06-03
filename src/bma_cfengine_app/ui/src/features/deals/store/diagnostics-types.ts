// FUTURE: vpc-3 registry parity

/**
 * Optional quick-fix payload attached to a diagnostic (ve-5).
 * `action_id` names a typed action; `params` carries its typed payload.
 */
export type QuickFix = {
  action_id: string;
  params: Record<string, unknown>;
};

export type DiagnosticPayload = {
  code: string;
  severity: "error" | "warning" | "info";
  path: string;
  message: string;
  payload: Record<string, unknown>;
  /**
   * ve-5: optional quick-fix for this diagnostic. Backward-compatible —
   * payloads without `fix` remain valid; consumers should null-check.
   */
  fix?: QuickFix;
};
