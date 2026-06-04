# Test Fixture Status — `corpus-fixture-status` (Phase 1)

> **Source of truth:** `docs/architecture/prospectus_inventory.md`. This document is a human-readable summary; for canonical metadata see the inventory.

**Authoritative classification of every prospectus named in `docs/architecture/waterfall_ir_design.md`** per the three-tier classification mandated by the `corpus-fixture-status` Phase 1 ticket.

The plan can require canonicalization round-trip + cashflow tie-out only on (i) STRUCTURAL and (ii) QUANTITATIVE GOLDEN fixtures. (iii) RESEARCH-ONLY corpus entries are explicitly downgraded — they are RAG governance material, not test coverage. This document is the single source of truth for which deal names support which kinds of test claims.

The shape of this file is enforced by `tests/test_corpus_fixture_status.py`.

## Classification key

| Tier | Definition | Test coverage commitment |
|---|---|---|
| (i) STRUCTURAL | Compiles + runs (no `ValidationError`; engine produces a finite cashflow); no quantitative tie-out to a published source | round-trip + canonicalization round-trip + non-regression |
| (ii) QUANTITATIVE GOLDEN | (i) plus matches a published decrement table, trustee tape, or other authoritative quantitative source within tolerance | (i) + per-period tie-out via dedicated test file |
| (iii) RESEARCH-ONLY | Cited prose in `waterfall_ir_design.md`; no executable artifact in `tests/fixtures/` | NONE; RAG-corpus only |

## Per-deal classification

The Phase 1 `tests/fixtures/` directory contains 5 deal builder fixtures plus 2 non-deal directories (`diagnostic_parity/`, `verification/`).

### Deal builder fixtures

| Deal | Fixture path | Tier | Quantitative test |
|---|---|---|---|
| **FNR 2006-018** | `tests/fixtures/fnr_2006_018/deal_definition.py` | **(ii) QUANTITATIVE GOLDEN** | `test_fnr_2006_018_decrement_table.py`, `test_fnr_2006_018_group_2_decrement_table.py`, `test_fnr_2006_018_yield_tables.py`, `test_fnr_2006_018_combined.py`, `test_fnr_2006_018_staged_tieout.py`, `test_fnr_2006_018_parity.py` |
| **Ginnie Mae 2025-203** | `tests/fixtures/ginniemae_2025_203/deal_definition.py` | **(i) STRUCTURAL** | none — fixture compiles + runs but no published decrement tape integrated yet |
| **Verus 2024-9** | `tests/fixtures/verus_2024_9/deal_definition.py` | **(i) STRUCTURAL** | none |
| **Ford Credit Auto Owner Trust 2024-C** | `tests/fixtures/ford_2024_c/deal_definition.py` | **(i) STRUCTURAL** | none |
| **CC Series Test** | `tests/fixtures/cc_series_test/deal_definition.py` | **(i) STRUCTURAL** (synthetic test fixture, not a real-world prospectus) | none |

### Non-deal fixture directories

| Directory | Purpose |
|---|---|
| `tests/fixtures/diagnostic_parity/` | vpc-5 + ve-2 parity fixtures (invalid-deal payloads with expected diagnostic output) |
| `tests/fixtures/verification/` | (legacy) verification snapshots; not deal builders |

### Research-only corpus entries (NOT fixtures)

These prospectuses are cited in `waterfall_ir_design.md` for pattern coverage but have **no executable artifact** in `tests/fixtures/`. Claims about these deals are RAG governance material only and CANNOT be used to assert canonicalization round-trip, structural validity, or any cashflow tie-out.

| Deal | Asset class | Cited for |
|---|---|---|
| FNR 2016-104 | Agency MBS REMIC | 9 collateral groups; mix of pass-through, sequential, accretion-directed, PAC; face-weighted splits |
| FNR 2019-17 | Agency MBS REMIC | 7 collateral groups; nested face-weighted splits; named Aggregate Group abstraction |
| FNMA 2024-M2 | Agency Multifamily REMIC | Multifamily; structurally similar to single-family REMICs |
| CAS 2024-R05 | Agency Synthetic CRT | Reference pool of FNMA-acquired loans; M-1/M-2/B-1/B-2 notes; reverse-seniority bond writedowns |
| CAS 2024-R06 | Agency Synthetic CRT | Same shape as CAS 2024-R05 |
| Ginnie Mae 2025-009 (HECM) | Agency MBS REMIC | Reverse-mortgage REMIC; Deferred Interest Amount (catch-up rule type not in current IR) |
| JPMMT 2006 | Non-Agency RMBS (subprime) | Interest waterfall + principal waterfall sub-streams; stepdown date; trigger event override; OC + excess interest |
| Verus 2026-4 | Non-Agency RMBS (Non-QM) | Same family as Verus 2024-9 fixture; cited for pattern reinforcement |
| Toyota Auto Receivables 2024-A | Prime Auto ABS | Same shape as Ford Credit fixture; Yield Supplement Overcollateralization Amount |
| Toyota Lexus Owner Trust 2024-A (TLOT) | Auto Lease ABS | Lease-specific 8-step waterfall; "Securitization Value" valuation |
| Santander Drive 2024-2 (SDART) | Subprime Auto ABS | Same shape as Ford Credit; parametric differences only |
| Westlake 2024-1 (WLAKE) | Subprime Auto ABS | 8-class structure; subprime auto pattern reinforcement |
| Ginnie Mae 2024-115 (Multifamily) | Agency Multifamily REMIC | Multifamily: trustee fee % of Principal Distribution Amount deducted before principal cascade; `PAY_FEE` with `basis_type=COLLATERAL_BALANCE` covers this; cited for multifamily vs single-family agency REMIC differences |
| Freddie Mac REMIC general structure (offering circular) | Agency REMIC | Single-Tier vs Double-Tier Series (REMIC-inside-REMIC); MACR Certificates; lower-tier mechanics transparent for cashflow IR |
| Capital One COMET | Credit Card Master Trust | Cited in AI corpus seed for credit card master trust pattern (Card series 2002-CC supplement; SF-3 registration) |
| Chase Issuance Trust | Credit Card Master Trust | Cited in AI corpus seed for credit card master trust pattern (CHASEseries A-2024-2, A-2025-1) |
| Citibank Credit Card Issuance Trust | Credit Card Master Trust | Cited in AI corpus seed for credit card master trust pattern (Citiseries 2023-A2 plus earlier 424B5 filings) |
| Discover Card Execution Note Trust | Credit Card Master Trust | Cited in AI corpus seed for credit card master trust pattern (DCENT Class A 2022-2) |
| American Express Credit Account Master Trust | Credit Card Master Trust | Cited in AI corpus seed for credit card master trust pattern (Series 2025-4) |

## Round-trip + canonicalization commitment

Per Phase 0 B6 (canonical-post-migration byte-identical IR round-trip) and the `rule-canonicalization-framework` ticket's round-trip requirement:

- **Round-trip + canonicalization round-trip MUST run on**: every (i) and (ii) fixture above. Currently 5 deal-builder fixtures (`fnr_2006_018`, `ginniemae_2025_203`, `verus_2024_9`, `ford_2024_c`, `cc_series_test`).
- **Per-period quantitative tie-out runs on**: every (ii) fixture only. Currently 1 fixture (`fnr_2006_018`) with a complete suite of decrement-table + yield-table + staged-tieout tests.
- **NO test coverage commitment** is made for any (iii) research-only entry. The plan's Vision narrative may cite these deals for pattern coverage, but no automated test can be authored that asserts canonicalization or cashflow correctness against them.

## Maintenance

When a new fixture is added to `tests/fixtures/`:
1. Append a row to the **Deal builder fixtures** table classifying it as (i) or (ii).
2. If (ii), enumerate the dedicated quantitative test file(s).
3. The `corpus-fixture-status` ticket explicitly forbids classifying a fixture as (ii) without a corresponding tie-out test in the same commit.

When a new prospectus is cited in `waterfall_ir_design.md`:
1. If a corresponding fixture is added in the same patch series, classify it (i) or (ii) per above.
2. If only cited as research material, append to the **Research-only corpus entries** table.

The meta-tests in `tests/test_corpus_fixture_status.py` enforce that every fixture with `deal_definition.py` and every named research-only prospectus is referenced here. Drift between this document and the fixture set fails CI.

## Audit trail

This document was authored as the deliverable for the Phase 1 `corpus-fixture-status` ticket. The Phase 1 plan classifies this todo as **routine** (no D1 + R1 required); a parent agent audited the existing fixtures + cross-referenced `docs/architecture/waterfall_ir_design.md` in a single TDD pass (failing meta-tests committed first; this document committed second).

The 5 deal builder fixtures match the explicit fixture set named in `studio-document-and-store.md` sds-3 AC 8 (`fnr_2006_018`, `ginniemae_2025_203`, `verus_2024_9`, `cc_series_test`, `ford_2024_c`). The fixture-count parity guard at `scripts/emit_canonical_fixtures.py --check` enforces that every fixture directory with a `deal_definition.py` has a corresponding `deal.canonical.json`. This STATUS.md adds the additional layer of test-tier classification.

## Follow-on tickets

(None — the heuristic `_PROSPECTUS_PATTERNS` regex inventory has been replaced by the structured `docs/architecture/prospectus_inventory.md` source-of-truth artifact. CI now validates against the inventory directly.)
