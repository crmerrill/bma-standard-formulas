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
 *
 * M2 fix (ve-1 R1 pass-2): before applying diagnostics the bridge checks that
 * the session still exists in the store; if not, the response is dropped. This
 * prevents setDiagnostics from recreating a malformed entry via spread of
 * undefined when a session is deleted between postMessage and onmessage.
 *
 * m1 fix (ve-1 R1 pass-2): the store subscription now detects session
 * deletions and removes the corresponding latestRequestId entry so the map
 * is bounded to live sessions only.
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

export function createWorkerBridge(useStore: StoreApi): {
  unsubscribe: () => void;
  /** Test-only: snapshot of the internal per-session request-id map. */
  _getLatestRequestIdForTesting: () => Record<string, number>;
} {
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
        // M2 fix: drop response if the session was deleted while the worker
        // was running; avoids recreating a malformed entry in the store.
        if (!state.sessions[sessionId]) return;
        state.setDiagnostics(sessionId, diagnostics);
      };
    }
    return worker;
  }

  const unsubscribe = useStore.subscribe((state, prev) => {
    // m1 fix: clean up latestRequestId for any session that was removed.
    for (const key of Object.keys(latestRequestId)) {
      if (!(key in state.sessions)) {
        delete latestRequestId[key];
      }
    }

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
    _getLatestRequestIdForTesting: () => ({ ...latestRequestId }),
  };
}
