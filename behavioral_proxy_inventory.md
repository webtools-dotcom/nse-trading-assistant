# Behavioral-proxy data inventory

What this codebase can actually measure, as of 2026-08-01. Written to constrain
behavioral-finance research prompts: a psychological rule is only useful here if it can be
expressed from Tier A (backtestable) or at worst Tier B (live-only) inputs.

Panel: 702–748 NSE stocks, daily OHLCV, **2021-07-30 → 2026-07-29** (`cache/backtest_5y_short.pkl`).
Market series `^NSEI` and `^INDIAVIX` both return a full 5y daily history from yfinance
(verified: 1234 / 1228 bars) — the short cache windows in `cache_manager.py` are a refresh
choice, not a data limit.

---

## Tier A — 5-year history, point-in-time, backtestable

These can go through `backtest_engine.py` against a random-entry control. Anything a rule
needs must live here to become a live gate.

### Market / crowd level

| Proxy | Source | Notes |
|---|---|---|
| India VIX level | `^INDIAVIX` 5y | fear level |
| VIX percentile (trailing 252d) | derived | already the basis of the validated vol-regime sizing |
| VIX 1d / 5d change, VIX z-score | derived | **acceleration** — spike vs slow grind are different states |
| Nifty realized vol (10d/20d) + its percentile | `^NSEI` | what the current sizing rule uses |
| Nifty drawdown from 252d high | `^NSEI` | market-level pain |
| Nifty 6d / 60d momentum, above/below SMA200 | already cached | regime |
| Nifty overnight gap (open vs prev close) | `^NSEI` | overnight-emotion proxy |
| Breadth: % of panel above 200SMA | cross-section of panel | currently a live snapshot only — **historically reconstructible** |
| Panic breadth: % of panel with RSI<30 on the day | cross-section of panel | crowd-wide capitulation, not per-stock |
| Advance/decline ratio, % of panel gapping down | cross-section of panel | reconstructible |
| Cross-sectional return dispersion | cross-section of panel | correlation-spike / "everything sells off together" |
| **Retail net cash flow (₹cr/day)** | `cache/category_flows.pkl` | ⚠️ history starts **2023-04**, not 2021 |
| **FPI net cash flow (₹cr/day)** | same | foreign institutional positioning |
| Mutual fund / insurance / bank / PMS / AIF net flow | same | domestic institutional side |
| Retail-vs-FPI divergence (opposite-sign days) | derived | the classic "retail buying what foreigners are selling" setup |
| Retail flow z-score / percentile | derived | needs ≥250 days of history to be meaningful |

### Stock level

| Proxy | Column / derivation |
|---|---|
| RSI, RSI slope, days-below-30 streak | `rsi` |
| Consecutive down-day streak | `price_change` |
| Volume spike vs 20d average | `volume_change`, `volume` |
| Overnight gap-down size | `open` vs prev `close` |
| Intraday range expansion `(high-low)/close` | OHLC |
| Distance from 50d / 252d high | `distance_from_high_50`, `dist_from_high_252` |
| 1-year trend context | `change_252d` |
| Volatility, ATR% and vol-of-vol | `volatility_10`, `atr_pct` |
| Turnover / attention | `turnover_60d` |
| Relative strength vs Nifty | panel + `^NSEI` |
| Sector-relative momentum | industry map in `sector_rs_data.pkl` + panel history |

---

## Tier B — live only, NOT backtestable

Real data, too little history to validate. Usable as displayed context or as a journal tag,
never as a silent sizing multiplier (project rule: no unbacktested rule drives logic).

| Proxy | Available history |
|---|---|
| Delivery % (retail vs speculative conviction) | **24 trading days**, 749 symbols |
| Bulk / block deals (institutional footprint) | ~1 month |
| Corporate announcements | 5 days rolling |
| Sector RS snapshot | current day only (history is recomputable, the cache is not) |

Delivery % is the single most painful gap — it is the best available retail-conviction proxy
in Indian markets and there is no stored history to test it on. Worth starting a daily append
now so it becomes Tier A in a year.

---

## Tier C — obtainable, but needs a new fetcher

Not in the project today. Flagged because behavioral-finance literature leans on these heavily
and for India they genuinely exist.

- **NSE index option put/call ratio and open interest** — the classic sentiment gauge.
- NSE F&O ban list / rollover data — speculative froth.
- FII/DII **derivatives** positioning — `nselib.derivatives.fii_derivatives_statistics(date)`
  and `participant_wise_open_interest(date)`, both per-day, same backfill pattern as cash.

### Built 2026-08-01: participant category flows ✅

`update_category_flows()` / `load_category_flows()` in `cache_manager.py`, wired into
`refresh_cache.py`, backfilled via `python cache_manager.py backfill-flows`. Source is
`nselib.capital_market.category_turnover_cash(date)` — one NSE file per trading day giving
buy / sell / net in ₹cr for **FPI, MUTUAL_FUNDS, INSURANCE, BANK, AIF, PMS, RETAIL, OTHERS**.

Two constraints that matter for any rule built on it:

1. **History starts ~April 2023 (~3.3 years), not 5.** Before that NSE published only
   `BNK / DFI / PRO-TRADES / OTHERS` — no FPI or Retail split exists at all in the older
   files. Any flow-based rule is validated on a shorter window than the price-based ones,
   covering roughly one and a half market regimes. Weight conclusions accordingly.
2. **Feb–Mar 2023 files fail to parse** (schema transition, `nselib` raises). Backfill starts
   2023-04-01 to sidestep it.

Labels drift across eras (`Retail`/`RETAIL`, `AIF`/`AIFs`, `BNK`/`Bank`); `_normalize_flows()`
folds them. `test_category_flows.py` covers that plus re-fetch dedupe.

**Backfilled and validated 2026-08-01**: 815 trading days, 2023-04-03 → 2026-07-29, 6,512 rows,
no gap longer than a long weekend. All eight categories present on 807 days; FPI missing on 8.

3. **The categories do not sum to zero, so do not treat them as exhaustive.** Every buy has a
   seller, so daily net across all participants should be ~0. It usually is (median residual
   ₹90cr, ~0.2% of daily turnover) but roughly 5% of days exceed ₹6,000cr and the worst is
   ₹22,000cr. Use individual category nets as signals; never derive one category as the
   residual of the others, and never use `OTHERS` as a balancing plug.

Observed structure worth testing (not yet backtested): RETAIL and FPI daily net flows correlate
**−0.48** and take opposite signs on **65.5%** of days. Over this window FPI averaged
−₹974cr/day and mutual funds +₹1,708cr/day — i.e. the sample is dominated by one regime of
persistent foreign selling absorbed domestically. A flow rule fitted here is fitted to that.

---

## Tier D — not available, do not accept rules that require them

Retail order flow, brokerage account-opening rates, margin-debt levels, short interest,
sentiment surveys (AAII-equivalent), Google Trends, social-media sentiment, mutual-fund flow
timing, individual investor positioning.

---

## Constraint block for the NotebookLM prompt

> Every rule you specify must be computable from **daily OHLCV of individual NSE stocks, the
> Nifty 50 index, the India VIX index, and NSE daily participant-category net cash flows
> (foreign institutional, domestic institutional, and retail net buy/sell in ₹ crores)**. Do
> not propose rules requiring put/call ratios, tick-level order flow, short interest,
> sentiment surveys, social media, or margin debt. For each psychological regime give:
> (1) the name, (2) the exact numeric trigger
> expressed in those inputs, including lookback windows and thresholds, (3) the proposed
> position-size multiplier, (4) the specific paper and market/period the claim comes from, and
> (5) whether it has been independently replicated.

Point (4) and (5) matter: most of this literature is US equities, often pre-2010, and
frequently unreplicated. Output is a hypothesis list, not a rule set.
