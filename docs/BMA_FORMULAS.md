# BMA Standard Formulas - Complete Reference

**Version**: 1.1.0
**Last Updated**: 2026-01-05
**Status**: Active
**Source**: BMA "Uniform Practices/Standard Formulas" (02/01/99)

---

## Table of Contents

- [A. Computational Accuracy](#a-computational-accuracy)
- [B. Prepayments](#b-prepayments)
  - [B.1. Cash Flows](#b1-cash-flows)
  - [B.2. Mortgage Prepayment Models](#b2-mortgage-prepayment-models)
  - [B.3. Average Prepayment Rates](#b3-average-prepayment-rates-for-mortgage-pools)
  - [B.4. ABS Prepayment Rates](#b4-abs-prepayment-rates-for-asset-pools)
- [C. Defaults](#c-defaults)
  - [C.1. Basic Concepts](#c1-mortgage-cash-flows-with-defaults-basic-concepts)
  - [C.2. Default Standards and Definitions](#c2-specifying-mortgage-default-assumptions)
  - [C.3. Standard Formulas for Defaults](#c3-standard-formulas-for-computing-mortgage-cash-flows-with-defaults)
  - [C.4. SDA (Standard Default Assumption)](#c4-the-standard-default-assumption-sda)
- [D. Assumptions for Generic Pools](#d-assumptions-for-generic-pools)
- [E. Day Counts](#e-day-counts)
- [F. Settlement-Based Calculations](#f-settlement-based-calculations)
- [F.2 CMO Bonds with Unknown Settlement Factors](#f2-cmo-bonds-with-unknown-settlement-factors)
- [F.3 Freddie Mac Multiclass PCs (REMICs)](#f3-freddie-mac-multiclass-pcs-remics)
- [G. Yield and Yield-Related Measures](#g-yield-and-yield-related-measures)
- [G.2 Calculations for Floating-Rate MBS](#g2-calculations-for-floating-rate-mbs)
- [G.3 Putable Project Loans](#g3-putable-project-loans)
- [H. Accrual Instruments](#h-accrual-instruments)

---

## A. Computational Accuracy

**Reference: SF-3**

All intermediate calculations should preserve **at least ten significant digits of accuracy**. This generally requires double-precision computer arithmetic.

**Rules:**
- Only quantities representing whole numbers of days, months, or years should use integer variables
- Final values should be rounded for display (not truncated)
- Numerical examples in the document are simple checks, not exhaustive benchmarks

---

## B. Prepayments

### B.1. Cash Flows

**Reference: SF-4**

#### Amortized Loan Balance (BAL)

For a level-payment fixed-rate mortgage pool:

```
BAL = [1 - (1 + C/1200)^(-M)] / [1 - (1 + C/1200)^(-M0)]
```

Where:
- `C` = gross weighted-average coupon (%)
- `M` = current weighted-average remaining term (months)
- `M0` = original term (months)
- BAL is expressed as a fraction of par

#### Gross Mortgage Payment

```
GROSS MORTGAGE PAYMENT = PRINCIPAL + INTEREST
                       = (BAL1 - BAL2) + (BAL1 * C/1200)
                       = (C/1200) / [1 - (1 + C/1200)^(-M0)]
```

Where:
- `BAL1` = balance at beginning of period
- `BAL2` = balance at end of period

#### Net Payment to Investors

```
NET PAYMENT = GROSS PAYMENT + UNSCHEDULED PREPAYMENTS - SERVICING FEE
SERVICING FEE = BAL1 * S/1200
```

Where:
- `S` = servicing percentage = gross coupon - net pass-through coupon

#### Pool Factor and Survival Factor

```
POOL FACTOR (F) = principal remaining / original face amount
SURVIVAL FACTOR = F / BAL
POOL FACTOR = SURVIVAL FACTOR * AMORTIZED LOAN BALANCE
```

#### Cash Flow Components

```
(1) Scheduled Amortization = BAL1 - BAL2
(2) Unscheduled Prepayments
(3) Gross Mortgage Interest = BAL1 * C/1200
(4) Servicing Fee = BAL1 * S/1200

Pass-Through Principal = (1) + (2)
Pass-Through Interest = (3) - (4)
Pass-Through Cash Flow = (1) + (2) + (3) - (4)
```

#### Example (SF-4)

9.0% net coupon, 9.5% gross coupon, 360 months, first month prepayments = 0.00025022:

| Component | Value |
|-----------|-------|
| Scheduled Amortization | 0.00049188 |
| Unscheduled Prepayments | 0.00025022 |
| Gross Mortgage Interest | 0.00791667 |
| Servicing Fee | 0.00041667 |
| Pass-Through Principal | 0.00074210 |
| Pass-Through Interest | 0.00750000 |
| Pass-Through Cash Flow | 0.00824210 |

---

### B.2. Mortgage Prepayment Models

**Reference: SF-5 to SF-10**

#### a. SMM (Single Monthly Mortality)

```
F2 = F1 * (BAL2/BAL1) * (1 - SMM/100)
```

Where:
- `F1`, `F2` = pool factors at beginning and end of month
- `BAL1`, `BAL2` = amortized loan balances

Alternative definition:

```
Fsched = F1 * (BAL2/BAL1)
SMM = 100 * (Fsched - F2) / Fsched
```

Where:
- `F1 - Fsched` = amortization for the month
- `Fsched - F2` = early prepayment of principal

#### b. CPR (Conditional Prepayment Rate)

```
(1 - SMM/100)^12 = 1 - CPR/100
```

Rearranged:

```
CPR = 100 * [1 - (1 - SMM/100)^12]
SMM = 100 * [1 - (1 - CPR/100)^(1/12)]
```

#### c. PSA (Prepayment Speed Assumptions)

100% PSA:
- Months 1-29: CPR increases by 0.2% each month (from 0.2% to 5.8%)
- Months 30+: CPR = 6.0%

**Formula:**

```
CPR = min{(PSA/100) * 0.2 * max{1, min{MONTH, 30}}, 100}
```

Where:
- `MONTH` = accrual period during which loan age increases from MONTH-1 to MONTH
- `PSA` = PSA speed as percentage (100 = baseline)

**AGE vs MONTH:**
- `AGE` = point in time (loan originated at AGE=0, after MONTH=1, AGE=1)
- `MONTH` = span of time
- Pool factors are reported as of an AGE; prepayment rates are reported for a MONTH

**PSA from CPR (for seasoned loans, MONTH ≥ 30):**

```
PSA = 100 * CPR / 6.0
```

#### Example (SF-7 to SF-8)

Ginnie Mae I 9.0% pass-through, remaining term 359 months:
- F1 = 0.85150625 (6/1/89)
- F2 = 0.84732282 (7/1/89)
- Gross coupon = 9.5%

Calculation:
```
BAL1 = [1 - (1 + 9.5/1200)^(-344)] / [1 - (1 + 9.5/1200)^(-359)] = 0.99213300
BAL2 = [1 - (1 + 9.5/1200)^(-343)] / [1 - (1 + 9.5/1200)^(-359)] = 0.99157471
Fsched = F1 * (BAL2/BAL1) = 0.85102709

Amortization = F1 - Fsched = 0.00047916
Prepayments = Fsched - F2 = 0.00370427
SMM = 100 * 0.00370427 / 0.85102709 = 0.435270%
CPR = 100 * [1 - (1 - 0.00435270)^12] = 5.1000%

MONTH = 17 (6/89 relative to 2/88 origination)
PSA = 100 * 5.1 / min{0.2*17, 6.0} = 100 * 5.1 / 3.4 = 150.00%
```

---

### B.3. Average Prepayment Rates for Mortgage Pools

**Reference: SF-11 to SF-12**

Standards:
- Pools not present at the start of the period are excluded; pools with bad/missing start or end factors are excluded.
- Iteration is required for PSA speeds; do **not** average individual PSA speeds or substitute a single aggregate pool. Nonstandard approximations must be labeled as such.
- For structured cash flows (e.g., CMO classes/strips), average speeds are not meaningful unless reported per class (or as a range).

#### Average SMM

```
SMM_avg = 100 * [1 - (FINAL_AGGREG_BAL_actual / FINAL_AGGREG_BAL_sched)^(1/months_in_period)]
```

#### Average CPR

```
CPR_avg = 100 * [1 - (FINAL_AGGREG_BAL_actual / FINAL_AGGREG_BAL_sched)^(12/months_in_period)]
```

#### Average PSA (for fully seasoned mortgages only)

```
PSA_avg = 100 * CPR_avg / 6.0
```

---

### B.4. ABS Prepayment Rates for Asset Pools

**Reference: SF-13 to SF-15**

The ABS model defines an increasing sequence of monthly prepayment rates (SMM) corresponding to a **constant absolute level** of loan prepayments in all future periods.

#### ABS to SMM Conversion

```
SMM = (100 * ABS) / [100 - ABS * (MONTH - 1)]
```

Where:
- `ABS` = ABS speed (%)
- `MONTH` = months after origination

**Note:** For a pool of new loans, X% ABS = prepayment each month of X% of loans **originally** in the pool.

#### Historical ABS Speed

For any time interval where loan age, pool factor, and amortized loan balance changed from AGE1, F1, BAL1 to AGE2, F2, BAL2:

```
ABS = 100 * [(F2/F1) - (BAL2/BAL1)] / [AGE1*(F2/F1) - AGE2*(BAL2/BAL1)]
```

#### Example (SF-14)

36-month car loans, WAM 34 months, 2% ABS for month 11:

```
SMM = (100 * 2) / [100 - 2 * (11 - 1)] = 200 / 80 = 2.5000%
```

#### ABS to SMM Conversion Table (Selected Values)

| Month | 0.50 ABS | 1.00 ABS | 1.50 ABS | 2.00 ABS |
|-------|----------|----------|----------|----------|
| 1 | 0.50 | 1.00 | 1.50 | 2.00 |
| 10 | 0.52 | 1.10 | 1.73 | 2.44 |
| 20 | 0.55 | 1.23 | 2.10 | 3.23 |
| 30 | 0.58 | 1.41 | 2.65 | 4.76 |
| 40 | 0.62 | 1.64 | 3.61 | 9.09 |
| 50 | 0.66 | 1.96 | 5.66 | 100.00 |

One-month PSA→SMM conversion by mortgage age is provided in SF-9/10 (select PSA column and age row; table not reproduced in full here).

---

## C. Defaults

### C.1. Mortgage Cash Flows with Defaults: Basic Concepts

**Reference: SF-16**

**Key Definitions:**

- **Default**: A loan that no longer pays principal and interest and remains delinquent until liquidated (cured delinquencies are NOT included)
- **New Defaults**: Loans that first go into default in a given month
- **Performing Balance**: Total balance of loans making full monthly payments through prior month
- **Loans in Foreclosure (FCL)**: Defaulted loans not yet liquidated
- **Expected Amortization**: Amortized principal expected from all existing loans (including FCL)
- **Amortization from Defaults**: Principal not received due to defaults
- **Actual Amortization**: Principal actually received from borrowers
- **Expected Interest**: Interest due on all existing loans (including FCL)
- **Interest Lost**: Interest not received due to defaults
- **Actual Interest**: Expected Interest minus Interest Lost
- **Servicer Advances**: If P&I are advanced, investors receive all Expected Amortization and Expected Interest regardless of defaults
- **Months to Liquidation**: Time from first missed payment to liquidation
- **Loss Severity**: Loss amount / principal balance at time of default

---

### C.2. Specifying Mortgage Default Assumptions

**Reference: SF-17**

**Standards and Definitions:**

a. Default analysis models defaults only, not delinquencies
b. Default rates specified separately from loss rates (severities)
c. Default rate = percentage of aggregate performing balance at end of prior month, **before** current month's scheduled amortization
d. Prepayment rates and default rates specified separately
e. Prepayment rate = percentage of aggregate performing balance at end of prior month, **after** removing current month's scheduled amortization
f. Required assumptions:
   - Time to Liquidation
   - Loss Severity or Loss Severity curve
   - Whether P&I are advanced
g. Loss Severity applied to loan balance at time of default
h. Higher prepayment → lower cumulative defaults (at same default rate)
i. Default rate is set to **0 for the final `n` months** where `n = Time to Liquidation`

**Constraint:**
```
Actual Amortization + New Defaults + Voluntary Prepayments ≤ prior period's Performing Balance
```

---

### C.3. Standard Formulas for Computing Mortgage Cash Flows with Defaults

**Reference: SF-18 to SF-19**

#### Variable Definitions

| Variable | Description | Formula |
|----------|-------------|---------|
| `PERF BAL(i)` | Performing Balance in month i | `PERF BAL(i-1) - NEW DEF(i) - VOL PREPAY(i) - ACT AM(i)` |
| `NEW DEF(i)` | New Defaults | `PERF BAL(i-1) * MDR(i)` |
| `FCL(i)` | Loans in Foreclosure | `(NEW DEF(i) + FCL(i-1) - ADB(i)) - AM DEF(i)` |
| `SCH AM(i)` | Scheduled Balance (no prepayments) | Amortization schedule |
| `EXP AM(i)` | Expected Amortization | `(PERF BAL(i-1) + FCL(i-1) - ADB(i)) * [1 - SCH AM(i)/SCH AM(i-1)]` |
| `VOL PREPAY(i)` | Voluntary Prepayments | `PERF BAL(i-1) * [SCH AM(i)/SCH AM(i-1)] * SMM(i)` |
| `AM DEF(i)` | Amortization from Defaults | See below |
| `ACT AM(i)` | Actual Amortization | `(PERF BAL(i-1) - NEW DEF(i)) * [1 - SCH AM(i)/SCH AM(i-1)]` |
| `EXP INT(i)` | Expected Interest | `(PERF BAL(i-1) + FCL(i-1)) * Net Mortgage Rate` |
| `LOST INT(i)` | Interest Lost | `(NEW DEF(i) + FCL(i-1)) * Net Mortgage Rate` |
| `ACT INT(i)` | Actual Interest | `EXP INT(i) - LOST INT(i)` |
| `PRIN RECOV(i)` | Principal Recovery | `MAX[ADB(i) - PRIN LOSS(i), 0]` |
| `PRIN LOSS(i)` | Principal Loss | `MIN[NEW DEF(i - lag) * Severity Rate, ADB(i)]` (capped by ADB when advances) |
| `ADB(i)` | Amortized Default Balance | See below |
| `MDR(i)` | Monthly Default Rate | Input |
| `SMM(i)` | Monthly Prepayment Rate | Input |

**Notes on FCL(i):**
Loans in Foreclosure do not include any loans that are liquidated in the current month. `ADB(i)` represents the balance removed from `FCL(i)` via liquidation.

#### Amortization from Defaults (AM DEF)

If P&I are advanced:
```
AM DEF(i) = (NEW DEF(i) + FCL(i-1) - ADB(i)) * [1 - SCH AM(i)/SCH AM(i-1)]
```

If P&I are NOT advanced:
```
AM DEF(i) = 0
```

#### Amortized Default Balance (ADB)

If P&I are advanced:
```
ADB(i) = NEW DEF(i - months_until_recovery) * [SCH AM(i-1) / SCH AM(i-1-months_until_recovery)]
```

If P&I are NOT advanced:
```
ADB(i) = NEW DEF(i - months_until_recovery) * 1
```

#### Clarification Notes (SF-19)

a. NEW DEF = MDR × prior period's Performing Balance
b. VOL PREPAY = SMM × (prior period's Performing Balance after scheduled amortization)
c. **Constraint**: ACT AM + NEW DEF + VOL PREPAY cannot exceed prior period's Performing Balance
d. EXP AM computed from sum of prior period's PERF BAL and FCL
e. FCL does not include loans liquidated in current month
f. EXP AM and AM DEF not computed for loans in their liquidation month
g. ACT AM based on (prior period's PERF BAL - NEW DEF)
h. Maximum PRIN RECOV = ADB in liquidation month (if P&I advanced)
i. Maximum PRIN LOSS = ADB in liquidation month (if P&I advanced)
j. **Default rate set to 0 for last n months** where n = Time to Liquidation
k. Produce cumulative default and loss matrices over the prepayment/default grids used (per SDA examples).

---

### C.4. The Standard Default Assumption (SDA)

**Reference: SF-20 to SF-22**

100% SDA characteristics:

| Months | Annual Default Rate | Description |
|--------|---------------------|-------------|
| 1-30 | 0.02% × month | Rise from 0 to peak |
| 30-60 | 0.60% | Constant at peak |
| 61-120 | 0.60% - 0.0095% × (month-60) | Decline from peak to tail |
| 121+ | 0.03% | Constant at tail |
| Last n months | 0% | n = Time to Liquidation |

Applicability: designed for fully amortizing residential mortgages with term ≥ 15 years; **not** intended for balloons, commercial mortgages, home equity loans, auto loans, or credit card receivables. The final `n` months (liquidation lag) are forced to 0 default rate.

#### SDA Mathematical Definition (100% SDA)

For Month (m):
- 1 ≤ m ≤ 30:  Annual CDR = 0.02% * m (Rise from 0 to 0.60%)
- 30 < m ≤ 60: Annual CDR = 0.60% (Constant at peak)
- 60 < m ≤ 120: Annual CDR = 0.60% - [0.0095% * (m - 60)] (Decline to tail)
- m > 120:     Annual CDR = 0.03% (Constant at tail)

**Constraint**: For m > (Total Term - n), Annual CDR = 0 (where n = Months to Liquidation).

#### CDR to MDR Conversion

```
MDR = 100 * [1 - (1 - Annual_Default_Rate/100)^(1/12)]
```

(Same formula as CPR to SMM)

#### Cumulative Default Matrix (Example: 8% WAC, 30-year)

| %PSA / %SDA | 50 | 100 | 150 | 200 | 250 | 300 |
|-------------|------|------|------|------|------|------|
| 100 | 1.56 | 3.09 | 4.59 | 6.08 | 7.53 | 8.97 |
| 150 | 1.40 | 2.78 | 4.13 | 5.47 | 6.79 | 8.08 |
| 200 | 1.26 | 2.51 | 3.74 | 4.95 | 6.14 | 7.32 |
| 300 | 1.05 | 2.08 | 3.10 | 4.11 | 5.10 | 6.08 |

#### SDA Usage Notes

- Designed for fully amortizing residential mortgages with term ≥ 15 years
- NOT intended for: balloon mortgages, commercial mortgages, home equity loans, auto loans, credit card receivables

---

## D. Assumptions for Generic Pools

**Reference: SF-39 to SF-43**

### D.1. Mortgage Maturity (WAM)

- Use most recent WAM from issuer/guarantor; adjust by months since its as-of date.
- If no WAM, use remaining term to final maturity.
- If WAM > time to final maturity: `WAM = MIN(updated WAM, time to maturity)`.
- Ginnie Mae WAM is quarterly and lagged: Jan/Apr/Jul/Oct releases refer to Sep/Dec/Mar/Jun respectively for pools issued before the third month prior; decrement WAM by elapsed months since that as-of date (4/3/2/1 depending on issue month).
- Fannie/Freddie WAM updates are monthly/current; for same-month concentration >50%, original WAM may be reported one month longer, but first amortization uses reported WAM.

### D.2. Mortgage Age (WALA)

- Use most recent WALA; adjust by months since as-of date (add elapsed months).
- Ginnie Mae WALA shares the same quarterly lag; add 4/3/2/1 months to align with current factor depending on pool issue timing.
- If WALA not available, use CAGE (Calculated Loan Age):

```
CAGE = Original_Maturity - Original_WAM + months_elapsed_since_pool_formation
```

Constraint: `CAGE = MIN(CAGE, Original_Maturity - Current_WAM)`
- Same-month concentration >50% pools: set CAGE = 0 for first two months (then increment).
- If WAM + WALA exceed term (e.g., >360 for 30-year), set age = `360 - WAM` (or `180 - WAM` for 15-year).
- If original WAM unavailable, estimate age as original maturity − remaining WAM; if remaining WAM unavailable, use original maturity − time to maturity.

### D.3. Mortgage Coupon (WAC)

If WAC not released, assume fixed servicing spread:

| Agency | Spread |
|--------|--------|
| Ginnie Mae I | +50 bp |
| Ginnie Mae II | +75 bp |
| Fannie Mae | +65 bp |
| Freddie Mac | +65 bp |

---

## E. Day Counts

**Reference: SF-44**

### E.1. Calendar Basis (30/360)

Number of days from M1/D1/Y1 to M2/D2/Y2:

```
If M1=2 and D1=28 (non-leap) or 29 (leap): set D1=30
If D1=31: set D1=30
If D1=30 and D2=31: set D2=30

N = max{360*(Y2-Y1) + 30*(M2-M1) + (D2-D1), 0}
```

### E.2. Delay Days

```
Actual Delay = Payment_Date_to_Investors - Payment_Date_from_Homeowners
```

| Pass-Through Type | First Payment to Investors | Actual Delay | Stated Delay |
|-------------------|---------------------------|--------------|--------------|
| Ginnie Mae I | April 15 | 14 days | 45 days |
| Ginnie Mae II | April 20 | 19 days | 50 days |
| Fannie Mae | April 25 | 24 days | 55 days |
| Freddie Mac NONGOLD | May 15 | 44 days | 75 days |
| Freddie Mac GOLD | April 15 | 14 days | 45 days |

---

## F. Settlement-Based Calculations

**Reference: SF-45 to SF-47**

### F.1. General Rules

#### Settlement Amount (Cost)

```
COST = PRINCIPAL AMOUNT + ACCRUED INTEREST
```

#### Principal Amount

```
PRINCIPAL AMOUNT = FACE * (PRICE/100) * F
```

Where:
- `FACE` = original face amount
- `PRICE` = price as percentage of current face
- `F` = current factor (at start of payment period)

#### Accrued Interest

```
ACCRUED INTEREST = FACE * F * (COUPON/100) * (N/360)
```

Where:
- `COUPON` = annual coupon rate (%)
- `N` = days from first day of accrual period to settlement (30/360 basis)

Settlement standards:
- Quotes assume the actual settlement date; if quoted within two business days of the standard settlement date for the month, assume settlement is the earlier of (standard + 2 business days) or the last business day of the month.
- CMOs and ABS follow corporate settlement rules.
- `N` is measured from the factor as-of date for `F`.

#### Assumed Settlement Date Rule
For quotations made within two business days of the standard settlement date for the delivery month:
```
Assumed Settlement = MIN(Quote Date + 2 Business Days, Last Business Day of Month)
```

### F.2. CMO Bonds with Unknown Settlement Factors

- If the current factor is not yet available, use the most recently published factor `F0` in the settlement formulas and true-up when the current factor is released.
- Accrual bonds in an accretion period are excluded from this shortcut; instead use an estimated factor:

```
Fest = F0 * (1 + (COUPON/100) * (N0/360))
```

where `N0` is days (30/360) from the as-of date of `F0` to the as-of date of the current factor.

### F.3. Freddie Mac Multiclass PCs (REMICs)

- Record dates are mid-month; tranche factors update at month start.
- **Fixed-rate classes**: principal and accrued interest use the factor as of the last Record Date before settlement; accrued interest covers days from the day after that Record Date to settlement.
- **Variable-rate classes**: principal uses the factor as of the last Record Date before settlement; accrued interest uses the factor as of the second prior Record Date because the accrual period follows the Record Date. Deduct from cost the accrued interest from settlement to the day after the first Record Date on/after settlement at the coupon in effect on settlement date.
- **Constraint for Fixed-Rate REMIC Accrued Interest**: If Settlement Date is the day after the Record Date (e.g., Feb 15 for a Feb 14 Record Date), Accrued Interest = 0.
- Example formulas (FACE original face; COUPON annual rate):
  - Fixed: `Principal = [F(2/1) - F(3/1)] * FACE`; `Interest = F(2/1) * FACE * COUPON/1200`
  - Variable: `Principal = [F(1/1) - F(2/1)] * FACE`; `Interest = F(1/1) * FACE * COUPON(2/15)/1200`

---

## G. Yield and Yield-Related Measures

**Reference: SF-48 to SF-55**

All calculations use **semiannual-compounding basis**.

### G.1. General Yield Rules

#### a. Bond-Equivalent Yield (Y)

```
P = CF1/(1 + Y/200)^(2*T1) + CF2/(1 + Y/200)^(2*T2) + ...
```

Where:
- `P` = dollar price (including accrued interest)
- `CFk` = cash flow at time Tk after settlement
- `Tk` = time in years (30/360 basis, including actual delay)

#### b. Mortgage Yield (Monthly Yield)

```
Mortgage Yield = 1200 * [(1 + Y/200)^(1/6) - 1]
```

#### c. Average Life

```
Average Life = (T1*PR1 + T2*PR2 + ...) / (PR1 + PR2 + ...)
```

Where `PRk` = principal payment at time Tk

#### d. Macaulay Duration

```
Duration = (1/P) * [T1*CF1/(1+Y/200)^(2*T1) + T2*CF2/(1+Y/200)^(2*T2) + ...]
```

#### e. Modified Duration

```
Modified Duration = Duration / (1 + Y/200)
```

#### f. Cash-Flow Convexity

```
Convexity = (1/P) * (1/(1+Y/200)^2) * [T1*(T1+0.5)*CF1/(1+Y/200)^(2*T1) + ...]
```

#### g. Price/Yield Approximation

```
P ≈ P0 * [1 - ModDur*(Y-Y0)/100 + 0.5*Conv*((Y-Y0)/100)^2]
```

#### h. Total Rate of Return

```
Bond-Equivalent Total Rate of Return = 200 * [(PT/P0)^(1/(2*T)) - 1]
Total Percentage Return = 100 * [(PT/P0) - 1]
```

**Terminal Value (PT) at end of holding period T:**
```
PT = (Sale Price * Pool Factor) + Σ [CFk * (1 + R/200)^(2 * (T - Tk))]
```
Where:
- `R` = assumed bond-equivalent reinvestment rate (%)
- `Tk` = time from settlement to receipt of cash flow `CFk`
- Only `CFk` received during the holding period are included
- `CFk` received on a delayed basis after the end of the holding period are discounted back to the end of the holding period (T) using `R`

#### Worked Example (GNMA I 9.0%, 150% PSA, 14-day actual delay)

- Price at issue: 100.0000
- Yield 9.10675%; Mortgage Yield 8.93863%
- Average Life 9.77844y; Duration 5.73147y; Modified Duration 5.48186y; Cash-Flow Convexity 0.544326 (years²)
- Effective metrics from ±10 bp prices (99.453 / 100.541): Effective Duration ≈ 5.44y; Effective Convexity ≈ -0.600
- Reinvestment example (R = 8% for first three cash flows): PT = 102.2502 → Bond-Equivalent Total Return 9.102%, Total Percentage Return 2.250%
- Settlement 7 days after issue: price 100.1750, yield 9.10644%

### G.2. Calculations for Floating-Rate MBS

- YTM Spread = floater yield − index yield, both on the same calendar basis (30/360 BEY or ACT/360 MMY) and compounding convention.
- Discounted Margin (DM) solves:

```
P = Σ CFk / Π_{j=1..k} [1 + (Ij + DM)/100 * (Tj - Tj-1)]
```

with Tk in years on the cash-flow calendar basis (no semiannual gross-up inside the product).
- Common index conventions: LIBOR <1y ACT/360; LIBOR ≥1y ACT/ACT; T-Bills ACT/360; CMT ≥1y 30/360; 11th District COFI ACT/ACT.
- Example (FRCMO, price 99): BEY basis Yield 10.96675%, index 10.46235% → YTM spread 50.44 bp; DM 62.05 bp. MMY basis Yield 10.76838%, index 10.31723% → spread 45.11 bp; DM 56.89 bp.

### G.3. Putable Project Loans

- Standard assumption: put price 96 (≈ 60 bp above 10-year Treasury) unless specified.
- Put window: one year starting the month after 20 years from final endorsement; put date must be explicit.
- Debentures valued as of the put date (no delay adjustment).
- Example (Gross 7.50%, Net 7.43%, 40y, 24-day delay, orig 2/1/79, put 6/1/99): Yield to Put 9.77078%; Average Life to Put 9.72452y; value = 96% of 6/99 balance + full 5/99 cash flow.

---

## H. Accrual Instruments

**Reference: SF-56 to SF-57**

### H.1. Average Life of Accrual Instruments

For CMO Z-bonds, GPMs, or capped ARMs:
- Interest accrued but not paid is treated as **negative principal payment**
- Different conventions for pass-throughs vs CMOs:

**GPM/ARM Convention:**
- Include all principal payments (positive and negative) in average life calculation
- Formula: `AL = Σ (Tk * PRk) / Σ PRk`
- Denominator = principal balance at settlement

**Z-bond Convention:**
- Include only positive principal payments
- Formula: `AL = Σ (Tk * max(0, PRk)) / Σ max(0, PRk)`
- Denominator generally larger than principal balance at settlement

### H.2. Accrual Settlement Note

Special settlement conventions for accrual bonds were discontinued for trades on/after 7/15/1991 (settling on/after 10/01/1991); use standard settlement rules (Sections F.1–F.2).

---

## Numerical Examples from Document

### Cash Flow A (SF-23 to SF-30)

**Parameters:**
- WAC: 8.00%
- WAM: 360 months
- Original Balance: 100,000,000
- Prepay Rate: 1% SMM
- Default Rate: 1% MDR
- Recovery Lag: 12 months
- Loss Severity: 20%
- P&I Advanced: Yes

### Cash Flow B (SF-31 to SF-38)

**Parameters:**
- WAC: 8.00%
- WAM: 360 months
- Original Balance: 100,000,000
- Prepay Rate: 150% PSA
- Default Rate: 100% SDA
- Recovery Lag: 12 months
- Loss Severity: 20%
- P&I Advanced: Yes

---

## Key Terminology Summary

| BMA Term | Description |
|----------|-------------|
| `BAL` | Amortized Loan Balance (fraction of par) |
| `F` | Pool Factor (principal remaining / original face) |
| `SURVIVAL FACTOR` | F/BAL (fraction of original $1 loans remaining) |
| `SMM` | Single Monthly Mortality (monthly prepay rate) |
| `CPR` | Conditional Prepayment Rate (annual prepay rate) |
| `PSA` | Prepayment Speed Assumption (% of standard curve) |
| `ABS` | Absolute prepayment speed (constant absolute prepayments) |
| `MDR` | Monthly Default Rate |
| `CDR` | Constant Default Rate (annual) |
| `SDA` | Standard Default Assumption (% of standard curve) |
| `PERF BAL` | Performing Balance |
| `FCL` | Foreclosure (loans in foreclosure pipeline) |
| `SCH AM` | Scheduled Amortization Schedule (scheduled balance) |
| `EXP AM` | Expected Amortization |
| `ACT AM` | Actual Amortization |
| `VOL PREPAY` | Voluntary Prepayments |
| `AM DEF` | Amortization from Defaults |
| `EXP INT` | Expected Interest |
| `LOST INT` | Interest Lost |
| `ACT INT` | Actual Interest |
| `ADB` | Amortized Default Balance (in recovery) |
| `PRIN RECOV` | Principal Recovery |
| `PRIN LOSS` | Principal Loss |

