import { beforeEach, describe, expect, test, vi } from "vitest";
import type { DiagnosticPayload } from "../deals/store/diagnostics-types";
import type { DealStoreState } from "../deals/store/useDealStore";
import {
  subscribeToValidationStream,
  _getActiveSubscriptionsForTesting,
  _resetActiveSubscriptionsForTesting,
} from "./validationStreamClient";

// ---------------------------------------------------------------------------
// Minimal mock EventSource
// ---------------------------------------------------------------------------
type MockEventSourceInstance = {
  close: ReturnType<typeof vi.fn>;
  onmessage: ((e: MessageEvent) => void) | null;
  onerror: ((e: Event) => void) | null;
  emit: (data: unknown) => void;
};

function makeMockEventSourceCtor(): {
  ctor: new (url: string) => MockEventSourceInstance;
  instances: MockEventSourceInstance[];
} {
  const instances: MockEventSourceInstance[] = [];

  class MockEventSource {
    close = vi.fn();
    onmessage: ((e: MessageEvent) => void) | null = null;
    onerror: ((e: Event) => void) | null = null;

    emit(data: unknown) {
      if (this.onmessage) {
        this.onmessage({ data: JSON.stringify(data) } as MessageEvent);
      }
    }

    constructor(_url: string) {
      instances.push(this as unknown as MockEventSourceInstance);
    }
  }

  return {
    ctor: MockEventSource as unknown as new (url: string) => MockEventSourceInstance,
    instances,
  };
}

// ---------------------------------------------------------------------------
// Minimal mock store
// ---------------------------------------------------------------------------
function makeMockStore(): {
  store: { getState: () => DealStoreState };
  mergeDiagnostics: ReturnType<typeof vi.fn>;
} {
  const mergeDiagnostics = vi.fn();
  const store = {
    getState: () => ({ mergeDiagnostics } as unknown as DealStoreState),
  };
  return { store, mergeDiagnostics };
}

const DEAL_ID = "deal-1";
const SHA = "abc123";
const SESSION_ID = "main";

describe("validationStreamClient (ve-4a)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    _resetActiveSubscriptionsForTesting();
  });

  // -------------------------------------------------------------------------
  // AC 1, 2: subscribe opens EventSource; diagnostic events dispatch to store
  // -------------------------------------------------------------------------
  test("test_subscribe_dispatches_diagnostic_events", () => {
    const { ctor, instances } = makeMockEventSourceCtor();
    const { store, mergeDiagnostics } = makeMockStore();

    subscribeToValidationStream(DEAL_ID, SHA, SESSION_ID, store, ctor);

    expect(instances).toHaveLength(1);

    const diagPayload: DiagnosticPayload = {
      code: "X",
      path: "$.foo",
      severity: "error",
      message: "msg",
      payload: {},
    };
    instances[0].emit({ event_type: "diagnostic", payload: diagPayload });

    expect(mergeDiagnostics).toHaveBeenCalledOnce();
    expect(mergeDiagnostics).toHaveBeenCalledWith(
      SESSION_ID,
      "backend",
      [diagPayload],
    );
  });

  // -------------------------------------------------------------------------
  // AC 3: validation_complete closes the EventSource
  // -------------------------------------------------------------------------
  test("test_subscribe_closes_on_validation_complete", () => {
    const { ctor, instances } = makeMockEventSourceCtor();
    const { store } = makeMockStore();

    subscribeToValidationStream(DEAL_ID, SHA, SESSION_ID, store, ctor);

    instances[0].emit({ event_type: "validation_complete" });

    expect(instances[0].close).toHaveBeenCalledOnce();
  });

  // -------------------------------------------------------------------------
  // AC 4: validation_failed merges error diagnostic AND closes EventSource
  // -------------------------------------------------------------------------
  test("test_subscribe_merges_error_and_closes_on_validation_failed", () => {
    const { ctor, instances } = makeMockEventSourceCtor();
    const { store, mergeDiagnostics } = makeMockStore();

    subscribeToValidationStream(DEAL_ID, SHA, SESSION_ID, store, ctor);

    instances[0].emit({
      event_type: "validation_failed",
      error: "Something went wrong",
    });

    // EventSource must be closed
    expect(instances[0].close).toHaveBeenCalledOnce();

    // An error-severity diagnostic must be merged
    expect(mergeDiagnostics).toHaveBeenCalledOnce();
    const [calledSessionId, calledSource, calledPayloads] =
      mergeDiagnostics.mock.calls[0];
    expect(calledSessionId).toBe(SESSION_ID);
    expect(calledSource).toBe("backend");
    expect(calledPayloads).toHaveLength(1);
    expect((calledPayloads as DiagnosticPayload[])[0].severity).toBe("error");
  });

  // -------------------------------------------------------------------------
  // AC 5: unsubscribe() closes the EventSource
  // -------------------------------------------------------------------------
  test("test_unsubscribe_closes_event_source", () => {
    const { ctor, instances } = makeMockEventSourceCtor();
    const { store } = makeMockStore();

    const { unsubscribe } = subscribeToValidationStream(
      DEAL_ID,
      SHA,
      SESSION_ID,
      store,
      ctor,
    );

    unsubscribe();

    expect(instances[0].close).toHaveBeenCalledOnce();
  });

  // -------------------------------------------------------------------------
  // R1 Finding 1: terminal events must clear _activeSubscriptions
  // These tests are RED until close() is patched to delete the active token.
  // -------------------------------------------------------------------------
  test("test_validation_complete_clears_active_token", () => {
    const { ctor, instances } = makeMockEventSourceCtor();
    const { store } = makeMockStore();

    subscribeToValidationStream(DEAL_ID, SHA, SESSION_ID, store, ctor);
    expect(_getActiveSubscriptionsForTesting().has(SESSION_ID)).toBe(true);

    instances[0].emit({ event_type: "validation_complete" });

    expect(_getActiveSubscriptionsForTesting().has(SESSION_ID)).toBe(false);
  });

  test("test_validation_failed_clears_active_token", () => {
    const { ctor, instances } = makeMockEventSourceCtor();
    const { store } = makeMockStore();

    subscribeToValidationStream(DEAL_ID, SHA, SESSION_ID, store, ctor);
    expect(_getActiveSubscriptionsForTesting().has(SESSION_ID)).toBe(true);

    instances[0].emit({
      event_type: "validation_failed",
      error: "Upstream failure",
    });

    expect(_getActiveSubscriptionsForTesting().has(SESSION_ID)).toBe(false);
  });

  // -------------------------------------------------------------------------
  // AC 6: stale-stream protection — superseded subscription events are ignored
  // -------------------------------------------------------------------------
  test("test_subscribe_ignores_stale_stream_events_for_superseded_sha_or_session", () => {
    const { ctor: ctorA, instances: instancesA } = makeMockEventSourceCtor();
    const { ctor: ctorB, instances: instancesB } = makeMockEventSourceCtor();
    const { store, mergeDiagnostics } = makeMockStore();

    // Stream A: subscribe first
    subscribeToValidationStream(DEAL_ID, SHA, SESSION_ID, store, ctorA);
    expect(instancesA).toHaveLength(1);

    // Stream B: supersede A for the same sessionId
    subscribeToValidationStream(DEAL_ID, "def456", SESSION_ID, store, ctorB);
    expect(instancesB).toHaveLength(1);

    // Emit a diagnostic from the STALE stream A — must be ignored
    instancesA[0].emit({
      event_type: "diagnostic",
      payload: {
        code: "STALE",
        path: "$.x",
        severity: "error",
        message: "stale",
        payload: {},
      },
    });

    expect(mergeDiagnostics).not.toHaveBeenCalled();

    // Emit from active stream B — must be dispatched
    instancesB[0].emit({
      event_type: "diagnostic",
      payload: {
        code: "FRESH",
        path: "$.y",
        severity: "warning",
        message: "fresh",
        payload: {},
      },
    });

    expect(mergeDiagnostics).toHaveBeenCalledOnce();
    expect(mergeDiagnostics.mock.calls[0][2][0].code).toBe("FRESH");
  });
});
