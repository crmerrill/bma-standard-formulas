// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import Layout from "./Layout";
import { expectNoA11yViolations } from "../test/a11y";

afterEach(() => {
  cleanup();
});

describe("Layout", () => {
  it("renders title/actions and respects page enablement", async () => {
    const onNavigate = vi.fn();
    const onReset = vi.fn();
    const user = userEvent.setup();

    render(
      <Layout
        currentPage="intake"
        pageTitle="Tape Intake"
        onNavigate={onNavigate}
        onReset={onReset}
        enabledPages={new Set(["intake", "history"])}
        actions={<button type="button">Action</button>}
      >
        <div>Content</div>
      </Layout>,
    );

    expect(screen.getByRole("heading", { level: 2, name: "Tape Intake" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Action" })).toBeInTheDocument();
    expect(screen.getByText("Content")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Setup" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Run History" }));
    expect(onNavigate).toHaveBeenCalledWith("history");

    await user.click(screen.getByRole("button", { name: "New Session" }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("a11y: has no detectable accessibility violations", async () => {
    const { container } = render(
      <Layout
        currentPage="intake"
        pageTitle="Tape Intake"
        onNavigate={vi.fn()}
        enabledPages={new Set(["intake", "history"])}
      >
        <div>Content</div>
      </Layout>,
    );
    await expectNoA11yViolations(container);
  });
});
