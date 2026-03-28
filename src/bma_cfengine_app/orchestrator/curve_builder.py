from __future__ import annotations

import numpy as np

from ..api.models import (
    ConstantCurve,
    CurveSpec,
    PsaCurve,
    RampCurve,
    SdaCurve,
    VectorCurve,
)


def build_curve(spec: CurveSpec, horizon: int) -> np.ndarray:
    """Convert a CurveSpec into a numpy array of length ``horizon``."""
    if isinstance(spec, ConstantCurve):
        return np.full(horizon, spec.value, dtype=float)

    if isinstance(spec, VectorCurve):
        arr = np.array(spec.values, dtype=float)
        if len(arr) >= horizon:
            return arr[:horizon]
        return np.pad(arr, (0, horizon - len(arr)), constant_values=arr[-1])

    if isinstance(spec, PsaCurve):
        return _psa_smm_curve(spec.speed, horizon)

    if isinstance(spec, SdaCurve):
        return _sda_mdr_curve(spec.speed, horizon)

    if isinstance(spec, RampCurve):
        return curve_parser(spec.expression, output_length=horizon)

    raise ValueError(f"Unknown curve spec type: {type(spec)}")


# ---------------------------------------------------------------------------
# PSA / SDA standard curves
# ---------------------------------------------------------------------------


def _psa_smm_curve(speed_pct: float, horizon: int) -> np.ndarray:
    """100 PSA = CPR ramps 0.2% at month 1 to 6% at month 30, flat after."""
    base_cpr_30 = 6.0
    months = np.arange(1, horizon + 1, dtype=float)
    cpr_annual = np.where(
        months <= 30,
        (base_cpr_30 / 30.0) * months * (speed_pct / 100.0),
        base_cpr_30 * (speed_pct / 100.0),
    )
    cpr_decimal = cpr_annual / 100.0
    smm = 1.0 - (1.0 - cpr_decimal) ** (1.0 / 12.0)
    return smm


def _sda_mdr_curve(speed_pct: float, horizon: int) -> np.ndarray:
    """100 SDA = CDR ramps to 0.60% at month 30, flat to 60, declines to 120."""
    months = np.arange(1, horizon + 1, dtype=float)
    cdr_annual = np.piecewise(
        months,
        [
            months <= 30,
            (months > 30) & (months <= 60),
            (months > 60) & (months <= 120),
            months > 120,
        ],
        [
            lambda m: (0.60 / 30.0) * m,
            0.60,
            lambda m: 0.60 - (0.60 - 0.03) * (m - 60) / 60.0,
            0.03,
        ],
    )
    cdr_annual = cdr_annual * (speed_pct / 100.0)
    cdr_decimal = cdr_annual / 100.0
    mdr = 1.0 - (1.0 - cdr_decimal) ** (1.0 / 12.0)
    return mdr


# ---------------------------------------------------------------------------
# Ramp curve parser (vendored from tessera_engine/utilities/cashflowutils.py)
# ---------------------------------------------------------------------------


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def curve_parser(curve_string: str, output_length: int = 361) -> np.ndarray:
    """Parse a DSL string into a numeric curve array.

    Syntax (semicolon-separated segments):
      - ``"5"`` -- single value at next index
      - ``"5 for 12"`` -- hold value 5 for 12 periods
      - ``"5 ramp 10 for 30"`` -- linearly interpolate from 5 to 10 over 30 periods
      - ``"5 for 12 ramp 10 for 30"`` -- hold 5 for 12, then ramp to 10 over 30

    Index 0 is always zero. Remaining indices after all segments are filled
    with the last assigned value.

    Example::
        >>> curve_parser("5; 7 ramp 10 for 3", output_length=10)
        array([0., 5., 7., 8., 9., 10., 10., 10., 10., 10.])
    """
    curve = np.zeros(output_length, dtype=np.float64)
    i = 1

    for element in curve_string.split(";"):
        element = element.strip().lower()
        if not element:
            continue

        if _is_numeric(element):
            if i < output_length:
                curve[i] = float(element)
                i += 1
            continue

        j = 0
        k = 0
        left_time = -1
        ramp_time = -1
        ramp_interval = 0.0
        ramp_min = 0.0
        ramp_max = 0.0

        ramp_split = element.split("ramp")

        if len(ramp_split) > 1 and _is_numeric(ramp_split[0]) and _is_numeric(ramp_split[1]):
            ramp_min = float(ramp_split[0])
            ramp_max = float(ramp_split[1])
            ramp_time = int(ramp_split[1]) - int(ramp_split[0])
            if ramp_time != 0:
                ramp_interval = (ramp_max - ramp_min) / ramp_time

        elif _is_numeric(ramp_split[0].strip()) and len(ramp_split) > 1 and "for" in ramp_split[1]:
            ramp_min = float(ramp_split[0].strip())
            parts = ramp_split[1].split("for")
            ramp_max = float(parts[0].strip())
            ramp_time = int(parts[1].strip())
            if ramp_time != 0:
                ramp_interval = (ramp_max - ramp_min) / ramp_time

        elif "for" in ramp_split[0]:
            left_parts = ramp_split[0].strip().split("for")
            ramp_min = float(left_parts[0].strip())
            left_time = int(left_parts[1].strip())

            if len(ramp_split) > 1:
                right = ramp_split[1].strip()
                if "for" in right:
                    right_parts = right.split("for")
                    ramp_max = float(right_parts[0].strip())
                    ramp_time = int(right_parts[1].strip())
                elif _is_numeric(right):
                    ramp_max = float(right)
                    ramp_time = abs(int(float(right)) - int(ramp_min))
                else:
                    ramp_max = ramp_min
                    ramp_time = 0
                if ramp_time != 0:
                    ramp_interval = (ramp_max - ramp_min) / ramp_time
            else:
                ramp_max = ramp_min
                ramp_time = 0

        while k < left_time and i < output_length:
            curve[i] = ramp_min
            i += 1
            k += 1

        while j <= ramp_time and i < output_length:
            curve[i] = ramp_min + (j * ramp_interval)
            i += 1
            j += 1

    while i < output_length:
        curve[i] = curve[i - 1]
        i += 1

    return curve
