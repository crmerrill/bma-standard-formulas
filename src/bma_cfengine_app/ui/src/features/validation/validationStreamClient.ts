/**
 * ve-4a-validation-stream-client: EventSource client for the ve-3 SSE
 * validation endpoint. Subscribes, dispatches `diagnostic` events into the
 * store via `mergeDiagnostics(sessionId, "backend", [...])`, and closes on
 * `validation_complete` or `validation_failed`.
 *
 * Stale-stream protection (AC 6 / R1 NF M5): a per-session subscription token
 * tracks the most recent subscription. Events from a superseded stream are
 * ignored — only the most recent subscription for a given sessionId can
 * dispatch into the store.
 */

import type { DealStoreState } from "../deals/store/useDealStore";
import type { DiagnosticPayload } from "../deals/store/diagnostics-types";

// Minimal EventSource shape we depend on. The browser-native EventSource
// satisfies this; tests inject a mock.
type EventSourceLike = {
  close: () => void;
  onmessage: ((e: MessageEvent) => void) | null;
  onerror: ((e: Event) => void) | null;
};

type EventSourceCtor = new (url: string) => EventSourceLike;

type ValidationStreamEvent = {
  event_type: "diagnostic" | "validation_complete" | "validation_failed";
  payload?: DiagnosticPayload;
  error?: string | null;
};

// Module-private: per-session active subscription token. Each call to
// subscribeToValidationStream stores a fresh symbol; events whose stream is
// not the currently-active token for its session are ignored.
const _activeSubscriptions = new Map<string, symbol>();

/** @internal Test-only: returns the active subscriptions map for assertion. */
export function _getActiveSubscriptionsForTesting(): ReadonlyMap<string, symbol> {
  return _activeSubscriptions;
}

/** @internal Test-only: clears all active subscriptions (call in beforeEach). */
export function _resetActiveSubscriptionsForTesting(): void {
  _activeSubscriptions.clear();
}

/**
 * Open an EventSource against `GET /deals/{dealId}/validate/stream?sha={sha}`
 * and dispatch incoming SSE events into the store. Returns an `unsubscribe()`
 * closer.
 */
export function subscribeToValidationStream(
  dealId: string,
  sha: string,
  sessionId: string,
  store: { getState: () => DealStoreState },
  EventSourceCtor: EventSourceCtor = (globalThis as unknown as { EventSource: EventSourceCtor }).EventSource,
): { unsubscribe: () => void } {
  const params = new URLSearchParams({ sha });
  const url = `/deals/${dealId}/validate/stream?${params.toString()}`;
  const subscriptionToken = Symbol(
    `validation-stream:${dealId}:${sha}:${sessionId}`,
  );

  // Mark this subscription as active for the session, superseding any prior.
  _activeSubscriptions.set(sessionId, subscriptionToken);

  const es = new EventSourceCtor(url);
  let closed = false;

  // Clears the active token for this session iff it still belongs to this
  // subscription — never clobbers a newer token that may have superseded.
  const clearActiveToken = () => {
    if (_activeSubscriptions.get(sessionId) === subscriptionToken) {
      _activeSubscriptions.delete(sessionId);
    }
  };

  const close = () => {
    if (closed) return;
    closed = true;
    es.close();
  };

  // Terminal close: EventSource is closed AND the active token is removed so
  // that isStillActive() cannot pass for any late-arriving messages.
  const terminalClose = () => {
    close();
    clearActiveToken();
  };

  const isStillActive = () =>
    _activeSubscriptions.get(sessionId) === subscriptionToken;

  es.onmessage = (e: MessageEvent) => {
    if (!isStillActive()) {
      // Stale stream from a superseded subscription; ignore.
      return;
    }

    let evt: ValidationStreamEvent;
    try {
      evt = JSON.parse(e.data) as ValidationStreamEvent;
    } catch {
      // Malformed event payload; skip.
      return;
    }

    if (evt.event_type === "diagnostic" && evt.payload) {
      store.getState().mergeDiagnostics(sessionId, "backend", [evt.payload]);
      return;
    }

    if (evt.event_type === "validation_complete") {
      terminalClose();
      return;
    }

    if (evt.event_type === "validation_failed") {
      const errorDiagnostic: DiagnosticPayload = {
        code: "VALIDATION_STREAM_FAILED",
        severity: "error",
        path: "",
        message: evt.error ?? "Validation stream failed",
        payload: {},
      };
      store.getState().mergeDiagnostics(sessionId, "backend", [errorDiagnostic]);
      terminalClose();
      return;
    }
  };

  return {
    unsubscribe: () => {
      clearActiveToken();
      close();
    },
  };
}
