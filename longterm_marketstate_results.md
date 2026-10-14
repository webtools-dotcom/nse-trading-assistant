# Long-term market-state gate (2026-09-25)

`python backtest_longterm_marketstate.py` · top-quartile momentum basket, monthly non-overlapping
(49 rebalances, 20 offsets), entry next open, 20d hold, costs charged. Nifty from Yahoo (^NSEI).

**Pre-registered:** DOWN = Nifty 50 trailing 12M return < 0 at the signal date. Pass needs a lower
edge in DOWN months (Welch z ≥ 2) AND a basket return ≤ 0 in them.

| state | months | basket | universe | edge | months basket < 0 | worst |
|---|---|---|---|---|---|---|
| UP | 44 | +1.41% | +0.87% | +0.54% | 36% | −13.1% |
| DOWN | 5 | **+2.88%** | +1.87% | +1.01% | 20% | −0.1% |

Welch z (UP edge − DOWN edge), median over offsets **0.52** (range −0.66..1.72), 4–10 DOWN months
per offset. **FAILED on both legs.** The gate would have sat out the basket's *better* months.

Worst five basket months: 2024-12-26 −13.1%, 2025-01-23 −9.5%, 2024-09-27 −9.4%, 2026-02-10 −8.1%,
2022-12-14 −8.0% — Nifty 12M was +5% to +30% at every one. In this 5-year Indian sample, momentum
lost money when a rising market turned (Sep 2024 → Jan 2025), not after a bear market. That is a
description of 5 months, not a tested rule; a "near-the-top" gate fitted to it would be curve-fitting.

The secondary state (Mid/Small equal-weight 12M-1M < 0) never fired (0–1 month per offset) — no
information.
