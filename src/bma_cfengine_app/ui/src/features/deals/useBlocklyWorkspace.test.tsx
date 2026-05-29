// @vitest-environment jsdom
import React, { useRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { useBlocklyWorkspace } from "./useBlocklyWorkspace";

const injectMock = vi.fn();
const svgResizeMock = vi.fn();
const defineThemeMock = vi.fn((name: string, theme: unknown) => ({ name, theme }));
const registerExtMock = vi.fn();

vi.mock("blockly", () => {
  return {
    default: {},
    Blocks: {},
    Extensions: {
      register: registerExtMock,
    },
    Theme: {
      defineTheme: defineThemeMock,
    },
    inject: injectMock,
    svgResize: svgResizeMock,
  };
});

function HookHarness() {
  const ref = useRef<HTMLDivElement>(null);
  useBlocklyWorkspace({
    containerRef: ref,
    blocks: [{ type: "bond_target" }],
    toolbox: { kind: "categoryToolbox", contents: [] },
    theme: { name: "test-theme" },
    onChange: vi.fn(),
  });
  return <div ref={ref} style={{ width: 1200, height: 700 }} />;
}

describe("useBlocklyWorkspace zoom ergonomics", () => {
  it("injects workspace with professional readability zoom settings", async () => {
    const workspaceMock = {
      addChangeListener: vi.fn(),
      getBlockById: vi.fn(),
      getAllBlocks: vi.fn().mockReturnValue([]),
      scrollCenter: vi.fn(),
      dispose: vi.fn(),
    };
    injectMock.mockReturnValue(workspaceMock);

    render(<HookHarness />);

    await waitFor(() => expect(injectMock).toHaveBeenCalledTimes(1));
    const options = injectMock.mock.calls[0][1];

    expect(options.zoom.controls).toBe(true);
    expect(options.zoom.wheel).toBe(true);
    expect(options.zoom.startScale).toBeGreaterThanOrEqual(0.5);
    expect(options.zoom.startScale).toBeLessThanOrEqual(0.8);
    expect(options.zoom.maxScale).toBeGreaterThanOrEqual(1.5);
    expect(options.zoom.minScale).toBeLessThanOrEqual(0.3);
    expect(options.zoom.scaleSpeed).toBeGreaterThanOrEqual(1.05);
    expect(workspaceMock.scrollCenter).toHaveBeenCalled();
  });
});
