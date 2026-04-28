"""Scenario-scoped and run-scoped output bundles with artifact manifests."""
from typing import Optional

from pydantic import BaseModel, Field

from .common import PrecisionPolicy, SchemaMetadata
from .output_bond import (
    BondCashflowRow,
    CarryTieoutSummary,
    CreditEnhancementRow,
    TrancheRiskSummaryRow,
)
from .output_structuring import (
    PacTacDiagnosticsRow,
    StressMatrixTrancheRow,
    StructureCompositionRow,
)
from .output_waterfall import (
    DealAccountRow,
    TriggerStateRow,
    WaterfallTraceRow,
)


class ScenarioOutputBundle(BaseModel):
    """All outputs for a single scenario execution."""
    scenario_name: str

    bond_cashflows: list[BondCashflowRow] = Field(default_factory=list)
    deal_accounts: list[DealAccountRow] = Field(default_factory=list)
    waterfall_trace: list[WaterfallTraceRow] = Field(default_factory=list)
    trigger_state_history: list[TriggerStateRow] = Field(default_factory=list)
    tranche_risk_summary: list[TrancheRiskSummaryRow] = Field(default_factory=list)
    credit_enhancement: list[CreditEnhancementRow] = Field(default_factory=list)
    pac_tac_diagnostics: list[PacTacDiagnosticsRow] = Field(default_factory=list)
    structure_composition: list[StructureCompositionRow] = Field(default_factory=list)

    # Engine-truth carry tie-out (per-tranche YTM/duration, pool YTM,
    # back-solved residual yield, status). Populated by
    # `bma_cfengine_app.orchestrator.deals.carry_tieout_service` after
    # the bond cashflows are materialized. Optional so older runs and
    # collateral-only scenarios remain backwards-compatible.
    carry_tieout: Optional[CarryTieoutSummary] = None


class DealRunOutput(BaseModel):
    """Complete output bundle for a deal run (all scenarios)."""
    metadata: SchemaMetadata = Field(default_factory=SchemaMetadata)
    precision: PrecisionPolicy = Field(default_factory=PrecisionPolicy)

    scenarios: list[ScenarioOutputBundle] = Field(default_factory=list)
    stress_matrix: list[StressMatrixTrancheRow] = Field(default_factory=list)

    artifact_keys: list[str] = Field(default_factory=list)
