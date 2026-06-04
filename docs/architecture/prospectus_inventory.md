# Prospectus Inventory — Canonical Source of Truth

Structured inventory of every prospectus referenced in the BMA Standard Formulas corpus.
Parsed programmatically by `scripts/parse_prospectus_inventory.py`; validated by
`tests/test_corpus_fixture_status.py`.

## Schema

| Column | Type | Description |
|---|---|---|
| `prospectus_id` | `string` (kebab-case) | Machine-readable unique identifier |
| `display_name` | `string` | Human-readable prospectus name (as cited in source docs) |
| `issuer` | `string` | Issuing entity or sponsor |
| `asset_class` | `string` | Asset class (e.g. Agency MBS REMIC, Auto ABS, Credit Card) |
| `tier` | `enum` | `structural` (i), `quantitative_golden` (ii), or `research_only` (iii) |
| `fixture_dir` | `string \| null` | Directory name under `tests/fixtures/`, or `null` if no fixture |
| `source_docs` | `string` (semicolon-separated paths) | Documents where this prospectus is referenced |

### Tier definitions

| Tier value | Label | Meaning |
|---|---|---|
| `structural` | (i) STRUCTURAL | Compiles + runs; no quantitative tie-out to a published source |
| `quantitative_golden` | (ii) QUANTITATIVE GOLDEN | Structural + matches a published decrement table or trustee tape |
| `research_only` | (iii) RESEARCH-ONLY | Cited in prose; no executable artifact in `tests/fixtures/` |

## Inventory

<!-- BEGIN INVENTORY TABLE — machine-parsed by scripts/parse_prospectus_inventory.py -->

| prospectus_id | display_name | issuer | asset_class | tier | fixture_dir | source_docs |
|---|---|---|---|---|---|---|
| fnr-2006-018 | FNR 2006-018 | Fannie Mae | Agency MBS REMIC | quantitative_golden | fnr_2006_018 | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| ginnie-mae-2025-203 | Ginnie Mae 2025-203 | Ginnie Mae | Agency MBS REMIC | structural | ginniemae_2025_203 | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| verus-2024-9 | Verus 2024-9 | Verus Securitization Trust | Non-Agency RMBS (Non-QM) | structural | verus_2024_9 | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| ford-credit-2024-c | Ford Credit Auto Owner Trust 2024-C | Ford Motor Credit | Prime Auto ABS | structural | ford_2024_c | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| cc-series-test | CC Series Test | Synthetic | Credit Card Master Trust | structural | cc_series_test | tests/fixtures/STATUS.md |
| fnr-2016-104 | FNR 2016-104 | Fannie Mae | Agency MBS REMIC | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| fnr-2019-17 | FNR 2019-17 | Fannie Mae | Agency MBS REMIC | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| fnma-2024-m2 | FNMA 2024-M2 | Fannie Mae | Agency Multifamily REMIC | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| cas-2024-r05 | CAS 2024-R05 | Fannie Mae (CAS) | Agency Synthetic CRT | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| cas-2024-r06 | CAS 2024-R06 | Fannie Mae (CAS) | Agency Synthetic CRT | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| ginnie-mae-2025-009 | Ginnie Mae 2025-009 | Ginnie Mae | Agency MBS REMIC | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| ginnie-mae-2024-115 | Ginnie Mae 2024-115 | Ginnie Mae | Agency Multifamily REMIC | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| freddie-mac-remic | Freddie Mac REMIC | Freddie Mac | Agency REMIC | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| jpmmt-2006 | JPMMT 2006 | JPMorgan Chase | Non-Agency RMBS (Subprime) | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| verus-2026-4 | Verus 2026-4 | Verus Securitization Trust | Non-Agency RMBS (Non-QM) | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| toyota-auto-2024-a | Toyota Auto Receivables 2024-A | Toyota Motor Credit | Prime Auto ABS | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| toyota-lexus-2024-a | Toyota Lexus Owner Trust 2024-A | Toyota Motor Credit | Auto Lease ABS | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| santander-drive-2024-2 | Santander Drive 2024-2 | Santander Consumer USA | Subprime Auto ABS | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| westlake-2024-1 | Westlake 2024-1 | Westlake Financial Services | Subprime Auto ABS | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| capital-one-comet | Capital One COMET | Capital One | Credit Card Master Trust | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| chase-issuance-trust | Chase Issuance Trust | JPMorgan Chase | Credit Card Master Trust | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| citibank-cc-issuance-trust | Citibank Credit Card Issuance Trust | Citibank | Credit Card Master Trust | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| discover-card-execution-note | Discover Card Execution Note Trust | Discover Financial | Credit Card Master Trust | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |
| amex-credit-account-trust | American Express Credit Account Master Trust | American Express | Credit Card Master Trust | research_only | null | docs/architecture/waterfall_ir_design.md; tests/fixtures/STATUS.md |

<!-- END INVENTORY TABLE -->

## Maintenance

When adding a new prospectus to the corpus:

1. Add a row to the inventory table above with all columns populated.
2. Update `tests/fixtures/STATUS.md` to include the same entry under the appropriate tier section.
3. Run `python -m pytest tests/test_corpus_fixture_status.py -v` to verify inventory ↔ STATUS.md ↔ fixture parity.

When promoting a research-only entry to a fixture:

1. Change `tier` from `research_only` to `structural` (or `quantitative_golden`).
2. Set `fixture_dir` to the new directory name under `tests/fixtures/`.
3. Add `tests/fixtures/STATUS.md` to `source_docs` if not already present.
