/**
 * ve-1-worker-host: Vitest suite for the workerBridge debounce logic.
 * AC 3 — worker execution is debounced via VALIDATION_DEBOUNCE_MS = 300.
 *         A burst of dispatches within 300ms produces exactly ONE worker invocation.
 *         Test uses fake timers and asserts exact timing.
 */

import { describe, it, expect, vi, afterEach } from "vitest";

// T1: these imports will FAIL until workerBridge.ts is created (I commit).
import { createWorkerBridge, VALIDATION_DEBOUNCE_MS } from "./workerBridge";

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
    const mockPostMessage = vi.fn();
    const mockTerminate = vi.fn();
    const mockWorkerInstance = {
      postMessage: mockPostMessage,
      terminate: mockTerminate,
      onmessage: null as ((e: MessageEvent) => void) | null,
    };
    vi.stubGlobal("Worker", vi.fn(() => mockWorkerInstance));

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
    vi.stubGlobal("Worker", vi.fn(() => mockWorkerInstance));

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
    vi.stubGlobal("Worker", vi.fn(() => ({ postMessage: mockPostMessage, terminate: vi.fn(), onmessage: null })));

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
