# Post-earnings-miss as a safety filter — measured, REJECTED (2026-08-15)

`backtest_pead.py`. The question behind the earnings red flag: when the RSI<30 scan surfaces an
oversold stock that recently reported **bad earnings**, is it a falling knife to skip?

Historical earnings *numbers* are not cached, so the "miss" is the market's own **price reaction**
to the last results filing (`close(t-1) -> close(t+2)`): a stock that dropped hard on its last
results IS the miss, revealed by price — arguably a better signal than a raw YoY number, since it
is the market's verdict. Results dates come from the 369k news archive; reaction and forward
returns from the 5y panel. Entry/exit/costs reuse `backtest_engine.simulate_trades` unchanged
(close entry, 6-day hold, 4x ATR stop, costs, non-overlapping). Control = random Mid/Small entries
through the same machinery. Headline stat = day-clustered `z_paired`.

## Verdict: REJECTED. Bad-earnings oversold names do NOT underperform — if anything they revert better.

Across all six lookback × "miss"-threshold specs, post-bad-earnings names never underperformed the
rest of the RSI<30 cohort day-paired, and on their own carried a strong edge:

| Lookback / miss | post-bad n | post-bad day-edge (z_paired) | FILTER: post-bad vs rest (z_paired) |
|---|---|---|---|
| 10 bars / ≤0%  | 487  | +0.28% (0.96) | −0.07% (**−0.19**) |
| 10 bars / ≤−5% | 270  | +1.13% (3.17) | +0.76% (+1.80) |
| 20 bars / ≤0%  | 881  | +0.63% (2.54) | +0.53% (+1.59) |
| 20 bars / ≤−5% | 446  | +1.09% (3.42) | +0.91% (**+2.38**) |
| 40 bars / ≤0%  | 1504 | +0.52% (2.75) | +0.20% (+0.74) |
| 40 bars / ≤−5% | 685  | +0.95% (3.52) | +0.53% (+1.68) |

Baseline all-RSI<30: +0.69%/trade, z_paired 2.42 (consistent with the README small/mid range, so
the harness is sound). The FILTER column is null-to-positive everywhere. Economic read: an oversold
reading *caused by* a sharp earnings-driven drop is exactly the overreaction mean-reversion exploits.

## The methodology note that matters

**Before** fixing a look-ahead bug, the 10-bar/≤0% cell showed FILTER z_paired **−1.94** — it
"confirmed" the falling-knife intuition. The bug: the reaction window (`close(t+2)`) peeked past the
entry bar for trades entering 1–2 bars after a filing. Requiring entry to fall strictly after the
reaction window closed (`i - idx > REACTION_K`) flipped every cell from negative to null/positive.
Textbook case of a strong-looking result collapsing under a correctness fix — the fourth time on
this project.

## What this changes

- The **earnings red flag** (`earnings_red_flag` in `tools.py`, added the same day) has no measured
  basis and its premise is rejected by a better proxy than it uses. Do not harden it; remove or
  neutralise it — a "red flag" on trades that revert fine is actively misleading.
- The sustained-decline falling knife (INOXWIND to 52-week lows) is already handled by the
  **Downtrend-tier FAIL** (z 0.71). A separate earnings gate is redundant.
- Weak/secondary: oversold *after a good* earnings reaction reverted best (z ~2.5–3.0), but small n
  and not the question asked — not adopted.
- The dilution filter is unaffected — it is a *filing-type* signal (z_paired −3.34), separately
  validated, and stands.
