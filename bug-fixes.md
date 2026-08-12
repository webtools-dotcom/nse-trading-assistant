# bug-fixes.md — exact fixes for the executor (DeepSeek)

**You are a code executor, not a designer.** Apply each fix below EXACTLY as written —
find the "BEFORE" block, replace it with the "AFTER" block. Do not refactor, rename,
reformat, or "improve" anything else. Do not touch any file not named here.

**Do NOT commit.** Leave all changes uncommitted. The reviewer inspects `git status --short`
and `git diff` afterward, so your work must be the only uncommitted change in the tree.

**After applying, run the VERIFICATION section at the bottom. Every command must pass.**

---

## Context: what this audit found

A deep audit of the money-decision path (scan → expected value → position sizing → exit
monitor) found the logic **sound**. These are the only two changes. The list is short because
the code is solid — not because the audit was shallow.

### VERIFIED CORRECT — DO NOT MODIFY THESE
Do not "fix" any of the following. They were checked and are correct:
- `calculate_position_size` in `tools.py` — risk math, stop-below-price guard, account-size path.
- `exit_verdict` / `get_exit_check_text` in `tools.py` — the exit monitor correctly uses the
  **live** price (`get_live_price`), not the cache.
- `round_trip_cost_pct`, `gross_edge_for_meta`, `gross_edge_for_rsi` in `config.py`.
- `add_short_features` / `add_long_features` in `features.py`.
- `check_exit_signals` `days_held` (uses `np.busday_count`), `record_trade_exit` classifier.
- `cache_status_note` stale-price warning (already added and working).

---

## FIX 1 — Guard against NaN ATR producing "Rs nan" stop/target levels  [priority: LOW, robustness]

**File:** `tools.py`
**Function:** `evaluate_user_trade`
**Why:** If a live-fetched ticker has a missing/NaN ATR, the stop/target/reward-risk lines
render as literal "Rs nan". That is a money-facing number that should never be shown; if ATR
is unavailable, say so instead of printing nonsense.

### Edit 1a — add the validity flag

BEFORE (find this exact line):
```python
    atr = levels['atr']
```

AFTER (replace with):
```python
    atr = levels['atr']
    atr_ok = atr is not None and pd.notna(atr) and atr > 0
```

### Edit 1b — branch on it

BEFORE (find this exact line — it is the start of the stop/target section):
```python
    if entry_price is not None and entry_price > 0:
```

AFTER (replace with):
```python
    if not atr_ok:
        out.append("\nATR is unavailable for this ticker (insufficient recent data), so stop and "
                   "target levels cannot be computed. Do not guess them.")
    elif entry_price is not None and entry_price > 0:
```

> Note: this turns the existing `if / else` into `if / elif / else`. The existing `else:`
> (the "IF ENTERING NOW" branch) stays exactly where it is and is unchanged. Do not touch it.

---

## FIX 2 — Unknown volatility regime should size DOWN, not apply full risk  [priority: MEDIUM, money-safety]

**File:** `config.py`
**Function:** `vol_regime_multiplier`
**Why:** When the market-volatility percentile is unavailable, the tool currently applies the
FULL position multiplier (1.0). But this strategy *loses money in calm markets* (measured
-0.8%/trade), and the whole purpose of this function is to cut size when the market is calm.
Defaulting an UNKNOWN regime to full size is the unsafe direction. Halving size until the
regime is known is the safe default. (This changes a documented default — see the reviewer's
note; apply only if the owner approved it.)

Inside `vol_regime_multiplier` there are **TWO identical lines** (one in the `if None` branch,
one as the function's last line). **Replace BOTH occurrences** (a replace-all of this exact
line within `config.py`):

BEFORE (this exact line appears twice — change both):
```python
    return 1.0, "market volatility regime unknown - no adjustment applied"
```

AFTER (both become):
```python
    return 0.5, "market volatility regime unknown - conservative half-size until it is known"
```

Note the indentation differs between the two (one is inside the `if`, indented 8 spaces; the
other is at function level, 4 spaces). Match `return 1.0, "market volatility regime unknown -
no adjustment applied"` regardless of leading whitespace, and change the `1.0` to `0.5` and the
trailing text as shown, preserving each line's original indentation.

---

## VERIFICATION — run all of these. Every one must print its success line / not error.

```bash
python -c "from config import vol_regime_multiplier; print(vol_regime_multiplier(None)); assert vol_regime_multiplier(None)[0] == 0.5"
python -c "import tools; print('tools imports OK')"
python test_user_trade.py
python test_discipline.py
python test_trade_journal.py
python features.py
python decay_monitor.py
python backtest_engine.py
```

Expected: `vol_regime_multiplier(None)` prints `(0.5, ...)`; `tools imports OK`; each test
prints its own "OK" / "passed" line; no tracebacks anywhere.

On Windows, prefix with `PYTHONIOENCODING=utf-8` if ₹ symbols crash the console.

---

## Scope not covered (for the owner's awareness — NOT for the executor to touch)
The audit focused on the short-term money-decision path. Not deeply audited: the long-term
momentum path, news/announcement text parsing, and the phone watcher (`news_watcher.py`,
`alert_watcher.py`). Flag for a future pass if desired.
