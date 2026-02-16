# BMA Compliance Test Organization

## Overview

This directory contains tests for BMA (Bond Market Association) compliance functions. Tests are organized using Python's `unittest` framework with a custom test suite orchestrator to ensure proper execution order and dependencies.

## Test Framework

**Framework**: Python `unittest` (not pytest)

**Test Orchestrator**: `test_suite_bma_compliance.py` uses unittest's standard `load_tests` protocol to enforce module execution order.

## Test Modules

### Prerequisite Tests (Must Pass First)

1. **`test_bma_reference_b1_payments.py`**
   - Tests BMA Section B.1 payment/balance functions
   - Foundation for all other tests
   - Contains `TEST_SCENARIOS` used by consistency tests
   - Execution order: 1

2. **`test_bma_reference_b2_prepayment.py`**
   - Tests BMA Section B.2 prepayment conversion functions
   - Tests: `bma_smm_from_factors`, `bma_cpr_to_smm`, `bma_smm_to_cpr`, `bma_psa_to_cpr`, `bma_cpr_to_psa`, `bma_generate_psa_curve`
   - Independent of B.1 and C.3
   - Execution order: 2

3. **`test_bma_reference_c3_cashflows.py`**
   - Tests BMA Section C.3 cashflow functions
   - Tests: `run_bma_scheduled_cashflow`, `run_bma_actual_cashflow`
   - Validates against `bma_cashflow_a.csv` and `bma_cashflow_b.csv` fixtures
   - Prerequisite for consistency tests
   - Execution order: 3

### Dependent Tests

4. **`test_bma_reference_c3b1_consistency.py`**
   - Tests consistency between C.3 and B.1 functions
   - **Depends on**: B.1 and C.3 tests passing
   - Cross-references C.3 cashflow functions with B.1 formulas under 0% CPR/0% CDR
   - Contains its own copy of `TEST_SCENARIOS` (does not import from B.1 tests)
   - Execution order: 4

### Utility Modules

5. **`test_suite_bma_compliance.py`**
   - Test suite orchestrator using unittest's `load_tests` protocol
   - Enforces module-level execution order
   - Manually calls `setUpModule()` for each module during suite construction

6. **`test_suite_utilities.py`**
   - Utility classes for test scenarios (`TestLoan`, `TestScenario`)
   - Shared test infrastructure

## Test Execution Order

Tests are automatically ordered by `test_suite_bma_compliance.py` using unittest's `load_tests` protocol. The order is:

1. B.1 payment/balance tests (`test_bma_reference_b1_payments`)
2. B.2 prepayment conversion tests (`test_bma_reference_b2_prepayment`)
3. C.3 cashflow tests (`test_bma_reference_c3_cashflows`)
4. C.3/B.1 consistency tests (`test_bma_reference_c3b1_consistency`)

**Important**: The `load_tests` protocol enforces **module-level** execution order. Tests within each module run in alphabetical order (unittest default).

## Running Tests

### Run All Tests (Recommended)

```bash
# Run all BMA compliance tests in order using the test suite
python -m unittest tests.laminarcf.bma_compliance.tests.test_suite_bma_compliance

# Or use unittest discovery (will use load_tests if present)
python -m unittest discover tests/laminarcf/bma_compliance/tests -p test_*.py

# With verbose output
python -m unittest tests.laminarcf.bma_compliance.tests.test_suite_bma_compliance -v
```

### Run Specific Test Modules

```bash
# Run prerequisites first
python -m unittest tests.laminarcf.bma_compliance.tests.test_bma_reference_b1_payments -v
python -m unittest tests.laminarcf.bma_compliance.tests.test_bma_reference_b2_prepayment -v
python -m unittest tests.laminarcf.bma_compliance.tests.test_bma_reference_c3_cashflows -v

# Then run consistency tests
python -m unittest tests.laminarcf.bma_compliance.tests.test_bma_reference_c3b1_consistency -v
```

### Run Specific Test Classes

```bash
# Run a specific test class
python -m unittest tests.laminarcf.bma_compliance.tests.test_bma_reference_b1_payments.TestB1SurvivalFactorConsistency -v

# Run a specific test method
python -m unittest tests.laminarcf.bma_compliance.tests.test_bma_reference_b2_prepayment.TestB2SmmFromFactors.test_sf7_example_single_month -v
```

## Test Architecture Details

### Module Setup (`setUpModule`)

Each test module may define a `setUpModule()` function that:
- Pre-computes test scenarios (e.g., `TEST_SCENARIOS`)
- Loads fixture data
- Performs module-level initialization

The `test_suite_bma_compliance.py` orchestrator manually calls `setUpModule()` for each module during suite construction to ensure shared state is populated before tests run.

### Test Scenario Management

- `test_bma_reference_b1_payments.py` generates `TEST_SCENARIOS` in its `setUpModule()`
- `test_bma_reference_c3b1_consistency.py` contains its own copy of `TEST_SCENARIOS` generation logic (does not import from B.1 tests)
- This avoids cross-module import dependencies and ensures tests are self-contained

### Test Data Sources

Tests validate against fixture files in `../fixtures/`:
- `bma_cashflow_a.csv` - BMA Cash Flow A (SF-28) reference data
- `bma_cashflow_b.csv` - BMA Cash Flow B (SF-29) reference data
- `1m_PSAtoSMM_conversion.csv` - BMA SF-10 PSA to SMM conversion table
- `bma_prepay_rate_conversion_table.csv` - BMA SF-9 prepayment rate conversion table

Verification scripts in `../fixtures/verification/` independently verify fixture correctness:
- `verify_bma_cashflow_a.py` - Verifies bma_cashflow_a.csv
- `verify_bma_cashflow_b.py` - Verifies bma_cashflow_b.csv
- `verify_psa_table_sf10.py` - Verifies 1m_PSAtoSMM_conversion.csv
- `verify_prepay_table_sf9.py` - Verifies bma_prepay_rate_conversion_table.csv

## Current Approach

Currently using **unittest's `load_tests` protocol** which:
- ✅ Enforces module-level execution order
- ✅ No additional dependencies required (standard unittest)
- ✅ Works with unittest discovery
- ✅ Simple and maintainable
- ✅ Manually calls `setUpModule()` to populate shared state

## Best Practices

1. **Always run all tests** when making changes to ensure nothing breaks
   ```bash
   python -m unittest tests.laminarcf.bma_compliance.tests.test_suite_bma_compliance -v
   ```

2. **Fix failing prerequisite tests first** before running consistency tests

3. **Keep test modules self-contained** - avoid cross-module imports of test data

4. **Use `setUpModule()`** for module-level initialization that needs to happen before tests run

5. **Verify fixtures independently** - run verification scripts to ensure fixture correctness

## Test Statistics

Current test suite status (as of last update):
- **Total tests**: 60
- **Skipped**: 3
- **All tests passing**: ✅

## Future Improvements

Consider:
- Adding test coverage reporting
- Creating a test suite runner script with better output formatting
- Adding CI/CD configuration that respects test order
- Documenting test scenario generation logic for easier maintenance
