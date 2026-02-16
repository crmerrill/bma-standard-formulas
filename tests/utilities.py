"""
Test Suite Utilities for BMA Compliance Tests

Provides random loan generators and scenario generators for testing
getCF.py against BMA reference implementations.

Version: 0.1.0
Last Updated: 2024-12-31
Status: Active
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from pathlib import Path

from bma_standard_formulas.payment_models import (
    cpr_to_smm_vector,
    generate_psa_curve,
    cdr_to_mdr_vector,
    generate_sda_curve,
)


# =============================================================================
# Random Seed for Reproducibility
# =============================================================================

RANDOM_SEED = 42


def get_random_state(seed: int = RANDOM_SEED) -> np.random.RandomState:
    """Get a reproducible random state."""
    return np.random.RandomState(seed)


# =============================================================================
# Loan Data Structure
# =============================================================================

@dataclass
class TestLoan:
    """Test loan parameters."""
    loan_id: int
    original_balance: float
    current_balance: float
    original_term: int
    remaining_term: int
    loan_age: int
    coupon: float  # Annual rate as decimal (e.g., 0.08 for 8%)
    rate_type: str  # 'fixed' or 'floating'
    margin: float | None = None
    index_name: str | None = None
    servicing_fee: float = 0.0025
    io_term: int = 0
    promo_term: int = 0
    promo_rate: float | None = None
    accrued_interest: float = 0.0
    
    @property
    def wam(self) -> int:
        return self.remaining_term
    
    @property
    def age(self) -> int:
        return self.loan_age
    
    @property
    def net_coupon(self) -> float:
        return self.coupon - self.servicing_fee


@dataclass
class TestScenario:
    """CPR/CDR scenario for testing."""
    scenario_id: int
    name: str
    cpr_curve: np.ndarray  # CPR as percentage (0-100)
    cdr_curve: np.ndarray  # CDR as percentage (0-100)
    severity_curve: np.ndarray  # Severity as decimal (0-1)
    severity_lag: int = 12
    
    @property
    def smm_curve(self) -> np.ndarray:
        return cpr_to_smm_vector(self.cpr_curve)
    
    @property
    def mdr_curve(self) -> np.ndarray:
        return cdr_to_mdr_vector(self.cdr_curve)


# =============================================================================
# Random Loan Generator
# =============================================================================

def generate_random_loan(loan_id: int, rng: np.random.RandomState) -> TestLoan:
    """Generate a random loan with realistic parameters."""
    original_balance = rng.uniform(50_000, 1_000_000)
    
    term_choices = [60, 120, 180, 240, 300, 360]
    original_term = rng.choice(term_choices)
    
    max_age = max(0, original_term - 12)
    loan_age = rng.randint(0, max_age + 1)
    remaining_term = original_term - loan_age
    
    if loan_age > 0:
        paydown_fraction = loan_age / original_term * 0.7
        current_balance = original_balance * (1 - paydown_fraction)
    else:
        current_balance = original_balance
    
    rate_type = 'fixed' if rng.random() < 0.8 else 'floating'
    coupon = rng.uniform(0.03, 0.12)
    margin = rng.uniform(0.01, 0.03) if rate_type == 'floating' else None
    index_name = 'SOFR' if rate_type == 'floating' else None
    servicing_fee = rng.uniform(0, 0.005)
    
    # Original IO term at loan origination
    original_io_choices = [0, 0, 0, 0, 12, 24, 36, 60]
    original_io_term = rng.choice(original_io_choices)
    # Remaining IO = max(0, original_io - loan_age)
    # If loan is older than original IO term, IO period has ended
    io_term = max(0, original_io_term - loan_age)
    
    promo_choices = [0, 0, 0, 0, 6, 12, 24]
    promo_term = rng.choice(promo_choices)
    promo_rate = coupon * rng.uniform(0.5, 0.9) if promo_term > 0 else None
    
    accrued_interest = 0.0 if rng.random() < 0.9 else original_balance * coupon / 12 * rng.uniform(0, 1)
    
    return TestLoan(
        loan_id=loan_id,
        original_balance=original_balance,
        current_balance=current_balance,
        original_term=original_term,
        remaining_term=remaining_term,
        loan_age=loan_age,
        coupon=coupon,
        rate_type=rate_type,
        margin=margin,
        index_name=index_name,
        servicing_fee=servicing_fee,
        io_term=io_term,
        promo_term=promo_term,
        promo_rate=promo_rate,
        accrued_interest=accrued_interest
    )


def generate_random_loans(count: int = 100, seed: int = RANDOM_SEED) -> list[TestLoan]:
    """Generate a list of random loans."""
    rng = get_random_state(seed)
    return [generate_random_loan(i, rng) for i in range(count)]


# =============================================================================
# CPR/CDR Scenario Generators
# =============================================================================

def generate_constant_cpr_scenario(scenario_id: int, cpr: float, term: int, severity: float = 0.20) -> TestScenario:
    """Generate a constant CPR scenario (prepay only, no defaults)."""
    return TestScenario(
        scenario_id=scenario_id,
        name=f"Constant CPR {cpr}%",
        cpr_curve=np.full(term + 1, cpr),
        cdr_curve=np.zeros(term + 1),
        severity_curve=np.full(term + 1, severity),
    )


def generate_constant_cdr_scenario(scenario_id: int, cdr: float, term: int, severity: float = 0.20) -> TestScenario:
    """Generate a constant CDR scenario (default only, no prepays)."""
    return TestScenario(
        scenario_id=scenario_id,
        name=f"Constant CDR {cdr}%",
        cpr_curve=np.zeros(term + 1),
        cdr_curve=np.full(term + 1, cdr),
        severity_curve=np.full(term + 1, severity),
    )


def generate_psa_scenario(scenario_id: int, psa_speed: float, term: int, severity: float = 0.20) -> TestScenario:
    """Generate a PSA prepay scenario (no defaults)."""
    return TestScenario(
        scenario_id=scenario_id,
        name=f"{psa_speed}% PSA",
        cpr_curve=generate_psa_curve(psa_speed, term),
        cdr_curve=np.zeros(term + 1),
        severity_curve=np.full(term + 1, severity),
    )


def generate_sda_scenario(scenario_id: int, sda_speed: float, term: int, severity: float = 0.20) -> TestScenario:
    """Generate an SDA default scenario (no prepays)."""
    return TestScenario(
        scenario_id=scenario_id,
        name=f"{sda_speed}% SDA",
        cpr_curve=np.zeros(term + 1),
        cdr_curve=generate_sda_curve(sda_speed, term),
        severity_curve=np.full(term + 1, severity),
    )


def generate_psa_sda_scenario(scenario_id: int, psa_speed: float, sda_speed: float, term: int, severity: float = 0.20) -> TestScenario:
    """Generate a combined PSA/SDA scenario."""
    return TestScenario(
        scenario_id=scenario_id,
        name=f"{psa_speed}% PSA, {sda_speed}% SDA",
        cpr_curve=generate_psa_curve(psa_speed, term),
        cdr_curve=generate_sda_curve(sda_speed, term),
        severity_curve=np.full(term + 1, severity),
    )


def generate_random_curve_scenario(scenario_id: int, rng: np.random.RandomState, term: int,
                                   max_cpr: float = 30.0, max_cdr: float = 10.0, 
                                   severity: float = 0.20) -> TestScenario:
    """Generate a random CPR/CDR scenario with realistic bounds."""
    cpr_base = rng.uniform(2, 15)
    cpr_walk = np.cumsum(rng.normal(0, 0.3, term + 1))
    cpr_curve = np.clip(cpr_base + cpr_walk, 0, max_cpr)
    
    cdr_base = rng.uniform(0.5, 3)
    cdr_walk = np.cumsum(rng.normal(0, 0.1, term + 1))
    cdr_curve = np.clip(cdr_base + cdr_walk, 0, max_cdr)
    
    return TestScenario(
        scenario_id=scenario_id,
        name=f"Random Curve {scenario_id}",
        cpr_curve=cpr_curve,
        cdr_curve=cdr_curve,
        severity_curve=np.full(term + 1, severity),
    )


def get_cpr_scenarios(term: int = 360, seed: int = RANDOM_SEED) -> list[TestScenario]:
    """
    Get 5 CPR-only scenarios (CDR=0).
    
    Mix of constant rates, PSA curves, and random curves.
    """
    rng = get_random_state(seed)
    return [
        generate_constant_cpr_scenario(0, 5.0, term),    # 5% CPR
        generate_constant_cpr_scenario(1, 15.0, term),   # 15% CPR
        generate_psa_scenario(2, 100, term),             # 100% PSA
        generate_psa_scenario(3, 300, term),             # 300% PSA
        generate_random_curve_scenario(4, rng, term, max_cdr=0),  # Random CPR, no CDR
    ]


def get_cdr_scenarios(term: int = 360, seed: int = RANDOM_SEED) -> list[TestScenario]:
    """
    Get 5 CDR-only scenarios (CPR=0).
    
    Mix of constant rates, SDA curves, and random curves.
    """
    rng = get_random_state(seed + 1000)  # Different seed
    return [
        generate_constant_cdr_scenario(0, 1.0, term),    # 1% CDR
        generate_constant_cdr_scenario(1, 5.0, term),    # 5% CDR
        generate_sda_scenario(2, 100, term),             # 100% SDA
        generate_sda_scenario(3, 200, term),             # 200% SDA
        generate_random_curve_scenario(4, rng, term, max_cpr=0),  # Random CDR, no CPR
    ]


# =============================================================================
# Fixture Paths
# =============================================================================

def get_fixtures_dir() -> Path:
    """Get path to fixtures directory."""
    return Path(__file__).parent / "fixtures"


def get_fixture_path(filename: str) -> Path:
    """Get path to a specific fixture file."""
    return get_fixtures_dir() / filename

