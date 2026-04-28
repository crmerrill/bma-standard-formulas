# Fannie Mae REMIC Trust 2006-018 Test Fixture

Public-record test fixture used to exercise the BMA deal runtime against a
real PAC + Z + Support CMO structure.

## Source

Fannie Mae REMIC Trust 2006-018 Prospectus Supplement (Feb 2, 2006).
Publicly available at <https://www.fanniemae.com/syndicated/documents/mbs/remicsupp/2006-018.pdf>.

## What's captured here

- `__init__.py` — pool assumptions, class structure, published WAL decrement
  table by class and PSA speed, and accessor helpers (`load_planned_balance_schedule`,
  `expand_to_monthly_balance_vector`, `planned_balances_to_principal_schedule`).
- `aggregate_group_i_planned_balances.csv` — 339 entries verbatim from the
  prospectus's Schedule 1 Aggregate Group I planned balance vector
  (Feb 2006 settlement → March 2035 paydown).
- `aggregate_group_ii_planned_balances.csv` — 349 entries from the
  Aggregate Group II (PAC/AD) planned balance vector.
- `deal_definition.py` — factory that builds a complete `DealDefinition` IR
  for the Group 1 sub-deal (16 classes plus residual).

## Loading the fixture into the local app workspace

The fixture is exposed to the Structuring Studio UI by running:

```bash
python scripts/seed_fnr_2006_018.py
```

This:

1. Saves the canonical `DealDefinition` to `~/PrismaRisk/BMA-CFEngine/deals/deal_fnr_2006_018/v1.json`.
2. Saves a Studio Snapshot (`studio_v1.json`) so the deal appears in the UI's
   "Open Deal" picker.
3. Pre-seeds portfolio runs at 100, 147, 250, and 500% PSA under stable run
   ids (`run_fnr2006018_psa100`, etc.), each populated with the
   `Base_Case_portfolio_actual.parquet` artifact in the schema the deal's
   collateral bridge expects.
4. Binds the deal's default source to the 100% PSA run.

After running the script, start the app:

```bash
python scripts/run_app.py
```

In the UI:

- Go to **Structuring Studio**.
- Click **Open Deal** and select **FNR 2006-018 Group 1 (PAC + Z + Support)**.
- Click **Run Deal** to execute against the bound 100% PSA portfolio run.
- Open **Structured Deal Analysis** to inspect bond cashflows, waterfall trace,
  trigger state history, decrement table, and stress matrix.

To switch PSA speed inside the UI, change the source run from the dropdown
(the 147%, 250%, and 500% PSA runs are seeded for direct selection).

## Running the parity tests

```bash
pytest tests/test_fnr_2006_018_parity.py -q
```

Tests cover:

- Schedule 1 parsing correctness and monotonicity.
- DealDefinition construction (all 16 classes + residual, schedule contracts
  populated, Z bond configuration).
- Aggregate Group I balance path tracking the published Schedule 1 within
  10% of original face across the 360-period horizon at 100% PSA.
- Cash conservation between pool inflows and bond + residual outflows.
- Class WAL parity at 100% and 250% PSA against the published decrement table
  with a 1.5-year tolerance.

## Known parity limitations

- **Pool projection vs prospectus pricing assumption**: The published Schedule 1
  is derived using Fannie Mae's internal pool projection. Our 100% PSA pool
  projection delivers approximately 145 bps more principal cash than the
  prospectus assumes, which cascades through the Z accrual interaction with
  Aggregate Group II's planned balance and produces noticeable WAL deltas on
  the TB and Z classes (10+ years at 100% PSA). The senior PAC stack
  (PA, PB, PC, PD) ties out within 0.07 years WAL.
- **Support cash split (95.65% / 4.35%)**: The prospectus splits support
  principal between the WA-WG sequential stack and the PO class as a
  percentage allocation. The fixture currently models this as sequential
  WA-WG followed by PO, which approximates but does not exactly reproduce
  the parallel split.
- **Group I "to zero" cleanup rules**: Modeled via `ignore_schedule_cap=True`
  on PAY_PRINCIPAL rules at the end of the priority of payments so PAC bonds
  pay beyond their published planned-balance schedule once supports are
  exhausted.
