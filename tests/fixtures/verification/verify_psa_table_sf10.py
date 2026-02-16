"""
Verify 1m_PSAtoSMM_conversion.csv against BMA SF-10 formulas.

BMA SF-10: Conversion of One-Month PSA to SMM Based on Months after Mortgage Origination

This script:
1. INDEPENDENTLY generates a grid of PSA speeds (50 to 1000 in increments of 50) and months (1 to 30)
2. For each month i=1 to i=30, calculates SMMs for PSA = 50 to PSA = 1000
3. Loads the CSV file
4. Compares the independently generated matrix to the CSV table

The conversion process:
- PSA -> CPR: For months 1-30, CPR = 0.2% × month × (PSA/100); for months 31+, CPR = 6.0% × (PSA/100)
- CPR -> SMM: SMM = 1 - (1 - CPR/100)^(1/12)
"""

import csv
import math
from pathlib import Path

# Tolerance for comparison (SMM values in CSV are rounded to 2 decimal places)
TOLERANCE = 0.01  # 0.01% SMM tolerance


def psa_to_cpr(psa_speed, month):
    """Convert PSA speed to CPR using BMA formula.
    
    BMA Formula:
    - Months 1-30: CPR = 0.2% × month × (PSA/100)
    - Months 31+: CPR = 6.0% × (PSA/100)
    """
    if month <= 30:
        cpr = 0.2 * month * (psa_speed / 100.0)
    else:
        cpr = 6.0 * (psa_speed / 100.0)
    return min(cpr, 100.0)  # Cap at 100%


def cpr_to_smm(cpr_pct):
    """Convert CPR (annual %) to SMM (decimal) using BMA formula.
    
    BMA Formula: SMM = 1 - (1 - CPR/100)^(1/12)
    """
    cpr_decimal = cpr_pct / 100.0
    smm = 1.0 - (1.0 - cpr_decimal) ** (1.0 / 12.0)
    return smm


def generate_psa_to_smm_matrix(months, psa_speeds):
    """Generate PSA to SMM conversion matrix independently using BMA formulas.
    
    Args:
        months: List of months (e.g., [1, 2, ..., 30])
        psa_speeds: List of PSA speeds (e.g., [50, 100, 150, ...])
    
    Returns:
        Dictionary: {month: {psa_speed: smm_pct}}
    """
    matrix = {}
    
    for month in months:
        matrix[month] = {}
        for psa_speed in psa_speeds:
            # Calculate SMM: PSA -> CPR -> SMM
            cpr = psa_to_cpr(psa_speed, month)
            smm_decimal = cpr_to_smm(cpr)
            smm_pct = smm_decimal * 100.0  # Convert to percent
            matrix[month][psa_speed] = smm_pct
    
    return matrix


def load_psa_to_smm_table(csv_path):
    """Load the PSA to SMM conversion table from CSV."""
    table = {}  # {month: {psa_speed: smm_pct}}
    
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
                month = int(row['Month'])
                table[month] = {}
                for col_name in row.keys():
                    if col_name.startswith('PSA'):
                        psa_speed = int(col_name.replace('PSA', ''))
                        smm_pct = float(row[col_name])
                        table[month][psa_speed] = smm_pct
            except (ValueError, KeyError) as e:
                print(f"Warning: Skipping row due to error: {e}")
                continue
    
    return table


def compare_matrices(generated_matrix, csv_table):
    """Compare CSV table to independently generated matrix.
    
    The generated matrix (from formulas) is and alternative source of truth.
    We verify that CSV entries match the generated values.
    Iterates over CSV table and checks each entry against generated matrix.
    """
    errors = []
    
    # Iterate over CSV table (what we're verifying)
    for month, csv_row in csv_table.items():
        # Check if month exists in generated matrix
        if month not in generated_matrix:
            errors.append(
                f"Month {month}: Found in CSV but not in generated matrix (CSV may have extra months)"
            )
            continue
        
        generated_row = generated_matrix[month]
        
        # Iterate over PSA speeds in CSV row
        for psa_speed, csv_smm in csv_row.items():
            # Check if PSA speed exists in generated matrix
            if psa_speed not in generated_row:
                errors.append(
                    f"Month {month}, PSA {psa_speed}: Found in CSV but not in generated matrix (CSV may have extra PSA speeds)"
                )
                continue
            
            # Compare CSV value to generated value
            generated_smm = generated_row[psa_speed]
            diff = abs(generated_smm - csv_smm)
            
            if diff > TOLERANCE:
                errors.append(
                    f"Month {month}, PSA {psa_speed}: "
                    f"CSV has {csv_smm:.2f}%, but formula generates {generated_smm:.6f}% "
                    f"(diff: {diff:.6f}%)"
                )
    
    return errors


def main():
    """Main verification function."""
    # Path to CSV file
    script_dir = Path(__file__).parent
    csv_path = script_dir.parent / '1m_PSAtoSMM_conversion.csv'
    
    print("=" * 80)
    print("BMA SF-10 Verification: PSA to SMM Conversion Table")
    print("=" * 80)
    print(f"CSV file: {csv_path}")
    print()
    
    # STEP 1: Generate matrix independently
    print("STEP 1: Generating matrix independently using BMA formulas...")
    months = list(range(1, 31))  # Months 1 to 30
    psa_speeds = list(range(50, 1050, 50))  # 50, 100, 150, ..., 1000
    print(f"  Months: {min(months)} to {max(months)}")
    print(f"  PSA speeds: {psa_speeds}")
    
    generated_matrix = generate_psa_to_smm_matrix(months, psa_speeds)
    print(f"  Generated {len(months)} months × {len(psa_speeds)} PSA speeds = "
          f"{len(months) * len(psa_speeds)} entries")
    print()
    
    # STEP 2: Load CSV table
    print("STEP 2: Loading CSV table...")
    try:
        csv_table = load_psa_to_smm_table(csv_path)
        print(f"  Loaded {len(csv_table)} months from CSV")
    except Exception as e:
        print(f"ERROR: Failed to load CSV: {e}")
        return 1
    print()
    
    # STEP 3: Compare matrices
    print("STEP 3: Verifying CSV table against generated matrix...")
    print("  (Generated matrix from formulas is source of truth)")
    print("  (Checking if CSV entries match generated values)")
    print()
    
    errors = compare_matrices(generated_matrix, csv_table)
    
    # Report results by month
    csv_months = sorted(csv_table.keys())
    for month in csv_months:
        month_errors = [e for e in errors if e.startswith(f"Month {month},")]
        if month_errors:
            print(f"Month {month}: {len(month_errors)} error(s)")
        else:
            print(f"Month {month}: OK")
    
    print()
    print("=" * 80)
    
    if errors:
        print(f"FAILED: {len(errors)} error(s) found")
        print()
        print("First 20 errors:")
        for error in errors[:20]:
            print(f"  {error}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more errors")
        return 1
    else:
        print("PASSED: All verifications successful!")
        print(f"Verified {len(months)} months × {len(psa_speeds)} PSA speeds")
        return 0


if __name__ == '__main__':
    exit(main())
