"""
Verify bma_prepay_rate_conversion_table.csv against BMA SF-9 formulas.

BMA SF-9: Prepayment Rate Conversion Table

This script:
1. INDEPENDENTLY generates tuples (SMM, CPR, PSA) for SMM from 0.05% to 9.0% in increments of 0.05%
2. For each SMM, calculates CPR and PSA (month 30)
3. Loads the CSV file
4. Compares the independently generated tuples to entries in the CSV table

The conversion process:
- SMM -> CPR: CPR = 100 × (1 - (1 - SMM)^12)
- CPR -> PSA at month 30: PSA = CPR × 500 / 30 = CPR × 100 / 6
"""

import csv
import math
from pathlib import Path

# Tolerance for comparisons
TOLERANCE_SMM = 0.001  # 0.001% SMM tolerance
TOLERANCE_CPR = 0.1    # 0.1% CPR tolerance
TOLERANCE_PSA = 1.0    # 1.0 PSA tolerance (PSA values are rounded)


def smm_to_cpr(smm_decimal):
    """Convert SMM (decimal) to CPR (annual %) using BMA formula.
    
    BMA Formula: CPR = 100 × (1 - (1 - SMM)^12)
    """
    cpr = 100.0 * (1.0 - (1.0 - smm_decimal) ** 12.0)
    return cpr


def cpr_to_psa(cpr_pct, month):
    """Convert CPR to PSA speed using BMA formula.
    
    BMA Formula:
    - Months 1-30: PSA = CPR × 500 / month
    - Months 31+: PSA = CPR × 100 / 6
    """
    if month <= 30:
        psa = cpr_pct * 500.0 / month
    else:
        psa = cpr_pct * 100.0 / 6.0
    return psa


def generate_prepay_tuples(smm_start, smm_end, smm_increment):
    """Generate prepayment conversion tuples independently using BMA formulas.
    
    Args:
        smm_start: Starting SMM percentage (e.g., 0.05)
        smm_end: Ending SMM percentage (e.g., 9.0)
        smm_increment: Increment for SMM percentage (e.g., 0.05)
    
    Returns:
        List of dictionaries: [{'smm_pct': float, 'cpr_pct': float, 'psa': float}, ...]
    """
    tuples = []
    
    smm = smm_start
    while smm <= smm_end + smm_increment / 2:  # Include endpoint with small tolerance
        # Convert SMM from percent to decimal
        smm_decimal = smm / 100.0
        
        # Calculate CPR from SMM
        cpr_pct = smm_to_cpr(smm_decimal)
        
        # Calculate PSA at month 30
        psa = cpr_to_psa(cpr_pct, month=30)
        
        tuples.append({
            'smm_pct': smm,
            'cpr_pct': cpr_pct,
            'psa': psa,
        })
        
        smm += smm_increment
    
    return tuples


def load_prepay_table(csv_path):
    """Load the prepayment rate conversion table from CSV."""
    table = []  # List of {smm_pct, cpr_pct, psa}
    
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    with open(csv_path, 'r') as f:
        lines = f.readlines()
        # Find header line (first non-comment line)
        header_idx = None
        for i, line in enumerate(lines):
            if not line.strip().startswith('#'):
                header_idx = i
                break
        
        if header_idx is None:
            raise ValueError("No header line found in CSV")
        
        reader = csv.DictReader(lines[header_idx:])
        for row in reader:
            try:
                entry = {
                    'smm_pct': float(row['SMM']),
                    'cpr_pct': float(row['CPR']),
                    'psa': float(row['PSA30']),  # CSV column is PSA30, but we store as psa
                }
                table.append(entry)
            except (ValueError, KeyError) as e:
                print(f"Warning: Skipping row due to error: {e}")
                continue
    
    return table




def compare_tuples(generated_tuples_dict, csv_table):
    """Compare CSV table to independently generated tuples.
    
    The generated tuples (from formulas) are the source of truth.
    We verify that CSV entries match the generated values.
    Iterates over CSV table and checks each entry against generated tuples.
    """
    errors = []
    verified_count = 0
    
    # Iterate over CSV table (what we're verifying)
    for csv_entry in csv_table:
        csv_smm = csv_entry['smm_pct']
        
        # Find matching generated tuple by SMM (within tolerance)
        matching_gen = None
        for gen_tuple in generated_tuples_dict.values():
            if abs(gen_tuple['smm_pct'] - csv_smm) <= TOLERANCE_SMM:
                matching_gen = gen_tuple
                break
        
        if matching_gen is None:
            errors.append({
                'type': 'missing',
                'csv': csv_entry,
                'message': f"CSV entry with SMM {csv_smm:.2f}% not found in generated tuples (CSV may have extra entries)"
            })
            continue
        
        # Compare values
        smm_diff = abs(csv_entry['smm_pct'] - matching_gen['smm_pct'])
        cpr_diff = abs(csv_entry['cpr_pct'] - matching_gen['cpr_pct'])
        psa_diff = abs(csv_entry['psa'] - matching_gen['psa'])
        
        if smm_diff > TOLERANCE_SMM or cpr_diff > TOLERANCE_CPR or psa_diff > TOLERANCE_PSA:
            errors.append({
                'type': 'mismatch',
                'generated': matching_gen,
                'csv': csv_entry,
                'diffs': {
                    'smm': smm_diff,
                    'cpr': cpr_diff,
                    'psa': psa_diff,
                }
            })
        else:
            verified_count += 1
    
    return errors, verified_count


def main():
    """Main verification function."""
    # Path to CSV file
    script_dir = Path(__file__).parent
    csv_path = script_dir.parent / 'bma_prepay_rate_conversion_table.csv'
    
    print("=" * 80)
    print("BMA SF-9 Verification: Prepayment Rate Conversion Table")
    print("=" * 80)
    print(f"CSV file: {csv_path}")
    print()
    
    # STEP 1: Generate tuples independently
    print("STEP 1: Generating tuples independently using BMA formulas...")
    smm_start = 0.05
    smm_end = 9.0
    smm_increment = 0.05
    
    generated_tuples_list = generate_prepay_tuples(smm_start, smm_end, smm_increment)
    # Convert to dict keyed by SMM for fast lookup
    generated_tuples_dict = {t['smm_pct']: t for t in generated_tuples_list}
    print(f"  Generated {len(generated_tuples_dict)} tuples")
    print(f"  SMM range: {smm_start}% to {smm_end}% (increment {smm_increment}%)")
    print()
    
    # STEP 2: Load CSV table
    print("STEP 2: Loading CSV table...")
    try:
        csv_table = load_prepay_table(csv_path)
        print(f"  Loaded {len(csv_table)} entries from CSV")
    except Exception as e:
        print(f"ERROR: Failed to load CSV: {e}")
        return 1
    print()
    
    # STEP 3: Compare tuples
    print("STEP 3: Verifying CSV table against generated tuples...")
    print("  (Generated tuples from formulas are source of truth)")
    print("  (Checking if CSV entries match generated values)")
    print()
    
    errors, verified_count = compare_tuples(generated_tuples_dict, csv_table)
    
    print("=" * 80)
    print(f"Verified: {verified_count} entries matched")
    print(f"Errors: {len(errors)} CSV errors found")
    print()
    
    if errors:
        missing_errors = [e for e in errors if e['type'] == 'missing']
        mismatch_errors = [e for e in errors if e['type'] == 'mismatch']
        
        if missing_errors:
            print("Missing entries in generated data (first 10):")
            for error in missing_errors[:10]:
                print(f"  {error['message']}")
            if len(missing_errors) > 10:
                print(f"  ... and {len(missing_errors) - 10} more")
            print()
        
        if mismatch_errors:
            print("CSV value mismatches (first 20):")
            for error in mismatch_errors[:20]:
                gen = error['generated']
                csv_entry = error['csv']
                diffs = error['diffs']
                print(
                    f"  SMM {csv_entry['smm_pct']:.2f}%: "
                    f"CSV has (CPR={csv_entry['cpr_pct']:.1f}%, PSA={csv_entry['psa']:.0f}), "
                    f"but formula generates (CPR={gen['cpr_pct']:.1f}%, PSA={gen['psa']:.0f}), "
                    f"Diffs (SMM={diffs['smm']:.4f}%, CPR={diffs['cpr']:.2f}%, PSA={diffs['psa']:.1f})"
                )
            if len(mismatch_errors) > 20:
                print(f"  ... and {len(mismatch_errors) - 20} more errors")
            print()
        
        print("FAILED: CSV table has errors")
        return 1
    else:
        print("PASSED: All CSV entries match generated values!")
        return 0


if __name__ == '__main__':
    exit(main())
