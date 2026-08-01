# Long-term strategy — deferred validation work

**Status:** the long-term (~1 month momentum) strategy has **not** been re-validated through the
corrected backtest engine. The short-term strategy has. This file is a self-contained handoff —
hand it to an AI session with the repo and it should be able to finish the job without any other
context.

**Why deferred:** deliberate scope decision (2026-07-31). Focus is on short-term only for now.
Nothing here is urgent *provided* the long-term numbers keep being presented as provisional,
which the code currently does (see "Where the caveats live" below).

---

## The core problem

Every published long-term z-score was produced by the old `simulate_trades()`, which opened a
trade on **every bar** the entry condition was true. Because the condition (near 52-week high +
uptrend) persists for weeks, one setup became many near-identical overlapping trades sharing the
same forward returns — but the statistics divided by `sqrt(n)` as if they were independent.
This is López de Prado's Pitfall #7 (non-IID samples / label overlap).

Measured on the **short-term** signal: average label uniqueness **0.344**, giving a z-score
inflation factor of **1.70×**.

> ⚠️ **Do not reuse the 1.70× figure for long-term.** It was measured on 6-day labels. The
> long-term horizon is **20 trading days** (`LONG_HORIZON_DAYS`), and the entry condition
> persists far longer than an RSI<30 reading. Overlap — and therefore inflation — is almost
> certainly **worse**. It must be measured separately via `backtest_engine.average_uniqueness()`.

### Published numbers, all suspect

| Claim | Published z | Naive 1.70× deflation (illustrative only) | Real status |
|---|---|---|---|
| Long-term overall | 9.69 | ~5.7 | Unverified |
| Small-cap | 14.52 | ~8.5 | Likely survives |
| Mid-cap | 2.88 | ~1.7 | Likely **fails** |
| Large-cap | 2.28 | ~1.3 | Likely **fails** |

Also unaddressed: **zero transaction costs** were charged, and there is **no multiple-testing
correction** across the several long-term backtest variants that were run.

---

## Blocking gap: the engine can't model this strategy yet

`backtest_engine.simulate_trades()` only supports **ATR-multiple** stops:

```python
def simulate_trades(stock_df, entry_mask, horizon_days=6, stop_atr_mult=2.0,
                    target_atr_mult=2.0, charge_costs=True, allow_overlap=False):
```

The long-term strategy uses **fixed percentage** stops — `LONG_STOP_PCT = 0.08`,
`LONG_TARGET_PCT = 0.16` (config.py:30-31). **This must be added before anything else can be
validated.** Suggested minimal change (keep it one function, don't fork the engine):

```python
def simulate_trades(stock_df, entry_mask, horizon_days=6, stop_atr_mult=2.0,
                    target_atr_mult=2.0, charge_costs=True, allow_overlap=False,
                    stop_pct=None, target_pct=None):
    # when stop_pct/target_pct are given they take precedence over the ATR multiples:
    #   stop   = entry * (1 - stop_pct)
    #   target = entry * (1 + target_pct)
```

Everything else in the engine already applies unchanged — non-overlap, gap-through-stop fills,
cost charging, purged walk-forward.

---

## What to do, in order

### 1. Build the 5-year long-feature dataset
The short-term equivalent already exists at `cache/backtest_5y_short.pkl`. Mirror it:

```python
import pickle, os
from data_fetcher import download_watchlist_history
from features import add_long_features
from config import WATCHLIST, BASE_DIR
raw = download_watchlist_history(WATCHLIST, period="5y")
out = {}
for t in raw['ticker'].unique():
    df = raw[raw['ticker'] == t].copy()
    if len(df) < 300: continue
    out[t] = add_long_features(df).reset_index(drop=True)
with open(os.path.join(BASE_DIR, "cache", "backtest_5y_long.pkl"), 'wb') as f:
    pickle.dump(out, f)
```

Takes several minutes (~750 tickers). `add_long_features` already emits `turnover_60d`.

### 2. Add percentage-stop support to the engine (see gap above), then re-run `python backtest_engine.py` — its self-check must still pass.

### 3. Measure the actual overlap inflation
Use `backtest_engine.average_uniqueness(trades, n_bars)` on long-term entries. Report the
uniqueness and `sqrt(1/uniqueness)`. **This number replaces the guessed 1.70× everywhere.**

### 4. Re-run every long-term claim non-overlapping and net of costs
Entry condition (from `tools.get_swing_levels_long`):
`dist_from_high_252 > -0.10` **and** `close > sma_50 > sma_200` **and** outperforming Nifty.
Use `backtest_engine.report()` for consistent output, and `edge_vs_control()` against a
random-entry control. Produce a before/after z-score table for all four claims above.

### 5. Walk-forward with purge + embargo
`backtest_engine.walk_forward_splits(n_bars, horizon_days=20)`. Report **out-of-sample only**.
A claim that only works in-sample does not ship.

### 6. Deflated Sharpe with effective trial count
`deflated_sharpe(...)` plus `effective_trials(...)`. Feeding the raw trial count over-deflates
because the variants are correlated — report the band across estimators.

### 7. Open questions worth testing (short-term answers may not transfer)
- **Liquidity.** Short-term edge rose *monotonically* with turnover (Q1 +0.53% → Q5 +1.11%),
  which is why the ₹25cr floor exists. Does the same hold at a 1-month horizon? A longer hold
  amortises impact cost over a bigger move, so the floor may be **too strict** here.
- **Market volatility regime.** Short-term mean reversion needs panic (calmest quartile
  −0.81%/trade, most volatile +1.64%, z=9.27). Momentum is a *different* effect and may well
  invert this. `calculate_position_size` currently applies the vol multiplier to `term="short"`
  **only** — correctly, since long-term is untested. Test before extending it.
- **Meta-labeling.** Followed the pattern in `meta_label.py`; for short-term it reached AUC 0.587
  and lifted net return +0.46% → +1.32% at top-50%. A long-term equivalent is plausible but
  needs its own model, its own purged CV, and the same ship criteria (must beat base rate OOS).

### 8. Replace the placeholder edge constant
`config.py:84` — `GROSS_EDGE_LONG_PCT = 2.50` is flagged in-code as a *"rougher estimate"*. It is
**not measured**. It currently drives the NET expected value shown for every long-term candidate.
Replace it with the measured walk-forward figure — ideally a `gross_edge_for_*` style band
function like the short-term ones (`gross_edge_for_rsi`, `gross_edge_for_meta`).

---

## Where the caveats live (update these when the work is done)

All of these currently tell the user the long-term numbers are provisional. If validation
succeeds, tighten them to the real figures; if a claim fails, **retire it rather than softening
it** — the same standard the README applies to the rejected shallow-pullback hypothesis.

| File | What is marked |
|---|---|
| `tools.py` → `get_snapshot_text_long` | "z=9.69 … NOT yet been re-run through the corrected engine; provisional" |
| `tools.py` → `get_snapshot_text_long` | Market Cap Segment line, overlap caveat on 14.52 / 2.88 / 2.28 |
| `tools.py` → `scan_watchlist_text_long` | "⚠️ CAP-TIER CAVEAT" header block |
| `tools.py` → `scan_watchlist_text_long` | Footer: "long-term gross edge has NOT yet been re-validated" |
| `config.py` → `SHARED_RULES` | Long-term strategy paragraph ("present as provisional and say so") |
| `config.py` → `SHARED_RULES` | "LONG-TERM CAP TIERS - the published numbers are NOT all valid" |
| `mcp_server.py` → `scan_long_term` | Docstring "PROVISIONAL: … not yet been re-validated" |
| `README.md` | Long-term Position table — already marked "⏳ Not yet re-validated" |

---

## Reusable pieces (do not rebuild these)

| What | Where |
|---|---|
| Trade simulation, non-overlap, honest fills, costs | `backtest_engine.simulate_trades` |
| Label uniqueness / overlap inflation | `backtest_engine.average_uniqueness` |
| Edge vs random control, z, p | `backtest_engine.edge_vs_control` |
| Purged walk-forward splits | `backtest_engine.walk_forward_splits` |
| Deflated Sharpe + effective trials | `backtest_engine.deflated_sharpe`, `effective_trials` |
| Search-adjusted p-value (block bootstrap) | `backtest_engine.block_bootstrap_pvalue` |
| Threshold plateau / curve-fit check | `backtest_engine.plateau_check` |
| Consistent result printing | `backtest_engine.report` |
| Long feature builder (incl. `turnover_60d`) | `features.add_long_features` |
| Indian round-trip cost incl. liquidity impact | `config.round_trip_cost_pct` |
| Decay / regime attribution | `decay_monitor.diagnose`, `cusum` |
| Meta-labeling pipeline to copy | `meta_label.py` |

---

## Two traps that bit during the short-term work

Both produced confident, wrong answers. Expect them.

1. **Look-ahead in percentile filters.** Ranking with `rank(pct=True)` or `.iloc[-1]` over the
   *whole* sample uses future information. Every percentile — liquidity, volatility — must be
   computed **point-in-time** (trailing window only). This error was made twice.
2. **Pooling trades per-ticker breaks any time-series analysis.** `[all of stock A, then all of
   stock B]` is not chronological. Sort trades by entry date before CUSUM, decay diagnosis, or
   anything fold-based, or the buckets are meaningless.

---

## Definition of done

- [ ] `backtest_engine.simulate_trades` supports percentage stops; self-check still passes
- [ ] `cache/backtest_5y_long.pkl` built
- [ ] Long-term label uniqueness measured and reported (replaces the guessed 1.70×)
- [ ] All four claims (overall, Small, Mid, Large) re-run non-overlapping and net of costs
- [ ] Walk-forward out-of-sample results reported, not in-sample
- [ ] Deflated Sharpe computed with effective trial count
- [ ] `GROSS_EDGE_LONG_PCT` replaced with a measured number
- [ ] Every caveat in the table above updated — or the failing claim retired outright
- [ ] `README.md` long-term table updated with before/after z-scores
