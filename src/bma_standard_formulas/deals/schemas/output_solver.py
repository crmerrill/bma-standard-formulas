"""Output schemas for solver iterations and run summaries."""
from typing import Any

from pydantic import BaseModel, Field

from .common import SolverStatus


class SolverIterationRow(BaseModel):
    """Single iteration of the solver loop."""
    solver_job_id: str
    solver_layer: str
    iteration: int = Field(ge=0)

    objective_value: float = 0.0
    constraint_violation_norm: float = 0.0
    feasible_flag: bool = False

    step_size: float = 0.0
    convergence_metric: float = 0.0
    status: SolverStatus = SolverStatus.RUNNING

    mutated_knobs_json: dict[str, Any] = Field(default_factory=dict)
    checkpoint_deal_version: int | None = None  # noqa: UP007


class SolverRunSummary(BaseModel):
    """Summary of a completed solver job."""
    solver_job_id: str
    solver_layers_run: list[str] = Field(default_factory=list)
    total_iterations: int = 0
    final_status: SolverStatus = SolverStatus.RUNNING
    final_objective_value: float = 0.0
    final_feasible: bool = False
    elapsed_seconds: float = 0.0
    solved_knobs: dict[str, Any] = Field(default_factory=dict)
    solved_deal_version: int | None = None
    iteration_log: list[SolverIterationRow] = Field(default_factory=list)
    selected_solution: dict[str, Any] = Field(default_factory=dict)
