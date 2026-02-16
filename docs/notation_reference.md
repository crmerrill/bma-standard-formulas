# BMA Notation Reference

## B.1: The M₀ and M Notation

**From BMA B.1 (SF-3):**

> "For a level-payment fixed-rate mortgage pool with gross weighted-average coupon C%, 
> current weighted-average remaining term M months, and **M0-M months elapsed since 
> origination**, the amortized loan balance (as a fraction of par) is..."

This tells us:
- **M₀** = original term (remaining term at origination)
- **M** = current remaining term
- **M₀ - M** = months elapsed = **AGE**

Therefore, **Mₙ notation uses n as the AGE index**:
- M₀ = remaining term at age 0 = original term
- Mₙ = remaining term at age n = M₀ - n

## SF-6: AGE is 0-indexed

**From BMA SF-6:**

> "For expositional purposes, AGE is defined as a point in time, whereas MONTH is
> defined as a span of time. Pool factors therefore are reported as of an AGE whereas
> prepayment rates are reported for a MONTH. When a mortgage loan is originated, 
> AGE = 0. After MONTH=1, AGE = 1."

```
|----Month 1----|----Month 2----|----Month 3----|----Month 4----|
^               ^               ^               ^               ^
AGE=0          AGE=1          AGE=2          AGE=3          AGE=4
(origination)
```

- **AGE** = point in time (pool factors reported as of an AGE)
- **MONTH** = span of time (prepayment rates reported for a MONTH)

**AGE is 0-indexed.** The subscript n in Mₙ equals AGE.

## The Simple Relationship

```
Mₙ = M₀ - n

where:
  n = AGE (0-indexed)
  M₀ = original term
  Mₙ = remaining term at age n
```

That's it. The subscript is the age.

## Period Indexing (for tests and projections)

When observing a loan at some point in time:

```
i = period index (0-indexed from observation)
age(i) = start_age + i    (age at END of period i)
M(i) = rem_term - i       (remaining_term at age(i))
```

**Key relationships:**
- **age(0)** = start_age = orig_term - rem_term (observation point, END of period 0)
- **Period i** spans from age(i-1) to age(i)
- At **i = 0** with **start_age = 0**: boundary condition (balance = 1, am_factor = 0)
- At **i = rem_term**: age = orig_term, M = 0 (maturity)

**ALIGNED Vector indexing (both indexed by AGE):**
- `survival_vec[k]` = balance at age k
- `am_vec[k]` = am_factor at age k (for period ENDING at age k)
- `am_vec[0]` = 0 (no amortization to reach origination)

**Relationship:** `survival_vec[k] = survival_vec[k-1] * (1 - am_vec[k])` for k >= 1

**Example:** Loan observed at age 60 (rem_term = 300, orig_term = 360):
```
k=0:   survival_vec[0] = 1.0,  am_vec[0] = 0  (origination)
k=60:  survival_vec[60] = balance at age 60,  am_vec[60] = am_factor for period 60
...
k=360: survival_vec[360] = 0,  am_vec[360] = am_factor for final period
```
