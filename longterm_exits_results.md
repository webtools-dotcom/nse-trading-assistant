# Long-term exits — the −8% stop / +16% target (2026-09-24)

`python backtest_longterm_exits.py` · Mid/Small liquid (≥₹25cr), 12M-1M momentum rank, entry next
session's open, costs charged, 5y panel to 2026-08-12. **Non-overlapping**: one rebalance every 20
sessions (49 rebalances), repeated over all 20 start offsets.

## Verdict
- **Fixed −8% stop: REJECTED, harmful.** −1.53%/trade vs plain 20d hold, z_paired −3.65 (offset
  median −2.55), worse in 5/5 periods. Live stop+target −1.70%, z −3.39.
- **+16% target alone:** −0.24%, z −0.97 — not significant, removed with the stop.
- **Stop's upside:** P(trade < −20%) 3.1% → 0.2%, 10th pct −13.0% → −8.5%. That is the price of
  the −1.5%: a 1–2 name holder may still choose it, the tool no longer calls it validated.
- **60d vs 3×20d:** quartile +0.95 / +0.63 / +1.54% per 60d (z 1.28 / 0.75 / 2.43), top-20 ≈ 0.
  Inconclusive; plausibly just 1 round trip of costs instead of 3.

## Side finding — headline re-measured
Top quartile vs universe, monthly non-overlapping: edge median **+0.60%/month, z_paired 1.94**
(1.32–2.73, 9/20 offsets ≥ 2). Top 20: +0.98%/month, z 1.80. Same data, every-day entries: z 8.94
/ 8.04 — ~4.6× overlap inflation. The basket is positive, not firmly demonstrated.

| basket | variant | mean | median | P<−20% | 10th pct | vs none | z_paired |
|---|---|---|---|---|---|---|---|
| quartile | none | +1.39% | +0.18% | 3.1% | −13.0% | | |
| quartile | stop8 | −0.14% | −6.23% | 0.2% | −8.5% | −1.53% | −3.65 |
| quartile | tgt16 | +1.20% | +0.70% | 3.1% | −12.9% | −0.24% | −0.97 |
| quartile | live | −0.26% | −5.46% | 0.2% | −8.5% | −1.70% | −3.39 |
| top 20 | none | +2.19% | +0.87% | 4.9% | −14.2% | | |
| top 20 | live | +0.12% | −8.50% | 0.1% | −8.5% | −2.06% | −3.03 |
