# Day-clustered re-measurement of the headline tables (2026-08-01)

`backtest_day_clustered.py`. 702 stocks, 2021-07-30 → 2026-07-29, 6-day horizon, non-overlapping
entries, costs charged. Each day's strategy mean tested against the **same day's** random-entry
control.

**Why:** every published z-score treats each trade as an independent observation. The 2026-07
correction fixed overlap *within* a stock. It was never corrected *across* stocks — on a day the
market is broadly oversold, hundreds of names trigger together and share one market factor.

## What changed

| Segment | Published z | **z_paired** | Verdict change |
|---|---|---|---|
| Small-cap | 7.03 | **2.74** | holds, much weaker |
| Mid-cap | 5.20 | **1.73** | ✅ Real → ⚠️ **weak** |
| Large-cap | 0.55 | **−0.04** | already excluded, confirmed |
| Uptrend (>+20% 1yr) | 7.58 | **2.05** | holds, barely |
| Flat/Mild | 5.42 | **4.41** | holds well |
| Downtrend (<−20% 1yr) | 3.18 | **0.71** | ⚠️ Real but thin → ❌ **gone** |

Chronological attribution (live universe):

| Period | net/trade | z_paired |
|---|---|---|
| 2021-10 → 2022-12 | +0.593% | 1.65 |
| 2022-12 → 2024-09 | +0.948% | 1.67 |
| 2024-09 → 2025-02 | +0.763% | 3.20 |
| 2025-02 → 2025-12 | +0.937% | 1.49 |
| 2025-12 → 2026-07 | −0.795% | −0.57 |

## What survived intact

- **Oversold depth is still monotonic in net/trade**: RSI<24 +1.17%, 24–26 +0.77%, 26–28 +0.50%,
  28–30 +0.27%, 30–35 +0.10%. The gradient is the claim, and it holds. (The z_paired values
  across bands are noisy and non-monotonic — read the returns, not the z's.)
- **The ≥₹25cr liquidity filter still earns its place**: z_paired 3.28 filtered vs 2.64
  unfiltered, net/trade +0.531% vs +0.247%.
- **The recent-period collapse is confirmed**, and is not an artefact of the naive test.

## The ordering that flips

The README calls Uptrend the strongest tier. Under day-clustering **Flat/Mild is the more
statistically reliable one** (4.41 vs 2.05), even though Uptrend still has the higher point
estimate (+1.225% vs +0.589% net/trade).

Both statements can be true: Uptrend earns more per trade but fires on fewer days (306 vs 431)
with fewer trades per day, so its day-means are noisier. Treat this as "Uptrend is higher-return
but less certain", not "Flat is better". `scan_watchlist_text_short` sorts Uptrend first; nothing
here justifies changing that ordering, but the confidence gap should not be presented as
Uptrend being both higher-returning *and* more reliable.

## Limits of this test

- **The paired test loses power when a strategy fires on few names per day.** A day with 2
  trades has a noisy day-mean. Mid-cap (3.1 trades/day) is penalised more than Small-cap
  (7.8/day) for reasons that are partly statistical power, not absence of edge. Mid-cap's drop
  to 1.73 should be read as "no longer demonstrated", not "disproven".
- **Not search-adjusted.** Table 3 and Table 5 rows subdivide one dataset, so individual
  z-scores carry multiplicity not accounted for here.
- Day-clustering is the *conservative* bound; the truth sits between it and the trade-level
  number. It is the right default precisely because the optimistic version has already been
  wrong twice on this project.
