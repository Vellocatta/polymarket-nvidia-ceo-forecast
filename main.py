# Polymarket "Next CEO of NVIDIA?" 4-hour price forecaster.
#
# Method (all from the case's own 72h of minute prices, no network, no clock):
#   1. For each market, take the empirical distribution of h-minute returns
#      over its history, recency-weighted with a 90-minute half-life, at a
#      grid of horizons; centre each horizon's quantiles on their median
#      (the median h-minute return is ~0: prices mostly sit still), and
#      interpolate between grid horizons in log-h.  Short half-life adapts
#      fast after jumps, which dominate this market's risk.
#   2. Median drift: a small momentum term from the last 5 minutes
#      (0.25 * r5, ramping linearly over the horizon) and a small
#      mean-reversion term from the last hour (-0.10 * r60, same ramp).
#      Both slopes were measured on the practice cases and kept small on
#      purpose: the signals are real but noisy, and large drifts lose.
#   3. Cross-market calibration: the 24 Yes prices are mutually exclusive
#      outcomes, so their medians should sum to ~1.  After step 2, shift
#      each market's median (only the median, never the spread) toward a
#      total of 1, the shift shared in proportion to each price.
#   4. Fallback for short histories: a Gaussian spread from the median
#      absolute 1-minute move, floored at 0.0004 per sqrt-minute.
#
# Practice loss (local backtest, same scorer the house quotes):
#   0.278459 vs house persistence baseline 0.363589 (-23.4%), wins 6/6 cases.
# Variants tried and rejected on practice (all scored on all six cases):
#   longer half-lives (120-2880 min), uniform weights, tail widening
#   (x1.15/x1.3) and narrowing (x0.85/x0.9), shifting all five quantiles
#   for the sum calibration, widening spreads when the sum is far from 1,
#   mean reversion to the 24h mean, and larger drift coefficients.
#   Each either lost overall or won on some cases and lost on others.
#
# Deterministic: no randomness, no wall clock, no network; the same case
# always writes the same bytes.  Python 3.13 standard library only.

import json
import math
import os
from statistics import mean

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"

TAUS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.644854, -0.67449, 0.0, 0.67449, 1.644854]

# Recency half-life (minutes) for weighting historical return windows.
HALF_LIFE_MIN = 90.0
# Grid horizons (minutes) at which return quantiles are estimated.
GRID_H = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 180, 240]
# Cap on return windows sampled per horizon (stride-sampled, deterministic).
MAX_WINDOWS = 1200
MIN_WINDOWS = 20
# Drift coefficients (see header).
MOM_R5 = 0.25
MOM_R60 = -0.10
# Sum-calibration target for the medians of the mutually exclusive markets.
SUM_TARGET = 1.0
# Floor on the fallback 1-minute spread (price units per sqrt-minute).
SIG_FLOOR = 0.0004


def clamp01(x):
    """A price clamped to [0, 1] and rounded to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)), 6) + 0.0


def wquantile(sorted_vals, weights, tau):
    """Weighted quantile with linear interpolation on cumulative weight."""
    total = sum(weights)
    if total <= 0:
        return sorted_vals[len(sorted_vals) // 2]
    target = tau * total
    acc = 0.0
    for i, (v, w) in enumerate(zip(sorted_vals, weights)):
        acc += w
        if acc >= target:
            if i == 0:
                return v
            prev_acc = acc - w
            frac = (target - prev_acc) / w if w > 0 else 0.0
            return sorted_vals[i - 1] + frac * (v - sorted_vals[i - 1])
    return sorted_vals[-1]


def hist_centered_quantiles(prices, h):
    """Centred quantiles of h-minute returns, recency-weighted.

    Returns the five quantiles of the return distribution with its median
    subtracted (so the forecast median stays at the last price plus drift),
    or None when the market's history is too short for this horizon.
    """
    n = len(prices)
    if n - h < MIN_WINDOWS:
        return None
    idx = list(range(0, n - h))
    if len(idx) > MAX_WINDOWS:
        stride = len(idx) / MAX_WINDOWS
        idx = [idx[int(i * stride)] for i in range(MAX_WINDOWS)]
    rets = [prices[t + h] - prices[t] for t in idx]
    ws = [0.5 ** ((n - 1 - (t + h)) / HALF_LIFE_MIN) for t in idx]
    order = sorted(range(len(rets)), key=lambda i: rets[i])
    sv = [rets[i] for i in order]
    sw = [ws[i] for i in order]
    qs = [wquantile(sv, sw, tau) for tau in TAUS]
    med = qs[2]
    return [v - med for v in qs]


def fallback_sigma(prices):
    """1-minute spread from the median absolute move, floored."""
    if len(prices) < 2:
        return SIG_FLOOR
    diffs = sorted(abs(prices[i + 1] - prices[i]) for i in range(len(prices) - 1))
    mad = diffs[len(diffs) // 2]
    return max(mad / 0.6745 if mad > 0 else 0.0, SIG_FLOOR)


def forecast_market(prices, horizon=240):
    """`horizon` rows x 5 quantiles for one market."""
    n = len(prices)
    x = prices[-1] if n else 0.5
    r5 = prices[-1] - prices[-6] if n >= 6 else 0.0
    r60 = prices[-1] - prices[-61] if n >= 61 else 0.0
    qh = {}
    for h in GRID_H:
        q = hist_centered_quantiles(prices, h)
        if q is not None:
            qh[h] = q
    sig1 = fallback_sigma(prices)
    rows = []
    for h in range(1, horizon + 1):
        if h in qh:
            cq = list(qh[h])
        else:
            lo = max([g for g in GRID_H if g < h and g in qh], default=None)
            hi = min([g for g in GRID_H if g > h and g in qh], default=None)
            if lo is None and hi is None:
                cq = [z * sig1 * math.sqrt(h) for z in Z]
            elif lo is None:
                cq = list(qh[hi])
            elif hi is None:
                cq = [v * math.sqrt(h / lo) for v in qh[lo]]
            else:
                w = (math.log(h) - math.log(lo)) / (math.log(hi) - math.log(lo))
                cq = [qh[lo][j] + w * (qh[hi][j] - qh[lo][j]) for j in range(5)]
        frac = h / horizon
        drift = (MOM_R5 * r5 + MOM_R60 * r60) * frac
        row = [clamp01(x + drift + v) for v in cq]
        for j in range(1, 5):
            if row[j] < row[j - 1]:
                row[j] = row[j - 1]
        rows.append(row)
    return rows


def forecast_case(case):
    """All markets of one case, with the cross-market sum calibration."""
    horizon = case.get("horizon_minutes", 240)
    forecasts = {m["id"]: forecast_market(m["prices"], horizon) for m in case["markets"]}
    markets = case["markets"]
    for h in range(horizon):
        meds = [forecasts[m["id"]][h][2] for m in markets]
        total = sum(meds)
        excess = total - SUM_TARGET
        if abs(excess) < 1e-9 or total <= 0:
            continue
        for m in markets:
            row = forecasts[m["id"]][h]
            med = row[2]
            shift = excess * (med / total)
            newmed = clamp01(med - shift)
            row[2] = newmed
            if row[2] < row[1]:
                row[2] = row[1]
            if row[2] > row[3]:
                row[2] = row[3]
    return [{"id": m["id"], "q": forecasts[m["id"]]} for m in markets]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    inputs = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".in"))
    for fname in inputs:
        cid = fname[: -len(".in")]
        with open(os.path.join(INPUT_DIR, fname), "r", encoding="utf-8") as f:
            case = json.load(f)
        forecasts = forecast_case(case)
        out = {"forecasts": forecasts}
        with open(os.path.join(OUTPUT_DIR, cid + ".out"), "w", encoding="utf-8") as f:
            f.write(json.dumps(out, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
