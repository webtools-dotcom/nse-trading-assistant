# Promoter holding change — measured, no edge

**Verdict: REJECTED as a signal. Retained as display-only context.**
Run `python backtest_promoter_holding.py [--hold N]` to reproduce.

## Why this test had real power, unlike the other fundamentals

`backtest_fundamentals.py` cannot really measure an annual-statement factor here: Indian FYs are
almost all March-end, so honest clustering leaves ~4 fiscal cohorts and z_paired has no power by
construction. Quarterly shareholding filings do not share that problem:

| | annual statements | quarterly shareholding |
|---|---|---|
| point-in-time | no (restated in place) | **yes** (`broadcastDate`, revisions filed as separate rows) |
| independent clusters | ~4 fiscal cohorts | **555 broadcast days**, median 1 event/day |
| look-ahead risk | high | entry = next open after broadcast |

Data: 745 symbols, 14,158 quarterly rows from NSE `corporate-share-holdings-master`
(`build_shareholding_archive.py`). 11,243 usable events after dropping revised rows, the
Jan-2022 bulk-backfill window (NSE loaded every pre-2022 filing at 02:55 on 07-JAN-2022 — those
timestamps are database artifacts, not disclosure dates), and filings more than 120 days late.

So this is the one fundamentals-adjacent factor that could have been demonstrated. It wasn't.

## Result

Nothing clears |z_paired| ≥ 2.0 at any horizon.

| bucket | n | hold 5 | hold 10 | hold 21 |
|---|---:|---:|---:|---:|
| promoters sold ≥5pp | 205 | -0.20 | 0.99 | 0.88 |
| promoters sold 2-5pp | 254 | 0.69 | 0.76 | 1.90 |
| promoters sold 1-2pp | 162 | 0.89 | 0.14 | -1.84 |
| promoters bought 1-2pp | 82 | 1.15 | 1.31 | 1.54 |
| promoters bought ≥2pp | 93 | -0.70 | -0.93 | 0.28 |
| all sells (≤ -0.5pp) | 759 | 0.58 | 0.89 | 1.13 |
| all buys (≥ +0.5pp) | 266 | -0.89 | -0.44 | 1.28 |

Two subgroups touched z_paired 2.48 at hold 5 — Mid-cap sells and Large-cap buys. Neither
survives: Mid-cap sells goes 2.48 → 1.96 → 0.70 across holds, Large-cap buys 2.48 → 0.52 →
-0.38. Out of ~14 subgroup comparisons, one or two |z| > 2 is what chance produces. "Promoters
selling predicts outperformance" is also backwards, which is the usual shape of a fluke.

## The naive-vs-paired gap, again

All sells at hold 5: **z_naive = -2.05, z_paired = 0.58.**

The naive number looks like a real bearish signal and is not one. Promoter holding drifts DOWN
across this universe — mean QoQ change -0.19pp, falls outnumber rises 2.5:1 — and the control
lost 0.46%/trade on the same days. The naive z was measuring the universe's drift and the
market's direction, not the filing. Same failure mode as `open_offer` in
[news_event_results.md](news_event_results.md) (naive 7.17, paired 0.44). Third time this
pattern has appeared in this project.

## What was kept

Promoter holding %, its 1-year change, and current pledge % are displayed in
`get_fundamentals_text` as business context, and pledge ≥25% / promoter exit ≥5pp are Fragile
triggers in `fundamental_verdict`. Those are **safety framing, not prediction** — the same
status as every other fundamental here. Nothing in this file justifies letting them influence
the scan, and they do not.

Pledging could not be tested at all: NSE's `corporate-pledgedata` serves only the current
snapshot, with no history.
