/**
 * ve-1-worker-host: Debounced bridge between the main-thread Zustand store and
 * the validation Web Worker.
 *
 * Subscribes to store dispatch events, debounces rapid mutations, posts the
 * current working_tree to the worker, and routes returned DiagnosticPayload[]
 * back into the store via setDiagnostics.
 *
 * M1 fix (ve-1 R1): sessionId is captured at postMessage time and echoed back
 * by the worker, so responses are always routed to the session that was
 * validated — not whatever session happens to be active at response time.
 * A per-session requestId counter ensures stale responses (requestId <
 * latestRequestId[sessionId]) are silently dropped.
 */

import type { DiagnosticPayload } from "../deals/store/diagnostics-types";
import type { DealState } from "../deals/store/session";

export const VALIDATION_DEBOUNCE_MS = 300;

type DocumentSession = {
  working_tree: DealState;
};

type StoreState = {
  dispatch_revision: number;
  activeSessionId: string;
  sessions: Record<string, DocumentSession>;
  setDiagnostics: (sessionId: string, payloads: DiagnosticPayload[]) => void;
};

type StoreApi = {
  subscribe: (
    listener: (state: StoreState, prev: StoreState) => void,
  ) => () => void;
  getState: () => StoreState;
};

type WorkerResponse = {
  diagnostics: DiagnosticPayload[];
  requestId: number;
  sessionId: string;
};

export function createWorkerBridge(useStore: StoreApi): { unsubscribe: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let worker: Worker | null = null;
  const latestRequestId: Record<string, number> = {};

  function ensureWorker(): Worker {
    if (!worker) {
      worker = new Worker(
        new URL("./validationWorker.ts", import.meta.url),
        { type: "module" },
      );
      worker.onmessage = (e: MessageEvent<WorkerResponse>) => {
        const { diagnostics, requestId, sessionId } = e.data;
        if (requestId < (latestRequestId[sessionId] ?? 0)) return;
        const state = useStore.getState();
        state.setDiagnostics(sessionId, diagnostics);
      };
    }
    return worker;
  }

  const unsubscribe = useStore.subscribe((state, prev) => {
    if (state.dispatch_revision === prev.dispatch_revision) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      const currentState = useStore.getState();
      const sessionId = currentState.activeSessionId;
      const session = currentState.sessions[sessionId];
      if (session) {
        const requestId = (latestRequestId[sessionId] ?? 0) + 1;
        latestRequestId[sessionId] = requestId;
        const w = ensureWorker();
        w.postMessage({ deal: session.working_tree, requestId, sessionId });
      }
      timer = null;
    }, VALIDATION_DEBOUNCE_MS);
  });

  return {
    unsubscribe: () => {
      if (timer) clearTimeout(timer);
      unsubscribe();
      if (worker) {
        worker.terminate();
        worker = null;
      }
    },
  };
}
