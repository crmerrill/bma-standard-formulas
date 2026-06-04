/**
 * ve-1-worker-host: Web Worker entry point for the TS validation registry.
 *
 * Receives a serialized deal payload from the main thread, runs all registered
 * worker validators, and posts back DiagnosticPayload[].
 *
 * `runValidators` is exported for direct unit-testing in Vitest (jsdom cannot
 * instantiate real Workers, so tests import this function instead of
 * constructing the worker).
 */

import type { DiagnosticPayload } from "../deals/store/diagnostics-types";
import { iterDiagnosticValidators } from "./diagnosticRegistry";
import "./structuralValidators"; // side-effect: registers BOND_NAME_EMPTY (and future validators)

export function runValidators(deal: unknown): DiagnosticPayload[] {
  const diagnostics: DiagnosticPayload[] = [];
  for (const validator of iterDiagnosticValidators()) {
    diagnostics.push(...validator.fn(deal));
  }
  return diagnostics;
}

self.onmessage = (e: MessageEvent<{ deal: unknown; requestId: number; sessionId: string }>) => {
  self.postMessage({
    diagnostics: runValidators(e.data.deal),
    requestId: e.data.requestId,
    sessionId: e.data.sessionId,
  });
};
