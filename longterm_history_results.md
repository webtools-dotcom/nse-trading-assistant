# Long-term momentum over the full Yahoo history (2026-09-25)

Panel: `python build_backtest_panel_long.py max` → `cache/backtest_max_long.pkl` (748/748 stocks,
bars from 1996). With the ₹25cr/day liquidity floor and ≥40 liquid names per date, rankable
rebalances start **2014-06**. Method as `backtest_longterm_exits.py`: one rebalance every 20
sessions, all 20 offsets, next-open entry, 20d hold, costs charged, top quartile vs universe paired.

    LONG_PANEL=cache/backtest_max_long.pkl python backtest_longterm_history.py
    LONG_PANEL=cache/backtest_max_long.pkl LONG_END=2021-08-12 python backtest_longterm_<exits|recheck|marketstate>.py

## Headline — the basket's edge
| era | months | edge/month | z_paired median (range) | offsets ≥ 2 |
|---|---|---|---|---|
| **ALL 2014-06 → 2026-08** | 139 | **+0.75%** | **3.29** (2.63..3.79) | 20/20 |
| 2014 → 2016 | 14 | +1.40% | 1.65 | 3/20 |
| 2016 → 2021-08 | 63 | +0.69% | 1.76 | 5/20 |
| 2021-08 → 2026 | 62 | +0.62% | 2.14 | 16/20 |

Positive in every era, similar size. **Demonstrated at the pooled level**, which the 5y panel alone
could not do. Basket still loses money in ~39% of months.

**Biases (both inflate, size unknown):** survivorship — only today's listed names; delisted
collapses are missing. Cap bucket is today's. Treat +0.75%/month as an upper-ish estimate.

## Out-of-sample re-run of this session's tests (2014-06 → 2021-08, never seen before)
| test | 2021-26 result | 2014-21 out-of-sample | verdict |
|---|---|---|---|
| −8% stop + 16% target | −1.70%/trade, z −3.39 | −1.05%/trade, z −2.40; hurt 3/5 periods, helped in 2018-20 slump | **harmful — confirmed** |
| −8% stop only | −1.53%, z −3.65 | −0.89%, z −2.46 | confirmed |
| low-atr% vs high-atr% | −0.81%/month | −0.03%, z −0.05; tail 1.8% vs 4.2% | risk dial, no return edge |
| top 20 vs rest | +0.69%, z 1.40 | uninformative (~104 liquid names/date → top 20 ≈ whole quartile) | unchanged |
| smooth vs jumpy (frog) | −1.03%, z −2.20 | **+0.96%, z 1.97** | flips sign by era → noise, stays rejected |
| Nifty 12M < 0 gate | failed | DOWN edge −0.52% vs UP +1.11% (literature direction) but z 0.31, and basket made +3.84% in DOWN months | **fails again** |

Worst basket months 2014-21 (−12% to −17%): 2015-04, 2020-03, 2020-02, 2018-09, 2018-01 — Nifty
12M was positive at every one. Same pattern as 2021-26: momentum crashes when a rising market turns.
