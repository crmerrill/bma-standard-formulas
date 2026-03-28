# CRT File Layout and Glossary (Reference)

This project consumes Fannie Mae CRT / Single-Family Loan Performance sample tapes
using `read_loan_tape(..., column_map=...)`.

Source reference used for mapping:

- *Single-Family Loan Performance Dataset and Credit Risk Transfer - Glossary and File Layout* (Fannie Mae, 2024)
- Local PDF copy: `docs/reference/crt-file-layout-and-glossary-1.pdf`

---

## Fields Used by Engine Ingestion

The CRT data dictionary contains many fields. The engine currently maps a focused
subset required for loan cashflow runs:

| CRT Header | Meaning (dictionary) | Engine Canonical Field |
|---|---|---|
| `int` | Reference Pool ID | `group_id` |
| `loan` | Loan Identifier | `loan_id` |
| `month` | Monthly Reporting Period | `asof_date` |
| `odate` | Origination Date | `origination_date` |
| `current_interest_rate` | Current Interest Rate | `rate_margin` |
| `original_upb` | Original UPB | `original_balance` |
| `current_upb` | Current Actual UPB | `current_balance` |
| `original_term` | Original Loan Term | `original_term` |
| `remaining_legal_term` | Remaining Months to Legal Maturity | `remaining_term` |
| `remaing_term` | Sample-header typo variant of remaining term | `remaining_term` |

Notes:

- `read_loan_tape` is the only ingestion function; dataset-specific behavior is passed via `column_map`.
- If two source columns map to the same canonical field (for example `remaining_legal_term` and `remaing_term`), the parser collapses duplicates deterministically from left to right.

---

## Example: Generic Reader with CRT Map

```python
import pandas as pd
from bma_standard_formulas.engine import (
    CRT_FILE_LAYOUT_COLUMN_MAP,
    read_loan_tape,
)

df = pd.read_csv("sample_crt_tape.csv")
loans = read_loan_tape(df, column_map=CRT_FILE_LAYOUT_COLUMN_MAP)
```
