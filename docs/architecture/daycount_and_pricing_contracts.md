# Daycount and Pricing Contracts

This document defines the **implemented** API contracts for the newly added daycount and price/yield table utilities.

Scope:

- `src/bma_standard_formulas/formulas/daycount.py`
- `src/bma_standard_formulas/formulas/pricing_risk.py`
- `src/bma_standard_formulas/engine/pricing.py`

---

## Why This Exists

Sections E/F/G rely on small helper rules (date increments, day fractions, settlement-time mapping) that can quietly break downstream pricing if assumptions are unclear. This document makes those assumptions explicit.

---

## Daycount API Contract

Primary public entry points:

- `year_fraction(start_date, end_date, convention)`
- `day_count_30_360(start_date, end_date, convention)`
- `increment_date(start_date, periods, increment_type, weekday_only)`
- `build_date_range_vector(start_date, periods, increment_type, weekday_only)`

Supported day-fraction `method` values:

- `"30/360 NASD"`
- `"30/360 ISDA"`
- `"30/360 FNMA"`
- `"act/360"`
- `"act/365"`
- `"act/act"` (ISDA flavor)

Input handling:

- Scalar date-like input returns scalar output.
- Array-like input returns NumPy array output.
- String dates are parsed with pandas timestamp parsing.
- For `day_count_30_360` and `year_fraction_*`, date ordering is **signed**:
  - `end_date >= start_date` -> non-negative result
  - `end_date < start_date` -> negative result
  This preserves interoperability with common analytics tool behavior while
  still applying BMA Section E.1 adjustment logic.

Error behavior:

- Invalid method names raise `ValueError`.
- Length mismatch for vector pair inputs raises `ValueError`.
- Invalid month values in month/day helpers follow assert-based checks in the
  direct cmutils port implementation.

Convention details:

- `"30/360 NASD"` applies BMA-style Section E.1 start-date adjustment rules:
  - start date end-of-February -> start day set to 30
  - start day 31 -> start day set to 30
  - if adjusted start day is 30 and end day is 31 -> end day set to 30
- `"30/360 ISDA"` applies 31st-day adjustments without end-of-February rules.
- `"act/act"` implements ISDA-style split-year computation:
  - days in leap years / 366 + days in non-leap years / 365
  - interval convention is `[start_date, end_date)` (start included, end excluded)

---

## Pricing Table API Contract

Primary pricing/risk API:

- `PriceRiskAnalyzer(scenarios, ...)`
- `PriceRiskAnalyzer.price_yield_table(column_inputs, input_kind)`
- `PriceRiskAnalyzer.risk_metrics(annual_yield_pct)`
- `PriceRiskAnalyzer.expanded_price_yield_table(column_inputs, input_kind)`

Engine wrapper:

- `build_price_yield_table(...)`
- `build_expanded_price_yield_table(...)`

Result dataclasses:

- `PriceYieldScenarioTable`
- `PriceYieldRiskTable`
- `RiskMetrics`

### Units and Quotes

- Input/Output **yield** values are annualized percent values (e.g., `6.25` means 6.25%).
- Input/Output **price** values are quoted per `face_value` (default `100`).
- Scenario cashflow vectors are normalized to quote basis using scenario notional before solving.

### Scenario Object Support

Each scenario value can be:

- `BMAScheduledCashflow`
- `BMAActualCashflow`
- `PortfolioCashflow`

Cashflow extraction policy:

- Scheduled leaf: `principal_paid + interest_paid`
- Actual leaf: `act_am + vol_prepay + prin_recov + act_int`
- Portfolio scheduled mode: scheduled principal+interest
- Portfolio actual/paired modes: trust-level `pt_cashflow`

### Period-Time Mapping

Time vector is built from each cashflow object's **existing period array**
(no synthetic index creation):

- `t_i = (i * month_days + delay_days) / 360`

Defaults:

- `month_days = 30.0`
- `delay_days = 0`
- `include_period_zero = False`

### Numerical Solver Behavior

Yield-from-price uses Brent root solve (`scipy.optimize.brentq`) with default bracket:

- lower = `-99.0%`
- upper = `250.0%`

If residual does not change sign across bracket, function raises `ValueError`.

### Risk Metrics

Implemented deterministic-path metrics:

- Macaulay duration (`macaulay_duration_years`)
- Modified duration (`modified_duration_years`)
- Convexity (`convexity_years2`)

Engine wrapper:

- `compute_risk_metrics(cashflow, annual_yield_pct, ...)`

---

## Known Limitations

- Daycount business-day logic currently assumes weekend-only calendars (no holiday calendars).
- Actual loan-level investable cashflow uses a proxy because trust waterfall allocation is portfolio-level.
- Price/yield calculations assume deterministic cashflow path per scenario row.

---

## Minimal Usage

```python
import numpy as np
from bma_standard_formulas.engine import build_price_yield_table

table = build_price_yield_table(
    scenarios={"base": portfolio_cashflow_obj},
    column_inputs=np.array([95.0, 100.0, 105.0]),
    input_kind="price",
)

df = table.to_dataframe()
print(df)
```
