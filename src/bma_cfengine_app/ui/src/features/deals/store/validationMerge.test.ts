import { beforeEach, describe, expect, test } from "vitest";
import { useDealStore } from "./useDealStore";
import type { DiagnosticPayload } from "./diagnostics-types";

const sid = "main";

function makeDiag(
  code: string,
  path: string,
  message: string,
): DiagnosticPayload {
  return { code, path, severity: "error", message, payload: {} };
}

describe("mergeDiagnostics (ve-4)", () => {
  beforeEach(() => {
    useDealStore.setState(useDealStore.getInitialState(), true);
  });

  test("test_mergeDiagnostics_backend_wins_on_conflict", () => {
    // AC 1, 2: worker emits code X at $.foo; backend emits same key → backend wins
    useDealStore
      .getState()
      .mergeDiagnostics(sid, "worker", [makeDiag("X", "$.foo", "worker")]);
    useDealStore
      .getState()
      .mergeDiagnostics(sid, "backend", [makeDiag("X", "$.foo", "backend")]);
    const diagnostics = useDealStore.getState().sessions[sid].diagnostics;
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0].message).toBe("backend");
  });

  test("test_mergeDiagnostics_retains_non_overlapping", () => {
    // AC 3: worker emits code A; backend emits code B → both retained
    useDealStore
      .getState()
      .mergeDiagnostics(sid, "worker", [makeDiag("A", "$.x", "worker-a")]);
    useDealStore
      .getState()
      .mergeDiagnostics(sid, "backend", [makeDiag("B", "$.y", "backend-b")]);
    const diagnostics = useDealStore.getState().sessions[sid].diagnostics;
    expect(diagnostics).toHaveLength(2);
    const codes = diagnostics.map((d) => d.code);
    expect(codes).toContain("A");
    expect(codes).toContain("B");
  });

  test("test_mergeDiagnostics_source_map_tracks_origin", () => {
    // AC 4 / R1 NF M5: backend-wins semantics persist across subsequent worker merges.
    // worker emits X:$.foo → backend overwrites → second worker merge of same key
    // must NOT overwrite the backend version.
    useDealStore
      .getState()
      .mergeDiagnostics(sid, "worker", [makeDiag("X", "$.foo", "worker-v1")]);
    useDealStore
      .getState()
      .mergeDiagnostics(sid, "backend", [makeDiag("X", "$.foo", "backend-v1")]);
    useDealStore
      .getState()
      .mergeDiagnostics(sid, "worker", [makeDiag("X", "$.foo", "worker-v2")]);
    const diagnostics = useDealStore.getState().sessions[sid].diagnostics;
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0].message).toBe("backend-v1");
  });
});
