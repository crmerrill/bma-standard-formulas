import { describe, expect, test } from "vitest";

type DiagnosticPayload = import("./diagnostics-types").DiagnosticPayload;

describe("sds-2 diagnostics payload typing", () => {
  test("test_diagnostic_payload_shape_matches_python_envelope", async () => {
    await import("./diagnostics-types");

    const payload: DiagnosticPayload = {
      code: "X",
      severity: "error",
      path: "$.foo",
      message: "bar",
      payload: { extra: 1 },
    };

    expect(payload).toEqual(
      expect.objectContaining({
        code: expect.any(String),
        severity: expect.any(String),
        path: expect.any(String),
        message: expect.any(String),
        payload: expect.any(Object),
      }),
    );

    expect(typeof payload.code).toBe("string");
    expect(typeof payload.severity).toBe("string");
    expect(typeof payload.path).toBe("string");
    expect(typeof payload.message).toBe("string");
    expect(typeof payload.payload).toBe("object");
  });
});
