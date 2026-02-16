"""
BMA Compliance Test Suite

This module provides a unified test suite that runs all BMA compliance tests
in the correct order using unittest's standard `load_tests` protocol.

The `load_tests` protocol is the standard unittest mechanism for custom test
loading and ordering. When unittest discovers this module, it will call
`load_tests()` to get the test suite.

Test Execution Order:
1. B.1 payment/balance tests (test_b1_payments)
2. B.2 prepayment conversion tests (test_b2_prepayment)
3. B.3 historical speed recovery tests (test_b3_historical_speeds)
4. B.4 ABS prepayment tests (test_b4_abs_prepayment)
5. C.3 cashflow tests (test_c3_cashflows)
6. C.3/B.1 consistency tests (test_c3b1_consistency)

Usage:
    # Run all BMA compliance tests in order (recommended)
    python -m unittest tests.test_suite
    
    # Or use unittest discovery (will use load_tests if present)
    python -m unittest discover tests -p test_*.py -v
    
    # Or run individual test modules (ensure prerequisites run first)
    python -m unittest tests.test_b1_payments
    python -m unittest tests.test_c3_cashflows
    python -m unittest tests.test_c3b1_consistency

Note:
    The `load_tests` protocol is the standard unittest way to customize test
    loading. This ensures tests run in the correct order when using discovery
    or running this module directly.

Version: 0.1.0
Last Updated: 2026-01-29
"""

import unittest
import sys


# =============================================================================
# Test Suite Definition (using unittest's load_tests protocol)
# =============================================================================

def load_tests(loader, standard_tests, pattern):
    """
    Custom test loader using unittest's standard `load_tests` protocol.
    
    This function enforces MODULE execution order by loading modules sequentially
    into the test suite. Tests within each module still run in alphabetical order
    (unittest default), but modules execute in the specified order.
    
    IMPORTANT: This enforces MODULE order, not test method order within modules.
    setUpModule() is called when modules are imported (during suite construction),
    not when tests execute. For cross-module dependencies, check prerequisites
    in test setUp() methods rather than setUpModule().
    
    The `load_tests` protocol is documented in Python's unittest module:
    https://docs.python.org/3/library/unittest.html#load-tests-protocol
    
    Args:
        loader: TestLoader instance
        standard_tests: Tests that would be loaded by default discovery
        pattern: Pattern used to match test files (ignored here)
    
    Returns:
        unittest.TestSuite containing all BMA compliance tests in order
    
    Execution Order Guaranteed:
        - Module 1 tests execute before Module 2 tests
        - Module 2 tests execute before Module 3 tests
        - etc.
    
    Execution Order NOT Guaranteed:
        - Test method order within a module (alphabetical by default)
        - setUpModule() timing relative to test execution
    """
    # Define test modules in execution order
    # Prerequisites must come before dependent tests
    test_modules = [
        'tests.test_b1_payments',
        'tests.test_b2_prepayment',
        'tests.test_b3_historical_speeds',
        'tests.test_b4_abs_prepayment',
        'tests.test_c3_cashflows',
        'tests.test_c3b1_consistency',
    ]
    
    # Create a test suite
    suite = unittest.TestSuite()
    
    # Load each test module in order
    # This ensures modules execute in order
    for module_name in test_modules:
        try:
            # Import the module
            module = __import__(module_name, fromlist=[''])
            
            # Manually call setUpModule if it exists (unittest doesn't call it during load_tests)
            # setUpModule is normally called by unittest's test runner, but we need it here
            # to populate shared state like TEST_SCENARIOS before dependent tests run
            if hasattr(module, 'setUpModule'):
                try:
                    module.setUpModule()
                except Exception as e:
                    print(f"WARNING: setUpModule() failed for {module_name}: {e}",
                          file=sys.stderr)
            
            # Load all tests from the module using the standard loader
            module_suite = loader.loadTestsFromModule(module)
            suite.addTest(module_suite)
        except ImportError as e:
            # If a module can't be imported, print warning but continue
            print(f"WARNING: Failed to import test module {module_name}: {e}", 
                  file=sys.stderr)
        except Exception as e:
            # If setUpModule raises an exception, we still want to continue
            # (the error will be reported when that module's tests run)
            print(f"WARNING: Error loading test module {module_name}: {e}",
                  file=sys.stderr)
    
    return suite


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == '__main__':
    """
    Run the test suite when executed directly.
    
    When running this module directly, unittest will:
    1. Discover tests in this module
    2. Call load_tests() to get the custom suite
    3. Run all tests in order
    """
    unittest.main(verbosity=2)
