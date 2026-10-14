# Does sector strength improve the long-term momentum ranking?

**Question (2026-09-11):** the scan ranks purely on 12-month price momentum and never looks at
whether the stock's sector is running. Should "what's booming in the market" reorder the picks?

**Answer: NO — measured three different ways, all fail. Sector strength ships as DISPLAY ONLY.**

Script: `backtest_sector_rank.py`. Panel `cache/backtest_5y_long.pkl`, liquid Mid/Small, 20-day
hold, entry next session's open, costs charged, day-clustered (`z_paired`).

---

## Setup

Sector momentum = mean trailing 60-day return of the stock's same-industry peers in the liquid
universe, point-in-time. Industries with fewer than 5 peers that day are dropped, not averaged
into noise.

Two taxonomies, competing **on the same stock-days** so a difference is the taxonomy and not the
sample:

| | labels | example |
|---|---|---|
| `nse` — macro sector already in the watchlist CSV | 20 | "Capital Goods" = 113 stocks, cement machinery to shipyards |
| `gics` — yfinance industry, new (`build_industry_map.py`) | 105 | STLTECH + HFCL = Communication Equipment; PARAS = Aerospace & Defense |

Matched sample: 747/748 tickers mapped; the rows where both taxonomies have a ≥5-peer group.

> **Caveat on every number here:** industry labels are today's, applied backwards. Companies
> change industry rarely so this is mild, but it is not strictly point-in-time, and it biases
> *toward* the sector signal working — which makes the negative result stronger, not weaker.

---

## Test 1 — the proposed reorder (combined rank vs momentum-only)

Top 20/day by `(1-w)·momentum_rank + w·sector_rank`, against top 20/day by momentum alone, same
days. This is the decision.

| taxonomy | weighting | combo | momentum-only | z_paired |
|---|---|---|---|---|
| nse | 75% mom + 25% sector | +1.88% | +1.84% | 1.20 |
| nse | 50/50 | +1.95% | +1.84% | **1.80** |
| nse | 25% mom + 75% sector | +1.77% | +1.84% | −0.80 |
| gics | 75/25 | +1.85% | +1.84% | 0.42 |
| gics | 50/50 | +1.79% | +1.84% | −0.89 |
| gics | 25/75 | +1.75% | +1.84% | −1.07 |

Best case z = **1.80**, below the bar of 2. Stability of that best case by chronological fifth:
0.00 / 4.38 / 3.00 / **−2.31** / −0.76 — **holds in 2 of 5**. Deflated Sharpe prefers
momentum-only over every granular variant.

**Granularity did not rescue it — granular is consistently worse than coarse in the head-to-head.**

## Test 2 — sector-strength quintiles inside the basket

This is what made a third test worth running:

| quintile (gics) | net/trade | z vs rest of basket |
|---|---|---|
| Q1 | +1.24% | −1.67 |
| Q2 | +1.07% | −3.49 |
| Q3 | +0.80% | −1.09 |
| Q4 | +0.87% | −1.63 |
| **Q5 — hottest sector** | **+2.31%** | **+7.85** |

Not a gradient — only the top quintile does anything, and granularity makes it much stronger
there (gics 7.85 vs nse 4.48). A weighted blend spreads that across the whole list and dilutes it.

Stock-vs-own-sector RS is U-shaped (Q1 +4.62, Q3 −4.76, Q5 +4.97 on gics). A U-shape with no
mechanism is a noise signature; not pursued.

## Test 3 — the cut, tested directly (post-hoc, higher bar)

Keep only names whose industry is in the hottest quintile that day, then take the top 10 by
momentum. Control: top 10 by momentum, no sector condition. Found by looking at the data, so the
bar was set at z > 2 **and** 4 of 5 periods.

| | trades | net/trade | z_paired |
|---|---|---|---|
| sector-tilted | 7,308 | **+2.31%** | 1.62 |
| momentum-only control | 9,660 | **+2.43%** | — |

**The tilt returns less than the control it was supposed to beat.** By fifth: 6.19 / 1.79 / 3.93 /
**−4.89** / **−2.24** — holds in 2 of 5, and both recent periods are negative.

### Why Q5 looked strong but the tilt fails

Q5's +7.85 is measured against **the whole rest of the basket**, which includes the weak tail at
ranks 21+ (already known to return +1.13%/trade vs +1.92% for the top 20). Hot-sector names are
better than *that*. They are not better than the top momentum names you were already buying.
Once the momentum rank has done its work, sector strength adds nothing — it was re-discovering
the same stocks from a noisier angle.

---

## What shipped

- **`build_industry_map.py` → `cache/industry_map.pkl`** — 747/748 tickers, 105 yfinance
  industries. Re-run occasionally; labels rarely change, existing entries are kept.
- **`cache_manager.load_industry_map()`** and **`tools.peer_strength()`** — peer-group 60-day
  move computed off the price cache already loaded by the scan.
- **Option A: a second line per scan entry** —
  `Communication Equipment: peers +4.4% over 60d, this stock ahead of them by 34.3pp`.
  Display only. Marked as such in `peer_strength`'s docstring and in `SHARED_RULES`.

## What did NOT ship

- **Sector strength as a ranking input** — every form failed (tests 1–3).
- **Granular taxonomy as a ranking improvement** — it is better data and it still failed; it is
  worth having for *reading*, not for ordering.
- **Upstox as a data source for this.** Their [Company Profile API](https://upstox.com/developer/api-documentation/get-company-profile/)
  returns `sector` only — no industry or sub-industry — and needs an ISIN per call; the
  instruments master carries no classification at all. Coarser than what yfinance already gives
  us free. Not adopted.

## Bug found and fixed mid-study

The first run reported "combo wins, z 4.29" for the coarse taxonomy. That run was **void**: the
panel is a per-ticker `concat` with **non-unique row indices**, and the control group was built
with `~basket.index.isin(sel.index)`, which silently dropped unrelated rows. Fixed by
`reset_index(drop=True)` plus boolean masks throughout. Same class of error as the two traps in
`long_term_issues.md` — worth adding to the list: **never build a control group by index on the
raw panel.**
