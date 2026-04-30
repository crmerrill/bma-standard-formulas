# Waterfall IR Design — research notes (work in progress)

**Status:** Initial findings from prospectus deep reads across RMBS
and auto ABS. Not a final spec yet. Below documents what real
prospectus language looks like and where the current IR matches or
diverges from it.

**Sample size (8 deals + FNR 2006-018 fixture):**

| Asset class | Deal | Key features |
|---|---|---|
| Agency MBS REMIC | FNR 2006-018 | 2 collateral groups, PAC + Z + Support, face-weighted support split |
| Agency MBS REMIC | FNR 2016-104 | 9 collateral groups, mix of pass-through, sequential, accretion-directed, PAC, face-weighted splits |
| Agency MBS REMIC | FNR 2019-17 | 7 collateral groups, **nested face-weighted splits**, **named Aggregate Group** abstraction |
| Agency Multifamily REMIC | FNMA 2024-M2 | Multifamily REMIC; structurally similar to single-family agency REMICs, fewer classes |
| Agency Synthetic CRT | CAS 2024-R05, CAS 2024-R06 | Connecticut Avenue Securities — **synthetic risk transfer**, not cash-flow backed; loss reference structure. **Different category** from cash flow waterfalls and out of scope for this IR. |
| Non-Agency RMBS (subprime) | JPMMT 2006 | Single pool, **interest waterfall + principal waterfall** sub-streams, **stepdown date**, **trigger event override**, OC + excess interest, M-1..M-10 mezz with reverse-seniority loss allocation |
| Prime Auto ABS | Ford Credit Auto Owner Trust 2024-C | Single pool, **interleaved interest + principal**, **first / second / regular priority principal** with computed amounts, target OC build, reserve replenishment as a step |
| Subprime Auto ABS | Santander Drive Auto Receivables Trust 2024-2 | **Same waterfall shape as Ford Credit prime auto.** Differences are parametric (4 mezz classes vs 3, 5 named principal allocations vs 3, $300K trustee fee cap vs $375K). Confirms auto prime + subprime share one IR grammar. |

This is short of "10-15 per asset class" but already surfaces
distinct structural requirements. The user has noted that more
breadth (credit card master trusts, CLOs, marketplace consumer,
equipment / aircraft, solar) will refine and extend these findings.
**Plan: surface the patterns from this sample, agree on direction,
then expand.**

**Key cross-asset finding:** **prime auto and subprime auto are
the same waterfall grammar.** All asset classes ultimately reduce
to a small set of structural primitives — see "Cross-asset-class
observations" below.

---

## Methodology

For each deal: locate the "Distributions" / "Priority of Payments"
section verbatim, categorize each numbered step in the prospectus,
and note what abstractions the prospectus implicitly assumes (named
amounts, computed amounts, named groups).

---

## RMBS — Agency MBS REMIC

### FNR 2006-018 (existing fixture, anchor)

Two collateral groups, Group 1 has PAC + Z + Support classes with a
95.65 / 4.35 face-weighted support split. Group 2 is a sequential
cascade with notional IO.

### FNR 2016-104 (Dec 2016)

**9 separate collateral groups** in one trust. Each group has its own
mini-waterfall. Sample group structures:

- **Group 1 (Pass-Through):** "Group 1 Principal Distribution Amount
  to BA until retired."
  - Single rule, single target.
- **Group 4 (Z + Sequential):** Two rules:
  1. "The Z Accrual Amount to A and B, **in that order**, until
     retired, and **thereafter** to Z."
  2. "The Group 4 Cash Flow Distribution Amount to A, B and Z,
     **in that order**, until retired."
  - Each rule has *multiple* targets in a sequential list.
- **Group 5 (PAC + Support):** Three numbered phases:
  1. To Aggregate Group **to its Planned Balance**.
  2. To LZ until retired.
  3. To Aggregate Group **to zero**.
  - Phase 1 = PAC schedule cap (`cap_mode=PLANNED`).
  - Phase 2 = pure sequential, no cap.
  - Phase 3 = cleanup (`cap_mode=NONE`).
  - **The whole "PAC + Support" pattern is three numbered
    rules, not three rules per bond.**
- **Group 6 (Face-Weighted Split):**
  - "The Group 6 Cash Flow Distribution Amount as follows:
    - 67.8420172533% to QA, QV and QZ, in that order, until retired
    - 32.1579827467% to QB, QW and QY, in that order, until retired"
  - Single SPLIT_CASH at the named percentage with two sub-cascades.

### FNR 2019-17 (Mar 2019)

7 collateral groups. Adds two patterns we did not see in 2006-018 or
2016-104:

- **Pro-rata pay** as a top-level option: "Group 1 Principal
  Distribution Amount to A and FA, **pro rata**, until retired." —
  payment_style=PRO_RATA on a multi-target rule.
- **Nested face-weighted splits** in Group 7:
  - "Group 7 ... Aggregate Group III as follows:
    - 16.6666666667% to MA until retired, **and**
    - 83.3333333333% as follows:
      - first, 44.8738331794% to ME until retired, **and**
        55.1261668206% to MG and MB, in that order, until retired,
      - second, to MC until retired."
  - The 83% branch is itself a SPLIT_CASH with two sub-streams,
    AND that split has two sequential phases ("first" / "second").
  - **Recursive structure**: rules can contain sub-rules.
- **Named "Aggregate Group" abstraction**: "Aggregate Group III
  consists of the MA, ME, MC, MG and MB Classes ... has a principal
  balance equal to the aggregate principal balance of the Classes
  included in Aggregate Group III."
  - A bond *bundle* with its own planned balance and internal
    allocation rules. **Not a separate REMIC class** — a virtual
    grouping for schedule cap and downstream rules.

### Common patterns across all 3 agency REMIC deals

- One waterfall per collateral group.
- Each waterfall has 1-3 logical steps.
- **Each step is a multi-target rule**, not one rule per bond.
- Order language is verbatim from the prospectus: "in that order,
  until retired", "concurrently / pro rata", "to its Planned
  Balance", "to zero".
- Z-bond accrual is its own pre-step: "Accrual Amount to X until
  retired, then to Z" (a sequential cascade itself).
- Face-weighted splits are first-class and **can nest**.
- "Aggregate Group" is a named bond bundle with its own schedule.

---

## RMBS — Non-Agency (Subprime, JPMMT 2006)

### Sample read: JPMorgan Mortgage Acceptance 2006 (CWHEQ-style)

This deal is structurally **very different** from agency:

- Two collateral groups (Group 1 / Group 2 mortgage loans).
- **Two parallel waterfalls per period** — Interest Remittance
  Amount cascade and Principal Remittance Amount cascade — that
  intersect via OC mechanics.
- 12-step **interest waterfall** plus 5-condition **principal
  waterfall** (varies by stepdown date and trigger event).
- M-1 through M-10 subordinate stack.
- Excess interest cascade ("Net Monthly Excess Cashflow") with its
  own multi-step waterfall.
- Net WAC reserve fund with its own sub-waterfall.

#### Interest waterfall (12 numbered steps)

1. Senior interest (concurrent / pro-rata across A-1A, A-1B, A-2..A-5)
2. Senior unpaid interest shortfalls (concurrent)
3-12. M-1 through M-10 interest, **one step per class**, in
   strict seniority order.

The prospectus phrases steps 3-12 as one step per mezz class —
**NOT** as one rule with [M-1..M-10]. The reason: each step is its
own waterfall priority where remaining funds at that step depend on
what was paid above. (For interest where shortfalls are tracked
per-class, step-by-step is more readable.) **Either rendering
(per-class steps OR a single multi-target sequential rule) produces
identical math** — but the prospectus authors prefer per-class for
clarity in the mezz stack.

#### Principal waterfall — gated by 2 conditions, 6 conditional blocks

Each block applies under a different **(stepdown date, trigger
event)** combination:

- **A:** prior to stepdown OR Trigger Event in effect → Group 1
  Principal → Group 1 Certs first, then Group 2 Certs.
- **B:** prior to stepdown OR Trigger Event in effect → Group 2
  Principal → Group 2 Certs first, then Group 1 Certs.
- **C:** prior to stepdown OR Trigger Event in effect → remaining
  combined principal → M-1, M-2, ..., M-10 sequentially.
- **D:** post-stepdown AND no Trigger Event → Group 1 Senior
  Principal Distribution Amount (a different formula) → Group 1
  Senior + cross-allocation to Group 2.
- **E:** post-stepdown AND no Trigger Event → Group 2 Senior
  Principal Distribution Amount → Group 2 Senior + cross-allocation.
- **F:** post-stepdown AND no Trigger Event → remaining → mezz with
  **Combined Class M-1, M-2 and M-3 Principal Distribution Amount**
  (a SHARED computed amount that pays all three sequentially).

#### Computed distribution amounts

Heavy use of NAMED FORMULAS:

- "Group 1 Principal Distribution Amount" = pool collections + advances
- "Group 1 Senior Principal Distribution Amount" = capped formula
- "Combined Class M-1, M-2 and M-3 Principal Distribution Amount" = formula

These are not rules — they are **named scalar calculations** computed
each period and referenced by rules. The current IR has
`CalculationNode` for trigger metrics but doesn't use it for
distribution amounts.

#### Sequential Trigger Event vs Trigger Event

There are **multiple distinct triggers** controlling different
behaviors:

- "Trigger Event" — gates the stepdown.
- "Sequential Trigger Event" — gates Class A-1A / A-1B
  concurrent-vs-sequential.

Both are computed each period from cumulative loss + delinquency
ratios with **time-dependent thresholds** (a different threshold
table per Distribution Date range).

#### Loss allocation — separate cascade

Loss allocation is a SEPARATE waterfall: realized losses go first to
M-10 → M-9 → ... → M-1 → seniors. **Reverse seniority order**, not
the cash distribution order. Currently the IR has no first-class
loss-allocation primitive; it's bolted onto bond writedown logic.

#### Excess interest cascade

"Net Monthly Excess Cashflow" — what's left after paying interest +
fees + scheduled principal — has its OWN multi-step waterfall:

1. To OC build until target reached
2. To unpaid interest shortfalls
3. To realized losses (write-up M-10..M-1)
4. To net WAC carryover
5. ... and several more

This is a sub-waterfall on a derived stream. The IR's `SPLIT_CASH`
primitive can route to a "Net Monthly Excess Cashflow" stream, and
then a sequence of rules consumes it. Workable, but requires
expressing the cascade explicitly.

---

## Auto ABS — Prime (Ford Credit Auto Owner Trust 2024-C)

### Pre-acceleration priority of payments (single 11-step cascade)

```
1. Transaction Fees and Expenses (capped $375K/yr) — to indenture trustee, owner trustee, ARR
2. Servicing Fee — to servicer
3. Class A Note Interest — pro rata across Class A notes
4. First Priority Principal Payment — to Class A, sequentially by class,
   amount = MAX(0, Class A principal - adjusted pool balance)
5. Class B Note Interest
6. Second Priority Principal Payment — to Class A+B, sequentially by class,
   amount = MAX(0, (A+B principal) - adjusted pool balance) - step 4 amount
7. Class C Note Interest
8. Reserve Account Replenishment — to top up to original balance
9. Regular Principal Payment — sequentially by class,
   amount = GREATER OF (a) Class A-1 principal,
                       (b) notes principal - (pool balance - target OC)
   reduced by first + second priority amounts
10. Additional Fees and Expenses (uncapped overflow from step 1)
11. Residual Interest — to depositor
```

### Key structural features

1. **Single Available Funds source** — no group split. All collections
   pool together; the waterfall consumes them in 11 steps.
2. **Interest and principal interleaved** by class seniority, not as
   separate sub-waterfalls. Step 3 = A interest. Step 5 = B interest.
   Step 7 = C interest. The 4 / 6 / 9 between are principal
   acceleration / catch-up steps.
3. **Computed principal amounts**:
   - "First Priority Principal Payment" — explicit formula based on
     overcollateralization deficit; only nonzero if Class A
     principal exceeds adjusted pool balance.
   - "Second Priority Principal Payment" — same shape, A+B view.
   - "Regular Principal Payment" — explicit MAX-of-two-formulas with
     reductions for upstream payments.
4. **Reserve account replenishment as a numbered step** (step 8).
   The current IR has `PAY_TO_RESERVE` rule type, so this is
   covered, but the name is hidden from the user in the FNR fixture
   (no reserve in agency).
5. **Sequential by class for principal**, but **pro rata within
   class** for interest. Class A has sub-classes A-1, A-2a, A-2b,
   A-3, A-4; principal pays A-1 first to retired, then A-2a, etc.;
   interest pays all 5 pro rata each period.
6. **Capped fees with overflow**: Step 1 caps at $375K/year; any
   excess fees move to step 10 (after principal). The IR's
   `max_amount_fixed` covers the cap; the carry-to-later-step needs
   thought.
7. **Post-acceleration priority of payments**: a SEPARATE waterfall
   for after Event of Default (not detailed in our extract). Adds an
   ALTERNATE TOP-LEVEL waterfall gated by deal state.

### What's notable vs RMBS

- **No PAC / TAC / Z**. Auto deals are pure sequential.
- **Single pool, no groups**.
- **No stepdown gate** the way RMBS has it; instead the auto
  structure relies on the priority principal mechanism (steps 4 + 6)
  to maintain seniority backstop, and the "Regular Principal" formula
  (step 9) to build target OC over time.
- **Reserve account is a first-class participant** in the waterfall,
  not just a credit enhancement footnote.
- **Asset-rep fees** (a relatively recent addition tied to ABS Rule
  15Ga-1) appear as a discrete payee.

---

## Auto ABS — Subprime (Santander Drive Auto Receivables Trust 2024-2)

### Pre-acceleration priority of payments (single 14-step cascade)

```
1.  first       — trustee + Delaware trustee + owner trustee + ARR fees
                  ($300K/yr cap)
2.  second      — servicing fee
3.  third       — Class A interest, pro rata
4.  fourth      — First Allocation of Principal
5.  fifth       — Class B interest
6.  sixth       — Second Allocation of Principal
7.  seventh     — Class C interest
8.  eighth      — Third Allocation of Principal
9.  ninth       — Class D interest
10. tenth       — Fourth Allocation of Principal
11. eleventh    — reserve replenishment (to Specified Reserve Balance)
12. twelfth     — Regular Allocation of Principal
13. thirteenth  — trustee fee overflow (per-annum cap exceeded)
14. fourteenth  — residual to certificateholders, pro rata
```

### Same shape as prime auto with parametric differences only

The waterfall is structurally **identical** to Ford Credit prime
auto. The differences are entirely parametric:

| Feature | Ford Credit (prime) | SDART (subprime) |
|---|---|---|
| Step count | 11 | 14 |
| Mezz classes | A, B, C | A, B, C, D |
| Named principal allocations | First, Second, Regular | First, Second, Third, Fourth, Regular |
| Trustee fee per-annum cap | $375K | $300K |
| Residual recipient | "Holder of residual interest" | "Certificateholders, pro rata" |

**Implication for the IR:** prime + subprime auto share **one
waterfall grammar**. The IR does not need a "subprime auto" rule
type or a "prime auto" rule type — same primitives, more
parameters.

### Post-acceleration priority of payments

After Event of Default + acceleration, a SEPARATE waterfall
applies (typically: trustee fees → all classes interest pro rata
→ all classes principal sequentially with no priority principal
acceleration). Triggered by indenture conditions, not period-by-period.

This is structurally the same as the JPMMT "Trigger Event in
effect" branch in the RMBS principal waterfall — an alternate
mode gated by a deal-state trigger.

---

## Cross-asset-class observations

### What ALL deals have in common

1. **Numbered priority of payments** — the prospectus is always a
   numbered list of steps.
2. **Each step has multiple targets in a list with explicit order
   semantics** (sequential, pro-rata, concurrent).
3. **Each step has explicit cap semantics**: "to its planned
   balance" / "until retired" / "to zero" / "amount equal to..."
4. **Triggers gate behavior**, but the *type* of trigger varies:
   stepdown date + cumulative loss + delinquency in RMBS;
   acceleration / event of default in auto.
5. **A "named amount" abstraction** is always implied — every deal
   defines named formulas like "Group X Principal Distribution
   Amount", "First Priority Principal Payment", "Net Monthly Excess
   Cashflow", and refers to them by name in subsequent steps.
6. **Residual / equity / depositor** is always the final step.

### What VARIES across asset classes

| Feature | Agency MBS | Non-Agency RMBS | Prime Auto |
|---|---|---|---|
| Distinct collateral groups | YES (1-9 per deal) | YES (typically 1-2) | NO |
| Separate INT/PRIN sub-streams | YES (INT_CASH/PRIN_CASH) | YES (Interest Remittance Amount + Principal Remittance Amount) | NO (combined Available Funds) |
| Group-aware allocation | YES | YES (Group 1 Certs, Group 2 Certs) | N/A |
| PAC / TAC / Z behavior | YES | NO | NO |
| Stepdown date gate | NO | YES | NO |
| OC / Reserve account in waterfall | RARE (REMIC trust-level fees) | YES (excess interest cascade) | YES (step 8) |
| Sequential vs pro-rata switch | NO | YES (Sequential Trigger Event) | NO |
| Interleaved I/P by class | NO | NO (separate I and P waterfalls) | YES (interest 3, prin 4; interest 5, prin 6...) |
| Loss allocation cascade | rare | YES (reverse seniority) | rare (covered by OC) |
| Computed (named) distribution amounts | LIGHT (just "Group N Cash Flow Distribution Amount") | HEAVY (every step references named formulas) | MEDIUM (priority principal payments are formulas) |
| Recursive splits | YES (FNR 2019-17 Group 7) | RARE | NO |
| Aggregate Group bond bundles | YES | NO | NO |

### Cross-cutting needs

1. **Multi-target rules with explicit payment_style** — already
   supported in IR. **Use it more** in the FNR fixture and the
   irGenerator.
2. **Named distribution amounts** — referenced by name in rule
   sources. Currently the IR has `INT_CASH` / `PRIN_CASH` as built-in
   streams and `SPLIT_CASH` to create new ones; this generalizes to
   "any named formula". Need a `CalculationNode`-style
   "ComputedAmount" object that produces a per-period scalar usable
   as a `from_source` cap.
3. **Conditional rule blocks** — the RMBS principal waterfall has
   six mutually exclusive blocks (A through F) keyed on (stepdown
   date, trigger event). Currently expressed via `condition_trigger`
   on each rule, which works but is verbose. A `RuleGroup` or
   `WaterfallBranch` abstraction would make multi-step branches
   readable.
4. **Loss allocation as a first-class waterfall** — separate from
   cash distribution. Order is reverse seniority. Inputs are the
   pool LOSS stream + write-down provisions.
5. **Aggregate Group abstraction** — a NAMED collection of bonds
   treated as a unit (own planned balance, internal allocation rule).
   Currently expressed by tagging each bond and listing them in a
   rule's `to_targets`; works but loses the "this is a group" intent.
6. **Reserve account integration** — already supported via
   `PAY_TO_RESERVE` / `PAY_FROM_RESERVE_*`. Used heavily in auto;
   present in non-agency RMBS via OC mechanics.
7. **Excess interest sub-cascade** — a separate sub-waterfall driven
   by what's left after the "main" interest cascade. Need a clean
   way to express the carry-forward.

---

## Gaps in the current IR

After this 4-deal sample:

| Gap | Severity | Affects |
|---|---|---|
| Named distribution amounts (computed scalars) referenced by source name | **HIGH** | non-agency RMBS, prime auto |
| Multi-target sequential rules under-used in fixtures and irGenerator | **HIGH** | every asset class (visual / authoring) |
| Aggregate Group bond bundles | MEDIUM | agency MBS |
| Recursive / nested splits | MEDIUM | agency MBS (FNR 2019-17 pattern) |
| Loss allocation as first-class waterfall (reverse seniority) | MEDIUM | non-agency RMBS, future CMBS |
| Branched waterfalls (6 mutually exclusive A-F blocks gated by stepdown × trigger) | MEDIUM | non-agency RMBS |
| Net WAC reserve / sub-cascade plumbing | LOW (covered by SPLIT_CASH + accounts) | non-agency RMBS |
| Post-acceleration alternate waterfall | LOW (covered by triggers) | auto |
| Capped fee with overflow to later step | LOW | auto |

---

## Proposed IR additions (DRAFT — not approved)

### A. Multi-target rule consolidation (no schema change, fixture rewrite + synth/irGen change)

Stop fragmenting by emitting one rule per bond. Both the FNR fixture
authors and the `emitPacTacSchedule` block generator should emit
multi-target rules (`to_targets: [PA, PB, PC, PD, EO]`,
`payment_style: SEQUENTIAL`, `cap_mode: PLANNED`).

**Why first:** zero schema risk, biggest immediate benefit. The rule
count drops from ~24 to ~5 for FNR Group 1.

### B. ComputedAmount node (small schema add)

```python
class ComputedAmountNode(BaseModel):
    name: str           # "Group 1 Principal Distribution Amount"
    expression: str     # "principal + advance_prin + recovery"
    description: str
```

Rules can reference `ComputedAmountNode` names in `from_sources` the
same way they reference `INT_CASH`/`PRIN_CASH`. The runtime resolves
the name to the per-period scalar.

### C. RuleGroup / WaterfallBranch wrapper

```python
class RuleGroup(BaseModel):
    rule_group_id: str
    description: str
    condition_trigger: str | None
    condition_invert: bool = False
    rules: list[RuleNode]
```

A rule group is "rules that fire only when a condition holds, as a
unit". Solves the RMBS A-F branching problem without putting
`condition_trigger` on every rule individually.

### D. AggregateGroup bond bundle

```python
class AggregateGroupDef(BaseModel):
    name: str           # "Aggregate Group III"
    members: list[str]  # ["MA", "ME", "MC", "MG", "MB"]
    schedule_contract: list[...] | None    # planned balance (PAC)
    internal_allocation: PaymentStyle      # SEQUENTIAL / PRO_RATA
```

A virtual bundle that rules can target by name. The runtime caps at
the bundle's planned balance and distributes internally per the
allocation rule.

### E. LossAllocationRule (new rule type)

```python
RuleType.LOSS_ALLOCATION = "LOSS_ALLOCATION"
# from_sources: ["LOSS"]
# to_targets: ["M-10", "M-9", ..., "M-1", "A"]  (reverse seniority)
# payment_style: SEQUENTIAL
```

Separate from cash distribution. Decrements bond balance for losses,
rather than paying cash.

### F. Recursive SPLIT_CASH (no schema change, runtime change)

Already supported in principle: a SPLIT_CASH target stream can be
the source of another SPLIT_CASH. Verify this works for FNR 2019-17
Group 7's nested 16.67 / 83.33 / first / second pattern.

---

## Open questions for user before any code change

1. **Priority.** Which of (A)-(F) above matter for your near-term
   deal universe? My read: (A) is must-have *now* (it fixes the
   visual problem you flagged); (B) and (C) are needed once we
   start modeling private-label RMBS; (D) is agency-MBS-specific;
   (E) is RMBS / CMBS / future CRT; (F) is already kind of working.

2. **More research breadth.** Do you want me to extend this study
   to the other asset classes (subprime auto, credit card, CLO,
   marketplace, equipment, solar) before proposing changes, or are
   the structural patterns above enough to converge on the
   abstractions for now and revisit the IR when those asset classes
   are needed? **My recommendation: do (A) now (no IR risk), park
   (B)-(F) until we have ≥5 deals per relevant asset class.**

3. **The PAC/TAC/Z question** you raised originally. The IR
   *intentionally* does not have `PAY_PRINCIPAL_PAC_SCHEDULE` as a
   distinct rule type — the PAC behavior is encoded as
   `BondDef.tranche_behavior=PAC` + `BondDef.schedule_contract` +
   `RuleNode.cap_mode=PLANNED`. This is the right call for the
   *runtime* (PAC and SEQ have the same allocation logic; only the
   bond's per-period cap differs). But for the *UI* we should
   recognize "this rule pays a PAC bond with cap_mode=PLANNED" and
   render it via the existing `pay_pac_schedule` Blockly block.
   The synthesizer can detect this from the IR (any rule whose
   targets include a bond with `tranche_behavior=PAC` and whose
   `cap_mode=PLANNED` is a PAC schedule rule).

   **The IR doesn't need a new rule type for PAC/TAC; the
   synthesizer + irGenerator just need to recognize the pattern.**
