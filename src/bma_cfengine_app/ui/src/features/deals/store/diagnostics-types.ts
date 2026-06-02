// FUTURE: vpc-3 registry parity
export type DiagnosticPayload = {
  code: string;
  severity: "error" | "warning" | "info";
  path: string;
  message: string;
  payload: Record<string, unknown>;
};
