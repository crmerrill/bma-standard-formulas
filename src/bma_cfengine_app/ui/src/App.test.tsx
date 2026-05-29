// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";
import App from "./App";
import * as api from "./services/api";

vi.mock("./services/api", () => ({
  getRun: vi.fn(),
  getRunConfig: vi.fn(),
  getSavedMapping: vi.fn(),
}));

vi.mock("./pages/TapeIntakePage", () => ({
  default: ({ onComplete, asofDate }: { onComplete: (u: string, m: string, maps: unknown[]) => void; asofDate: string }) => (
    <div>
      <div>Intake mock ({asofDate})</div>
      <button type="button" onClick={() => onComplete("u_1", "m_1", [])}>
        Complete Intake
      </button>
    </div>
  ),
}));

vi.mock("./pages/TapeViewPage", () => ({
  default: ({ onOpenTape }: { onOpenTape: (u: string, m: string) => Promise<void> | void }) => (
    <div>
      <div>Tape view mock</div>
      <button type="button" onClick={() => void onOpenTape("u_2", "m_2")}>
        Open Tape Item
      </button>
    </div>
  ),
}));

vi.mock("./pages/RunSetupPage", () => ({
  default: ({ onRunComplete }: { onRunComplete: (run: any) => void }) => (
    <div>
      <div>Run setup mock</div>
      <button
        type="button"
        onClick={() =>
          onRunComplete({
            run_id: "run_direct",
            status: "completed",
            created_at: "2026-01-01T00:00:00Z",
            sections: [],
          })
        }
      >
        Complete Run
      </button>
    </div>
  ),
}));

vi.mock("./pages/ResultsPage", () => ({
  default: ({ run }: { run: { run_id: string } }) => <div>Results mock ({run.run_id})</div>,
}));

vi.mock("./pages/RunHistoryPage", () => ({
  default: ({
    onViewRun,
    onRerun,
    onOpenSolverStudio,
  }: {
    onViewRun: (runId: string, runType?: "portfolio" | "structured_deal") => Promise<void> | void;
    onRerun: (runId: string) => Promise<void> | void;
    onOpenSolverStudio: (runId: string) => void;
  }) => (
    <div>
      <div>History mock</div>
      <button type="button" onClick={() => void onViewRun("run_hist_1")}>
        View Portfolio Run
      </button>
      <button type="button" onClick={() => void onViewRun("run_struct_1", "structured_deal")}>
        View Structured Run
      </button>
      <button type="button" onClick={() => void onRerun("run_rerun_1")}>
        Rerun Portfolio Run
      </button>
      <button type="button" onClick={() => onOpenSolverStudio("run_solver_1")}>
        Open Solver Studio
      </button>
    </div>
  ),
}));

vi.mock("./features/deals/DealEditor", () => ({
  default: ({ onDirtyStateChange }: { onDirtyStateChange?: (dirty: boolean) => void }) => (
    <div>
      <div>Deal editor mock</div>
      <button type="button" onClick={() => onDirtyStateChange?.(true)}>
        Mark Structuring Dirty
      </button>
    </div>
  ),
}));

vi.mock("./pages/StructuredDealAnalysisPage", () => ({
  default: () => <div>Structured analysis mock</div>,
}));

describe("App shell flows", () => {
  const mockedGetRun = vi.mocked(api.getRun);
  const mockedGetRunConfig = vi.mocked(api.getRunConfig);
  const mockedGetSavedMapping = vi.mocked(api.getSavedMapping);

  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    mockedGetSavedMapping.mockResolvedValue({
      mappings: [{ source_column: "loan_id", canonical_field: "loan_id" }],
      asof_date: "2026-03-15",
    });
    mockedGetRun.mockResolvedValue({
      run_id: "run_hist_1",
      status: "completed",
      created_at: "2026-03-15T00:00:00Z",
      sections: [],
    });
    mockedGetRunConfig.mockResolvedValue({
      run_config: {
        upload_id: "u_hist",
        mapping_id: "m_hist",
        mappings: [],
        asof_date: "2026-03-15",
        grouping: { keys: ["state"] },
        run_mode: "actual",
        include_period_zero: false,
      },
      scenarios: [],
      group_names: [],
      summary: {},
    });
    vi.spyOn(window, "confirm").mockImplementation(() => true);
  });

  afterEach(() => {
    cleanup();
  });

  it("supports intake to results path and reset", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByText(/Intake mock/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Complete Intake" }));
    expect(screen.getByText("Tape view mock")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open Tape Item" }));
    await waitFor(() => expect(mockedGetSavedMapping).toHaveBeenCalledWith("u_2", "m_2"));

    await user.click(screen.getByRole("button", { name: "Run Setup" }));
    expect(screen.getByText("Run setup mock")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Complete Run" }));
    expect(screen.getByText("Results mock (run_direct)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New Session" }));
    expect(screen.getByText(/Intake mock/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tape View" })).toBeDisabled();
  });

  it("keeps user on structuring page when dirty and navigation is denied", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<App />);
    await user.click(screen.getByRole("button", { name: "Structuring Studio" }));
    expect(screen.getByText("Deal editor mock")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Mark Structuring Dirty" }));
    await user.click(screen.getByRole("button", { name: "Run History" }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(screen.getByText("Deal editor mock")).toBeInTheDocument();
  });

  it("routes history actions to results, setup, and structured analysis", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Run History" }));
    expect(screen.getByText("History mock")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "View Structured Run" }));
    expect(screen.getByText("Structured analysis mock")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Run History" }));
    await user.click(screen.getByRole("button", { name: "View Portfolio Run" }));
    await waitFor(() => expect(mockedGetRun).toHaveBeenCalledWith("run_hist_1"));
    expect(screen.getByText("Results mock (run_hist_1)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Run History" }));
    await user.click(screen.getByRole("button", { name: "Rerun Portfolio Run" }));
    await waitFor(() => expect(mockedGetRunConfig).toHaveBeenCalledWith("run_rerun_1"));
    expect(screen.getByText("Run setup mock")).toBeInTheDocument();
  });

  it("restores page from session storage on load", () => {
    sessionStorage.setItem(
      "bma_cfengine_session",
      JSON.stringify({
        page: "history",
      }),
    );
    render(<App />);
    expect(screen.getByText("History mock")).toBeInTheDocument();
  });
});
