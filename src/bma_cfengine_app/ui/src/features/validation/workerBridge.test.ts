/**
 * ve-1-worker-host: Vitest suite for the workerBridge debounce logic.
 * AC 3 — worker execution is debounced via VALIDATION_DEBOUNCE_MS = 300.
 *         A burst of dispatches within 300ms produces exactly ONE worker invocation.
 *         Test uses fake timers and asserts exact timing.
 */

import { describe, it, expect, vi, afterEach } from "vitest";

// T1: these imports will FAIL until workerBridge.ts is created (I commit).
import { createWorkerBridge, VALIDATION_DEBOUNCE_MS } from "./workerBridge";

// ---------------------------------------------------------------------------
// Helper: build a minimal mock Worker instance and stub global Worker.
// ---------------------------------------------------------------------------
function makeWorkerStub() {
  const mockPostMessage = vi.fn();
  const instance = {
    postMessage: mockPostMessage,
    terminate: vi.fn(),
    onmessage: null as ((e: MessageEvent) => void) | null,
  };
  vi.stubGlobal("Worker", function MockWorker() { return instance; });
  return { mockPostMessage, instance };
}

// ---------------------------------------------------------------------------
// Helper: build a minimal mock store backed by a mutable storeState ref.
// ---------------------------------------------------------------------------
function makeStore(initial: Record<string, unknown>) {
  let storeState = { ...initial };
  const subscribers: Array<(state: unknown, prev: unknown) => void> = [];
  const mockStore = {
    subscribe: vi.fn((cb: (state: unknown, prev: unknown) => void) => {
      subscribers.push(cb);
      return () => {
        const idx = subscribers.indexOf(cb);
        if (idx !== -1) subscribers.splice(idx, 1);
      };
    }),
    getState: vi.fn(() => storeState),
  };
  const emit = (next: Record<string, unknown>) => {
    const prev = storeState;
    storeState = { ...next };
    for (const cb of subscribers) cb(storeState, prev);
  };
  return { mockStore, emit, getState: () => storeState };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("test_bridge_debounces_rapid_mutations", () => {
  it("VALIDATION_DEBOUNCE_MS is exactly 300", () => {
    expect(VALIDATION_DEBOUNCE_MS).toBe(300);
  });

  it("invokes the worker exactly once for 5 mutations within 200ms (AC 3)", () => {
    vi.useFakeTimers();

    // Mock the global Worker constructor so jsdom doesn't throw.
    // Use a regular function (not arrow) so it is constructable with `new`.
    const mockPostMessage = vi.fn();
    const mockTerminate = vi.fn();
    const mockWorkerInstance = {
      postMessage: mockPostMessage,
      terminate: mockTerminate,
      onmessage: null as ((e: MessageEvent) => void) | null,
    };
    vi.stubGlobal("Worker", function MockWorker() { return mockWorkerInstance; });

    // Minimal store stub: records the subscriber so tests can drive it.
    const subscribers: Array<(state: unknown, prev: unknown) => void> = [];
    const mockStore = {
      subscribe: vi.fn((cb: (state: unknown, prev: unknown) => void) => {
        subscribers.push(cb);
        return () => {
          const idx = subscribers.indexOf(cb);
          if (idx !== -1) subscribers.splice(idx, 1);
        };
      }),
      getState: vi.fn(() => ({
        activeSessionId: "main",
        sessions: { main: { working_tree: { bonds: [] } } },
        setDiagnostics: vi.fn(),
      })),
    };

    const bridge = createWorkerBridge(mockStore);

    // Helper: fire a single revision increment through all registered subscribers.
    let revision = 0;
    const emit = () => {
      const prev = {
        dispatch_revision: revision,
        activeSessionId: "main",
        sessions: { main: { working_tree: { bonds: [] } } },
      };
      revision += 1;
      const next = {
        dispatch_revision: revision,
        activeSessionId: "main",
        sessions: { main: { working_tree: { bonds: [] } } },
      };
      for (const cb of subscribers) cb(next, prev);
    };

    // Fire 5 mutations 40ms apart → total span = 160ms, well within 300ms debounce.
    emit(); // t = 0
    vi.advanceTimersByTime(40); // t = 40
    emit();
    vi.advanceTimersByTime(40); // t = 80
    emit();
    vi.advanceTimersByTime(40); // t = 120
    emit();
    vi.advanceTimersByTime(40); // t = 160
    emit(); // last mutation; debounce timer resets to fire at t = 160 + 300 = 460

    // At t = 160ms the worker must not have been called yet.
    expect(mockPostMessage).not.toHaveBeenCalled();

    // Advance exactly 300ms past the last mutation → debounce fires.
    vi.advanceTimersByTime(VALIDATION_DEBOUNCE_MS);

    // Exactly one worker invocation for the entire burst.
    expect(mockPostMessage).toHaveBeenCalledTimes(1);

    bridge.unsubscribe();
  });

  it("invokes the worker immediately after a single mutation + 300ms (AC 3)", () => {
    vi.useFakeTimers();

    const mockPostMessage = vi.fn();
    const mockWorkerInstance = {
      postMessage: mockPostMessage,
      terminate: vi.fn(),
      onmessage: null as ((e: MessageEvent) => void) | null,
    };
    // Use a regular function (not arrow) so it can be used as a constructor.
    vi.stubGlobal("Worker", function MockWorker() { return mockWorkerInstance; });

    const subscribers: Array<(state: unknown, prev: unknown) => void> = [];
    const mockStore = {
      subscribe: vi.fn((cb: (state: unknown, prev: unknown) => void) => {
        subscribers.push(cb);
        return () => {};
      }),
      getState: vi.fn(() => ({
        activeSessionId: "main",
        sessions: { main: { working_tree: { bonds: [] } } },
        setDiagnostics: vi.fn(),
      })),
    };

    const bridge = createWorkerBridge(mockStore);

    // Single mutation.
    const prev = { dispatch_revision: 0, activeSessionId: "main", sessions: { main: { working_tree: {} } } };
    const next = { dispatch_revision: 1, activeSessionId: "main", sessions: { main: { working_tree: {} } } };
    for (const cb of subscribers) cb(next, prev);

    // Not yet invoked.
    expect(mockPostMessage).not.toHaveBeenCalled();

    vi.advanceTimersByTime(VALIDATION_DEBOUNCE_MS);

    expect(mockPostMessage).toHaveBeenCalledTimes(1);

    bridge.unsubscribe();
  });

  it("does not invoke the worker when dispatch_revision is unchanged (AC 3)", () => {
    vi.useFakeTimers();

    const mockPostMessage = vi.fn();
    const mockWorkerInstanceNoOp = { postMessage: mockPostMessage, terminate: vi.fn(), onmessage: null as any };
    vi.stubGlobal("Worker", function MockWorker() { return mockWorkerInstanceNoOp; });

    const subscribers: Array<(state: unknown, prev: unknown) => void> = [];
    const mockStore = {
      subscribe: vi.fn((cb: (state: unknown, prev: unknown) => void) => {
        subscribers.push(cb);
        return () => {};
      }),
      getState: vi.fn(),
    };

    const bridge = createWorkerBridge(mockStore);

    // Same revision → guard should skip.
    const sameState = { dispatch_revision: 5, activeSessionId: "main", sessions: { main: { working_tree: {} } } };
    for (const cb of subscribers) cb(sameState, sameState);

    vi.advanceTimersByTime(VALIDATION_DEBOUNCE_MS);

    expect(mockPostMessage).not.toHaveBeenCalled();

    bridge.unsubscribe();
  });
});

// ---------------------------------------------------------------------------
// M1 fix tests: session attribution + stale-request guard
// ---------------------------------------------------------------------------

describe("test_bridge_routes_diagnostics_to_validated_session_not_active_session", () => {
  it("routes diagnostics to the session that was validated, even if active session changes before response (M1)", () => {
    vi.useFakeTimers();

    const setDiagnostics = vi.fn();

    const mockPostMessage = vi.fn();
    const mockWorkerInstance = {
      postMessage: mockPostMessage,
      terminate: vi.fn(),
      onmessage: null as ((e: MessageEvent) => void) | null,
    };
    vi.stubGlobal("Worker", function MockWorker() { return mockWorkerInstance; });

    // Initial store state: session A is active.
    let storeState = {
      dispatch_revision: 0,
      activeSessionId: "A",
      sessions: {
        A: { working_tree: { bonds: [] } },
        B: { working_tree: { bonds: [] } },
      },
      setDiagnostics,
    };

    const subscribers: Array<(state: unknown, prev: unknown) => void> = [];
    const mockStore = {
      subscribe: vi.fn((cb: (state: unknown, prev: unknown) => void) => {
        subscribers.push(cb);
        return () => {
          const idx = subscribers.indexOf(cb);
          if (idx !== -1) subscribers.splice(idx, 1);
        };
      }),
      getState: vi.fn(() => storeState),
    };

    const bridge = createWorkerBridge(mockStore);

    // Trigger a revision change on session A.
    const prevState = { ...storeState };
    storeState = { ...storeState, dispatch_revision: 1 };
    for (const cb of subscribers) cb(storeState, prevState);

    // Advance past debounce → worker receives postMessage for session A.
    vi.advanceTimersByTime(VALIDATION_DEBOUNCE_MS);
    expect(mockPostMessage).toHaveBeenCalledTimes(1);

    // Switch active session to B BEFORE the worker responds.
    storeState = { ...storeState, activeSessionId: "B" };

    // Worker responds with diagnostics tagged to session A (new protocol).
    const diagnostics = [
      { code: "E001", severity: "error" as const, path: "bond[0]", message: "test", payload: {} },
    ];
    mockWorkerInstance.onmessage!(
      new MessageEvent("message", { data: { diagnostics, requestId: 1, sessionId: "A" } }),
    );

    // Diagnostics must land on session A — NOT on the currently-active session B.
    expect(setDiagnostics).toHaveBeenCalledTimes(1);
    expect(setDiagnostics).toHaveBeenCalledWith("A", diagnostics);
    expect(setDiagnostics).not.toHaveBeenCalledWith("B", expect.anything());

    bridge.unsubscribe();
  });

  it("ignores stale responses whose requestId is less than the latest for that session (stale-guard)", () => {
    vi.useFakeTimers();

    const setDiagnostics = vi.fn();

    const mockPostMessage = vi.fn();
    const mockWorkerInstance = {
      postMessage: mockPostMessage,
      terminate: vi.fn(),
      onmessage: null as ((e: MessageEvent) => void) | null,
    };
    vi.stubGlobal("Worker", function MockWorker() { return mockWorkerInstance; });

    let storeState = {
      dispatch_revision: 0,
      activeSessionId: "A",
      sessions: { A: { working_tree: { bonds: [] } } },
      setDiagnostics,
    };

    const subscribers: Array<(state: unknown, prev: unknown) => void> = [];
    const mockStore = {
      subscribe: vi.fn((cb: (state: unknown, prev: unknown) => void) => {
        subscribers.push(cb);
        return () => {};
      }),
      getState: vi.fn(() => storeState),
    };

    const bridge = createWorkerBridge(mockStore);

    // First mutation → debounce fires → postMessage with requestId=1.
    const prev0 = { ...storeState };
    storeState = { ...storeState, dispatch_revision: 1 };
    for (const cb of subscribers) cb(storeState, prev0);
    vi.advanceTimersByTime(VALIDATION_DEBOUNCE_MS);
    expect(mockPostMessage).toHaveBeenCalledTimes(1);

    // Second mutation → debounce fires → postMessage with requestId=2.
    const prev1 = { ...storeState };
    storeState = { ...storeState, dispatch_revision: 2 };
    for (const cb of subscribers) cb(storeState, prev1);
    vi.advanceTimersByTime(VALIDATION_DEBOUNCE_MS);
    expect(mockPostMessage).toHaveBeenCalledTimes(2);

    const stalePayload = [{ code: "E001", severity: "error" as const, path: "a", message: "stale", payload: {} }];
    const freshPayload = [{ code: "E002", severity: "warning" as const, path: "b", message: "fresh", payload: {} }];

    // Stale response (requestId=1, latest is 2) → must be ignored.
    mockWorkerInstance.onmessage!(
      new MessageEvent("message", { data: { diagnostics: stalePayload, requestId: 1, sessionId: "A" } }),
    );
    expect(setDiagnostics).not.toHaveBeenCalled();

    // Fresh response (requestId=2) → must be applied.
    mockWorkerInstance.onmessage!(
      new MessageEvent("message", { data: { diagnostics: freshPayload, requestId: 2, sessionId: "A" } }),
    );
    expect(setDiagnostics).toHaveBeenCalledTimes(1);
    expect(setDiagnostics).toHaveBeenCalledWith("A", freshPayload);

    bridge.unsubscribe();
  });
});

// ---------------------------------------------------------------------------
// M2 fix test (ve-1 R1 pass-2): deleted-session responses must be dropped
// ---------------------------------------------------------------------------

describe("test_deleted_session_response_does_not_recreate_malformed_entry", () => {
  it("drops worker response for a session that was deleted before the response arrived (M2)", () => {
    vi.useFakeTimers();

    const setDiagnostics = vi.fn();
    const { instance: workerInstance } = makeWorkerStub();

    const { mockStore, emit } = makeStore({
      dispatch_revision: 0,
      activeSessionId: "A",
      sessions: { A: { working_tree: { bonds: [] } } },
      setDiagnostics,
    });

    const bridge = createWorkerBridge(mockStore);

    // Trigger validation for session A.
    emit({ dispatch_revision: 1, activeSessionId: "A", sessions: { A: { working_tree: { bonds: [] } } }, setDiagnostics });
    vi.advanceTimersByTime(VALIDATION_DEBOUNCE_MS);
    expect(workerInstance.postMessage).toHaveBeenCalledTimes(1);

    // Delete session A — remove it from sessions entirely.
    emit({ dispatch_revision: 1, activeSessionId: "main", sessions: {}, setDiagnostics });

    // Worker now responds for the deleted session A.
    const diagnostics = [
      { code: "E001", severity: "error" as const, path: "bond[0]", message: "test", payload: {} },
    ];
    workerInstance.onmessage!(
      new MessageEvent("message", { data: { diagnostics, requestId: 1, sessionId: "A" } }),
    );

    // Bridge must NOT call setDiagnostics — session A no longer exists.
    expect(setDiagnostics).not.toHaveBeenCalled();

    bridge.unsubscribe();
  });
});

// ---------------------------------------------------------------------------
// m1 fix test (ve-1 R1 pass-2): latestRequestId must be cleaned up on deletion
// ---------------------------------------------------------------------------

describe("test_latestRequestId_cleaned_up_on_session_delete", () => {
  it("removes the latestRequestId entry when a session is deleted (m1)", () => {
    vi.useFakeTimers();

    const { instance: workerInstance } = makeWorkerStub();
    const setDiagnostics = vi.fn();

    const { mockStore, emit } = makeStore({
      dispatch_revision: 0,
      activeSessionId: "A",
      sessions: { A: { working_tree: { bonds: [] } } },
      setDiagnostics,
    });

    const bridge = createWorkerBridge(mockStore);

    // Trigger validation → latestRequestId["A"] should be set to 1.
    emit({ dispatch_revision: 1, activeSessionId: "A", sessions: { A: { working_tree: { bonds: [] } } }, setDiagnostics });
    vi.advanceTimersByTime(VALIDATION_DEBOUNCE_MS);
    expect(workerInstance.postMessage).toHaveBeenCalledTimes(1);

    // Confirm "A" is tracked in latestRequestId.
    expect(bridge._getLatestRequestIdForTesting()).toHaveProperty("A", 1);

    // Delete session A.
    emit({ dispatch_revision: 1, activeSessionId: "main", sessions: {}, setDiagnostics });

    // latestRequestId["A"] must have been cleaned up.
    expect(bridge._getLatestRequestIdForTesting()).not.toHaveProperty("A");

    bridge.unsubscribe();
  });
});
