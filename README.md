# NVIDIA CEO price forecaster — make.fun entry

Forecasts Polymarket's "Next CEO of NVIDIA?" Yes prices minute by minute,
4 hours ahead, as five quantiles (5%, 25%, 50%, 75%, 95%) per market per
minute. Entry for
[polymarket-nvidia-ceo-forecast-01](https://make.fun/competitions/polymarket-nvidia-ceo-forecast-01).

## Method

`main.py` (Python 3.13, standard library only) reads one case file
(`/input/<id>.in`: 72h of 1-minute Yes prices per market up to a checkpoint)
and writes `/output/<id>.out`. For each market:

1. **Historical simulation.** Empirical quantiles of h-minute returns over
   the market's own history, recency-weighted with a 90-minute half-life,
   at horizons 1–240 min, centred on their median (the median h-minute
   return is ~0 — these prices mostly sit still), interpolated in log-h.
   A short half-life adapts fast after jumps, which dominate this market's
   risk (a 20-point move in one minute happens).
2. **Median drift.** Small momentum from the last 5 minutes
   (0.25 × r5) plus small mean reversion from the last hour
   (−0.10 × r60), both ramping linearly over the 240-minute horizon.
   Both slopes were measured on the practice cases and kept small on
   purpose: the signals are real but noisy, and larger drifts lose.
3. **Cross-market calibration.** The 24 Yes prices are mutually exclusive
   outcomes, so their medians should sum to ~1. After step 2, each
   market's median — only the median, never the spread — is shifted toward
   a total of 1, the shift shared in proportion to each price.
4. **Fallback.** For short histories, a Gaussian spread from the median
   absolute 1-minute move, floored at 0.0004 per sqrt-minute.

Deterministic (no randomness, no clock, no network): the same case always
writes the same bytes. ~0.5 s per case, well inside the 8 s cap.

## Practice results (local backtest on the kit's six practice cases)

| model | loss |
|---|---|
| House persistence baseline | 0.363589 |
| This entry | **0.278459** (−23.4%, wins 6/6 cases) |

The local scorer reproduces the house baseline's published practice loss
exactly (0.363589), so the comparison is like-for-like. Median error
0.73, 90% coverage 0.81.

## Variants tried and rejected (all scored on all six practice cases)

- Longer half-lives (120–2880 min) and uniform (unweighted) history: worse.
- Tail widening (×1.15, ×1.3) and narrowing (×0.85, ×0.9): worse, or a
  hair better at the cost of much lower coverage — rejected for robustness
  on the 48-hour final.
- Shifting all five quantiles for the sum calibration (instead of the
  median only): much worse (0.295).
- Widening spreads when the sum is far from 1: worse.
- Mean reversion to the 24h mean, and larger drift coefficients: worse or
  inconsistent across cases.

## License

MIT — see `LICENSE`.
