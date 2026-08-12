# long-term-adoption.md — wire the validated momentum signal into the live tool

Context: `backtest_longterm.py` proved the old near-52w-high screen only survives in **Small-cap**
(z 4.28; Mid −0.01 and Large 0.34 are dead). `backtest_longterm_xsec.py` + `backtest_longterm_oos.py`
proved the real upgrade: **cross-sectional 12M-1M momentum + low-vol overlay**, day-clustered
z ≈ 8.5 out-of-sample, net ≈ **+2.9%/trade** over ~20 days — with genuine momentum-crash periods
(2 of 5 backtest years negative). This pass surfaces that signal live and corrects two fictions.

## Your role (executor)
- Make ONLY the three changes below, exactly. This is a **money path** — the reviewer will run
  every changed function against the live cache before anything ships.
- **Do NOT commit.** Leave changes uncommitted for `git diff` review.
- Do NOT touch the agent/MCP dispatch, `SHARED_RULES`, the README, or `get_swing_levels_long` —
  the reviewer wires those (integration + disclosure prose, decided from the live output).
- `PYTHONIOENCODING=utf-8` on Windows.

---

## CHANGE 1 — Add the validated momentum scan (new function in `tools.py`)

Add this function to `tools.py` **immediately after** the existing `scan_watchlist_text_long`
function (i.e. after its final `return text` line — find the end of that function; insert this new
function right after it). It is self-contained: reads only the long cache and existing config
constants (`MIN_TURNOVER_INR`, `LONG_STOP_PCT`, `LONG_TARGET_PCT`, `CAP_BUCKET_MAP`) already
imported at the top of `tools.py`. Paste EXACTLY:

```python
def scan_watchlist_text_long_momentum(limit=30):
    """Cross-sectional momentum scan - the VALIDATED long-term signal (2026-08).
    Ranks the liquid Mid/Small universe by 12M-1M momentum (skip the most recent month), keeps the
    top decile filtered to the lower-volatility half. Day-clustered z ~8.5 out-of-sample, net
    ~+2.9%/trade over ~20 trading days - materially stronger than the old near-52w-high screen
    (only Small-cap survived that, z 4.28; Mid/Large were dead).

    THIS IS A BASKET STRATEGY: hold several of the top names, rebalanced ~monthly - not a single
    pick. Momentum CRASHES: 2 of the 5 backtested years were negative (the top names underperformed
    the universe). High return, high drawdown - size small and diversify.
    """
    cache = load_price_cache_long()
    rows = []
    for ticker, df in cache.items():
        cap = CAP_BUCKET_MAP.get(ticker)
        if cap not in ('Mid', 'Small'):
            continue
        d = df.dropna(subset=['close', 'turnover_60d'])
        if len(d) < 260:
            continue
        c = d['close'].values
        turn = float(d['turnover_60d'].values[-1])
        if not np.isfinite(turn) or turn < MIN_TURNOVER_INR or c[-252] <= 0:
            continue
        mom = c[-21] / c[-252] - 1                     # 12M-1M: return from 252 bars ago to 21 bars ago
        vol = float(pd.Series(c).rolling(10).std().values[-1])
        if not np.isfinite(vol):
            continue
        rows.append({'ticker': ticker, 'cap': cap, 'price': round(float(c[-1]), 2),
                     'mom_pct': round(mom * 100, 1), 'vol': vol, 'turn_cr': round(turn / 1e7, 1)})

    if not rows:
        return "Long-term momentum scan: no liquid Mid/Small stocks with >=260 bars of history. Run refresh_cache.py."

    d = pd.DataFrame(rows)
    d['mom_rank'] = d['mom_pct'].rank(pct=True)
    d['vol_rank'] = d['vol'].rank(pct=True)
    top = d[(d['mom_rank'] >= 0.90) & (d['vol_rank'] <= 0.50)]
    if len(top) == 0:
        top = d[d['mom_rank'] >= 0.90]
    top = top.sort_values('mom_pct', ascending=False)

    text = cache_status_note()
    text += ("Long-term MOMENTUM scan (validated 2026-08, day-clustered z ~8.5 out-of-sample, net "
             "~+2.9%/trade over ~20 trading days). Ranks the liquid Mid/Small universe by 12-month "
             "momentum, keeps the top decile at below-median volatility.\n"
             "⚠️ BASKET strategy - hold several, rebalance ~monthly, NOT a single pick. Momentum "
             "CRASHES: 2 of 5 backtested years were negative (winners underperformed the universe). "
             "High return, high drawdown.\n\n")
    for _, r in top.head(limit).iterrows():
        stop = round(r['price'] * (1 - LONG_STOP_PCT), 2)
        target = round(r['price'] * (1 + LONG_TARGET_PCT), 2)
        text += (f"{r['ticker']} [{r['cap']}]: Price Rs{r['price']}, 12M momentum {r['mom_pct']:+.1f}%, "
                 f"liquidity {r['turn_cr']}cr/day | stop Rs{stop} (-{LONG_STOP_PCT*100:.0f}%), "
                 f"target Rs{target} (+{LONG_TARGET_PCT*100:.0f}%)\n")
    return text
```

---

## CHANGE 2 — Replace the fake long-term edge constant (`config.py`)

`GROSS_EDGE_LONG_PCT = 2.50` was flagged in-code as a "rougher estimate" — it is not measured. The
near-52w-high screen (the path `get_swing_levels_long` still uses for single-stock snapshots) nets
+0.98% in Small-cap and ~0 elsewhere; gross ≈ +1.5%.

BEFORE (find this exact line):
```python
GROSS_EDGE_LONG_PCT = 2.50      # momentum setup, ~1 month hold (rougher estimate)
```

AFTER:
```python
GROSS_EDGE_LONG_PCT = 1.50      # near-52w-high screen, measured Small-cap gross (backtest_longterm.py); Mid/Large ~0
```

---

## CHANGE 3 — Correct the wrong cap-tier caveat in the existing long scan (`tools.py`)

The current caveat cites the OLD, WRONG overlap figure (1.70x) and pre-validation guesses. The
honest measured numbers are: overlap inflation **2.9x**, Small honest z **4.28** (holds), Mid and
Large **dead**.

BEFORE (find this exact block inside `scan_watchlist_text_long`):
```python
             f"⚠️ CAP-TIER CAVEAT: the published z-scores (Small 14.52, Mid 2.88, Large 2.28) were computed with "
             f"OVERLAPPING trades. Deflating by the measured 1.70x inflation gives Small ~8.5 (holds), Mid ~1.7 and "
             f"Large ~1.3 (NOT significant). Treat Mid- and Large-cap long-term setups as UNVALIDATED until "
             f"re-tested; only the Small-cap claim survives correction.\n\n")
```

AFTER:
```python
             f"⚠️ CAP-TIER REALITY (validated 2026-08, day-clustered, costs charged): the old z-scores "
             f"(Small 14.52, Mid 2.88, Large 2.28) were ~2.9x overlap-inflated. Honest: Small z 4.28 HOLDS; "
             f"Mid (z -0.01) and Large (z 0.34) are DEAD - no edge over random, do not present them as setups. "
             f"NOTE: the stronger validated long-term signal is the cross-sectional MOMENTUM scan "
             f"(scan_watchlist_text_long_momentum), not this near-52w-high screen.\n\n")
```

---

## VERIFICATION — run, and paste output
```bash
python -c "import tools; print('tools imports OK')"
python -c "import config; assert config.GROSS_EDGE_LONG_PCT == 1.50; print('edge constant OK')"
python -c "import tools; print(tools.scan_watchlist_text_long_momentum(limit=10))"
python test_user_trade.py
python test_discipline.py
```
Expected: `tools imports OK`; `edge constant OK`; the momentum scan prints a ranked list with the
BASKET/crash header (or the "no liquid stocks" message if the cache is empty); both tests pass.
**Paste the momentum-scan output** so the reviewer can sanity-check the ranked names.

---

## NOT in this pass — the reviewer does these (integration + money-path judgment)
Do NOT attempt; listed so the reviewer knows what remains:
- Point the agent + `mcp_server.py` long-scan dispatch at `scan_watchlist_text_long_momentum`
  (making momentum the default long scan).
- Weave the corrected numbers + momentum-crash disclosure through `SHARED_RULES` (config.py),
  the README long-term table, and the MCP `scan_long_term` docstring; retire the Mid/Large
  near-high claims there.
- Decide whether the near-52w-high screen (`scan_watchlist_text_long`) stays as a secondary view
  or is retired.

## DO NOT TOUCH
`get_swing_levels_long`, the agent/MCP dispatch, `SHARED_RULES`, `README.md`, `features.py`,
`backtest_*.py`, any `test_*.py`. This pass adds ONE function and makes TWO exact one-line/one-block
edits — nothing else.
