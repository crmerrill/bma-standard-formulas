/**
 * ve-1-worker-host: Debounced bridge between the main-thread Zustand store and
 * the validation Web Worker.
 *
 * Subscribes to store dispatch events, debounces rapid mutations, posts the
 * current working_tree to the worker, and routes returned DiagnosticPayload[]
 * back into the store via setDiagnostics.
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

export function createWorkerBridge(useStore: StoreApi): { unsubscribe: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let worker: Worker | null = null;

  function ensureWorker(): Worker {
    if (!worker) {
      worker = new Worker(
        new URL("./validationWorker.ts", import.meta.url),
        { type: "module" },
      );
      worker.onmessage = (e: MessageEvent<{ diagnostics: DiagnosticPayload[] }>) => {
        const state = useStore.getState();
        state.setDiagnostics(state.activeSessionId, e.data.diagnostics);
      };
    }
    return worker;
  }

  const unsubscribe = useStore.subscribe((state, prev) => {
    if (state.dispatch_revision === prev.dispatch_revision) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      const w = ensureWorker();
      const session = state.sessions[state.activeSessionId];
      if (session) {
        w.postMessage({ deal: session.working_tree });
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
