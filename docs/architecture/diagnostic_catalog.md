# Diagnostic Catalog

**Source of truth** for all registered diagnostic codes in the BMA Standard Formulas validation
system. Both the Python `@diagnostic_code` decorator registry and the TypeScript worker registry
are expected to reflect every entry in this table. The `vpc-4-ci-guard` tooling enforces that
no decorated validator may exist in the codebase without a corresponding catalog entry.

## Contract

Each row in the Catalog Table below defines one diagnostic code. The columns map as follows:

| Column | Meaning |
| --- | --- |
| `code` | Unique string identifier, SCREAMING_SNAKE_CASE. Must match the first arg of `@diagnostic_code(...)`. |
| `severity` | One of `error`, `warning`, `info` (mirrors `Severity` enum). |
| `path schema` | JSON-Path-like template for the field location. Supports `.field`, `[*]`, and `[id_var]` substitution patterns. |
| `message template` | Human-readable message with `{variable}` placeholders resolved at emit time. |
| `owner` | One of `backend`, `worker`, `both`. Codes with `owner ∈ {worker, both}` must also be registered in the TypeScript worker registry. |
| `quick fix` | One-sentence actionable resolution for the diagnostic consumer. |
| `owning validator file:line` | Repo-relative path and line number of the `@diagnostic_code` decoration, e.g. `src/.../foo.py:42`. Updated when the decorator moves. |

## Catalog Table

| code | severity | path schema | message template | owner | quick fix | owning validator file:line |
| --- | --- | --- | --- | --- | --- | --- |
| MERGE_CONFLICT | error | deal.{entity_kind}[{entity_id}].{field_path} | Merge conflict on {field_path} between base and branch values for {entity_kind} {entity_id} | backend | Resolve the conflicting field in Studio or reset the feature branch to base before retrying the merge. | src/bma_cfengine_app/orchestrator/deals/merge.py:17 |
| REPO_CORRUPT | error | deal:{deal_id} | Repository corruption detected for deal {deal_id}: {detail} | backend | Run restore_deal to re-clone the deal bundle from the last known-good backup. | src/bma_cfengine_app/orchestrator/deals/operational.py:45 |
| BOND_NAME_EMPTY | error | deal.bonds[*].name | Bond at index {index} has an empty or missing name. | both | Supply a non-blank name for every bond in the deal definition. | src/bma_standard_formulas/diagnostics/structural_validators.py:26 |
| BOND_NAME_DUPLICATE | error | deal.bonds[*].name | Bond '{name}' at index {index} duplicates bond at index {first_index}. | both | Rename one of the duplicate bonds to a unique name. | src/bma_standard_formulas/diagnostics/structural_validators.py:49 |
| REFERENCE_BROKEN | error | deal.waterfall_rules[*].from_sources | Rule '{rule_id}' references non-existent source(s) or target(s). | both | Correct the from_sources/to_targets to reference existing bond, account, or fee names. | src/bma_standard_formulas/diagnostics/structural_validators.py:70 |
| MULTI_TARGET_WEIGHT_SUM_INVALID | error | deal.waterfall_rules[*].target_weights | Rule '{rule_id}' target_weights sum to {sum}, expected 1.0. | both | Adjust target_weights so they sum to exactly 1.0. | src/bma_standard_formulas/diagnostics/structural_validators.py:113 |
| KIND_SCHEDULE_SOURCE_INCONSISTENT | error | deal.bonds[*].kind | Bond '{name}' (kind={kind}) has inconsistent schedule configuration. | both | Add schedule_contract or schedule_model_type for PAC/TAC; remove them for non-PAC/TAC. | src/bma_standard_formulas/diagnostics/structural_validators.py:137 |
| NLA_SUBORDINATION_INCONSISTENT | error | deal.bonds[*].nla_starting_balance | Bond '{name}' has NLA/subordination fields set inconsistently. | both | Set both nla_starting_balance and required_subordination_pct together, or neither. | src/bma_standard_formulas/diagnostics/structural_validators.py:167 |
| MULTI_GROUP_ROUTING_INVALID | error | deal.waterfall_rules[*].from_sources | Rule '{rule_id}' references group-prefixed source not in declared collateral_groups. | both | Ensure group-prefixed sources (GROUP_X_CASH etc.) reference a declared collateral_groups entry. | src/bma_standard_formulas/diagnostics/structural_validators.py:193 |
