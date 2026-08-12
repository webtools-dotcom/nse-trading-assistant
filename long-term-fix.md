# long-term-fix.md — make the long-term tool REAL, then measure the upgrades

**Read `long_term_issues.md` first** — it is the prior-session handoff this plan executes.

## Your role (executor, not designer)
- Create/modify files **exactly** as written below. Reuse the existing engine; do not fork or
  reinvent any statistics — every stats function already exists in `backtest_engine.py`.
- **This pass MEASURES. It does not ADOPT.** Do NOT wire any signal into the live tools, do NOT
  change `GROSS_EDGE_LONG_PCT`, do NOT edit `tools.py`/`mcp_server.py`/`README.md`/`SHARED_RULES`.
  Those decisions depend on the numbers you produce and happen in a later pass after review.
- **Do NOT commit.** Leave everything uncommitted for review via `git status --short` / `git diff`.
- After building, run the **VERIFICATION** section and **paste the FULL console output of every
  backtest** back to the reviewer. The output IS the deliverable.
- On Windows prefix commands with `PYTHONIOENCODING=utf-8`.

---

## PHASE 1 — Add percentage-stop support to the engine

The long-term strategy uses fixed `%` stops; the engine only does ATR-multiple stops. This is the
blocking gap. Minimal additive change — ATR behavior is unchanged when the new params are omitted.

**File:** `backtest_engine.py`, function `simulate_trades`.

### Edit 1a — signature

BEFORE (find this exact line — the last line of the signature):
```python
                    exit_rsi=None):
```

AFTER:
```python
                    exit_rsi=None, stop_pct=None, target_pct=None):
```

### Edit 1b — stop/target computation

BEFORE (find this exact block):
```python
        entry = close[i]
        stop = entry - stop_atr_mult * atr[i]
        target = entry + target_atr_mult * atr[i]
```

AFTER:
```python
        entry = close[i]
        # stop_pct/target_pct (fixed %) take precedence over ATR multiples when given.
        stop = entry * (1 - stop_pct) if stop_pct is not None else entry - stop_atr_mult * atr[i]
        target = entry * (1 + target_pct) if target_pct is not None else entry + target_atr_mult * atr[i]
```

### Edit 1c — self-check (so the engine's own `demo()` proves the new path)

BEFORE (find this exact block — the exit_rsi self-check added earlier):
```python
    rsi_ex = simulate_trades(df, m, charge_costs=False, exit_rsi=45)
    assert any(t['reason'] == 'rsi_recover' for t in rsi_ex), "exit_rsi branch never fired"
```

AFTER (append the percentage-stop check right after it):
```python
    rsi_ex = simulate_trades(df, m, charge_costs=False, exit_rsi=45)
    assert any(t['reason'] == 'rsi_recover' for t in rsi_ex), "exit_rsi branch never fired"

    # 5c. Percentage stops must produce trades whose returns are finite (fill at entry*(1±pct)).
    pct = simulate_trades(df, m, charge_costs=False, stop_pct=0.08, target_pct=0.16)
    assert pct and all(np.isfinite(t['net_pct']) for t in pct), "percentage-stop path broken"
```

> Note (leave as-is): the entry guard still requires a finite `atr[i]`, so `%`-stop trades are
> only taken on bars with valid ATR. Harmless here — `add_long_features` always emits `atr`.

---

## PHASE 2 — Build the 5-year long-feature panel

The long backtests have no panel to run on. This mirrors the existing `build_backtest_panel.py`
exactly, swapping `add_short_features` → `add_long_features`.

**Create new file `build_backtest_panel_long.py`** with EXACTLY this content:
```python
"""Build the 5-year LONG-feature panel (cache/backtest_5y_long.pkl) - the long-term twin of
build_backtest_panel.py. Run after build_universe.py whenever the universe changes.

    python build_backtest_panel_long.py
"""

import pickle

from config import WATCHLIST
from cache_manager import chunked_download, _retry_missing
from features import add_long_features, MIN_BARS

OUT = "cache/backtest_5y_long.pkl"


def build():
    print(f"Downloading 5y data for {len(WATCHLIST)} stocks (chunked)...")
    raw = chunked_download(WATCHLIST, chunk_size=100, period="5y", interval="1d", auto_adjust=True)

    panel, missing = {}, []
    for ticker in WATCHLIST:
        try:
            df = raw[ticker].copy() if len(WATCHLIST) > 1 else raw.copy()
            df = df.reset_index()
            df.columns = [str(c).lower() for c in df.columns]
            df = df.dropna(subset=['close'])
            if len(df) < MIN_BARS:
                missing.append(ticker)
                continue
            feat = add_long_features(df)
            feat['ticker'] = ticker
            panel[ticker] = feat
        except Exception:
            missing.append(ticker)

    panel = _retry_missing(missing, panel, add_long_features, "long")
    with open(OUT, 'wb') as f:
        pickle.dump(panel, f)
    print(f"Saved {OUT}: {len(panel)}/{len(WATCHLIST)} stocks")
    if panel:
        s = next(iter(panel.values()))
        print(f"  columns: {list(s.columns)}")
        print(f"  history: {s['date'].min().date()} -> {s['date'].max().date()}, ~{len(s)} bars/stock")


if __name__ == "__main__":
    build()
```

---

## PHASE 3 — Validate the EXISTING long-term momentum strategy

Re-runs the current near-52w-high + uptrend signal through the honest engine: overlap inflation,
non-overlapping day-clustered edge vs a random control, by cap tier, plus a decay split. This is
what tells us whether the published z-scores (Small 14.52, Mid 2.88, Large 2.28) are real or fiction.

**Create new file `backtest_longterm.py`** with EXACTLY this content:
```python
"""Validate the long-term momentum strategy through the honest engine. The short-term went through
this; the long-term never did - every published long z-score is overlap-inflated and zero-cost.

Signal (price-computable core of tools.get_swing_levels_long): near the 252-day high AND uptrend
  dist_from_high_252 > -0.10  AND  close > sma_50 > sma_200
('outperforming Nifty' is dropped - it needs the Nifty series and is a refinement, not the core the
cap-tier claims rested on.) Percentage stops, 20-day horizon, costs charged.

    python backtest_longterm.py
"""

import numpy as np
import pandas as pd

from backtest_engine import simulate_trades, day_clustered_edge, average_uniqueness
from config import CAP_BUCKET_MAP, LONG_STOP_PCT, LONG_TARGET_PCT, LONG_HORIZON_DAYS

PANEL = "cache/backtest_5y_long.pkl"
H = LONG_HORIZON_DAYS


def load():
    d = pd.read_pickle(PANEL)
    out = []
    for t, df in d.items():
        df = df.sort_values('date').reset_index(drop=True)
        if len(df) < 300:
            continue
        out.append((t, CAP_BUCKET_MAP.get(t), df))
    return out


def signal(df):
    return ((df['dist_from_high_252'] > -0.10) & (df['close'] > df['sma_50'])
            & (df['sma_50'] > df['sma_200'])).fillna(False).values


def _sim(df, mask):
    return simulate_trades(df, mask, horizon_days=H, stop_pct=LONG_STOP_PCT, target_pct=LONG_TARGET_PCT)


def collect(panel, universe, seed=42):
    rng = np.random.default_rng(seed)
    strat, ctrl = [], []
    for t, cap, df in panel:
        if not universe(cap):
            continue
        dates = df['date'].values
        for lst, mask in ((strat, signal(df)), (ctrl, rng.random(len(df)) < 0.05)):
            for tr in _sim(df, mask):
                tr['entry_date'] = dates[tr['entry_idx']]
                lst.append(tr)
    return strat, ctrl


def uniqueness(panel, universe):
    vals = []
    for t, cap, df in panel:
        if not universe(cap):
            continue
        trs = simulate_trades(df, signal(df), horizon_days=H, allow_overlap=True,
                              stop_pct=LONG_STOP_PCT, target_pct=LONG_TARGET_PCT)
        if trs:
            vals.append(average_uniqueness(trs, len(df)))
    return float(np.mean(vals)) if vals else 1.0


def row(label, strat, ctrl):
    if len(strat) < 30:
        print(f"  {label:<22}{len(strat):>7} trades - too few")
        return
    net = np.mean([t['net_pct'] for t in strat])
    clu = day_clustered_edge(strat, ctrl)
    z = clu['z_paired'] if clu else float('nan')
    days = clu['n_days'] if clu else 0
    win = np.mean([t['net_pct'] > 0 for t in strat]) * 100
    print(f"  {label:<22}{len(strat):>7}{days:>6}{net:>+9.2f}%{win:>6.0f}%{z:>9.2f}")


def run():
    panel = load()
    print(f"Panel {len(panel)} stocks, {panel[0][2]['date'].min().date()} -> "
          f"{panel[0][2]['date'].max().date()}, horizon {H}d, "
          f"stop {LONG_STOP_PCT*100:.0f}%/target {LONG_TARGET_PCT*100:.0f}%, costs charged\n")

    print("OVERLAP - how inflated the old z-scores were (uniqueness 1.0 = independent):")
    for cap in ('Small', 'Mid', 'Large'):
        u = uniqueness(panel, lambda c, cap=cap: c == cap)
        print(f"  {cap:<8} avg uniqueness {u:.3f}  ->  naive-z inflation ~{(1/max(u,1e-6))**0.5:.2f}x")

    print("\nDAY-CLUSTERED EDGE vs random control, by cap tier:")
    print(f"  {'segment':<22}{'trades':>7}{'days':>6}{'net/tr':>10}{'win':>6}{'z_paired':>9}")
    for cap, pub in [('Small', 14.52), ('Mid', 2.88), ('Large', 2.28)]:
        s, c = collect(panel, lambda cp, cap=cap: cp == cap)
        row(f"{cap} (pub z {pub})", s, c)

    print("\nDECAY - recent third vs older two-thirds (Small+Mid):")
    s, c = collect(panel, lambda cp: cp in ('Small', 'Mid'))
    s = sorted(s, key=lambda t: t['entry_date'])
    if len(s) > 30:
        cut = s[int(len(s) * 0.67)]['entry_date']
        for label, keep in [("older 2/3", lambda t: t['entry_date'] < cut),
                            ("recent 1/3", lambda t: t['entry_date'] >= cut)]:
            row(label, [t for t in s if keep(t)], [t for t in c if keep(t)])

    print("\nz_paired >= 2 holds | 1-2 weak | < 1 not distinguishable from random. "
          "Single tests, not search-adjusted.")


if __name__ == "__main__":
    try:
        run()
    except FileNotFoundError:
        print("cache/backtest_5y_long.pkl not found - run build_backtest_panel_long.py first.")
```

---

## PHASE 4 — Research the upgrade: cross-sectional momentum + low-vol overlay

Tests the strongest, India-proven long-term factor (cross-sectional 12M-1M momentum) as a ranked
sort, and a low-volatility overlay (the price-only proxy for "quality momentum" that beat the Nifty
in every regime). Buy-and-hold 20 days (standard momentum-sort convention — no stops), net of costs.

**Create new file `backtest_longterm_xsec.py`** with EXACTLY this content:
```python
"""Cross-sectional momentum (rank the universe, buy the top) vs the current screen, plus a low-vol
overlay. A TRUE fundamental-quality filter (ROE/debt) needs historical point-in-time fundamentals
the panel does not have - that is a LIVE filter, not backtestable here (see long-term-fix.md).

Each date: rank Mid/Small liquid stocks by 12M-1M momentum (close[t-21]/close[t-252]-1). Take the
top decile, hold H=20 days, net of costs. Day-clustered against the SAME-day mean of the whole
liquid universe (the honest control for a cross-sectional sort).

    python backtest_longterm_xsec.py
"""

import numpy as np
import pandas as pd

from backtest_engine import day_clustered_edge
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR, LONG_HORIZON_DAYS, round_trip_cost_pct

PANEL = "cache/backtest_5y_long.pkl"
H = LONG_HORIZON_DAYS


def build_rows():
    d = pd.read_pickle(PANEL)
    rows = []
    for t, df in d.items():
        if CAP_BUCKET_MAP.get(t) not in ('Small', 'Mid'):   # ponytail: Mid/Small first; add Large only if it survives
            continue
        df = df.sort_values('date').reset_index(drop=True)
        if len(df) < 300:
            continue
        c = df['close'].values
        turn = df['turnover_60d'].values
        n = len(c)
        mom = np.full(n, np.nan)
        fwd = np.full(n, np.nan)
        for i in range(252, n - H):
            if c[i - 252] > 0:
                mom[i] = c[i - 21] / c[i - 252] - 1
            if c[i] > 0:
                fwd[i] = (c[i + H] - c[i]) / c[i] * 100 - round_trip_cost_pct(turn[i])
        rows.append(pd.DataFrame({'date': df['date'].values, 'ticker': t, 'mom': mom,
                                  'vol': df['volatility_10'].values, 'fwd': fwd, 'turn': turn}))
    a = pd.concat(rows).dropna(subset=['mom', 'fwd'])
    return a[a['turn'] >= MIN_TURNOVER_INR].copy()


def clustered(sel, universe):
    strat = [{'entry_date': d, 'net_pct': r} for d, r in zip(sel['date'], sel['fwd'])]
    ctrl = [{'entry_date': d, 'net_pct': r} for d, r in zip(universe['date'], universe['fwd'])]
    return day_clustered_edge(strat, ctrl)


def run():
    a = build_rows()
    a['mom_rank'] = a.groupby('date')['mom'].rank(pct=True)
    a['vol_rank'] = a.groupby('date')['vol'].rank(pct=True)
    print(f"{a['ticker'].nunique()} Mid/Small liquid stocks, {len(a)} stock-days, "
          f"12M-1M momentum, {H}d hold, costs charged")
    print("Control = same-day mean of ALL liquid Mid/Small stocks.\n")
    print(f"  {'strategy':<30}{'trades':>8}{'days':>6}{'net/tr':>10}{'z_paired':>9}")
    for label, sel in [
            ("top-decile momentum", a[a['mom_rank'] >= 0.90]),
            ("top-decile mom + low-vol half", a[(a['mom_rank'] >= 0.90) & (a['vol_rank'] <= 0.50)]),
            ("top-quartile momentum", a[a['mom_rank'] >= 0.75])]:
        clu = clustered(sel, a)
        if clu is None or len(sel) < 30:
            print(f"  {label:<30}{len(sel):>8} too few")
            continue
        print(f"  {label:<30}{len(sel):>8}{clu['n_days']:>6}{sel['fwd'].mean():>+9.2f}%{clu['z_paired']:>9.2f}")
    print("\nz_paired >= 2 = the rank beats the universe average on its own days. If low-vol lifts z")
    print("over plain momentum, that is the price-only signal of the 'quality momentum' effect.")


if __name__ == "__main__":
    try:
        run()
    except FileNotFoundError:
        print("cache/backtest_5y_long.pkl not found - run build_backtest_panel_long.py first.")
```

---

## VERIFICATION — run in this order; paste ALL output back to the reviewer
```bash
python backtest_engine.py            # self-check must still print "backtest_engine.py self-check passed"
python build_backtest_panel_long.py  # ~several minutes; downloads 5y for the universe
python backtest_longterm.py          # PASTE FULL OUTPUT
python backtest_longterm_xsec.py     # PASTE FULL OUTPUT
```
Expected: engine self-check passes; the panel saves `N/N stocks`; both backtests print their
tables with no traceback. **The two backtest tables are the deliverable — paste them verbatim.**

---

## DEFERRED — NOT in this pass (do not attempt; here so the reviewer knows why)
- **Fundamental quality overlay (ROE / debt / earnings filter)** — the highest-value idea from
  research, BUT it needs historical *point-in-time* fundamentals which the price panel does not
  contain and yfinance does not serve as a time series. It can only be applied as a **live** scan
  filter, not backtested here. Phase 4's low-vol overlay is the backtestable price-only proxy.
- **PEAD (earnings-surprise drift)** — needs historical earnings-surprise data (actual vs expected)
  the repo lacks. Defer until an earnings-surprise source exists.
- **Momentum-crash regime protection / long-term meta-label** — sequenced after the core is shown
  to be real; not worth building on an unvalidated base.
- **ADOPTION of any result** — wiring a signal into `tools.py`/`mcp_server.py`, replacing
  `GROSS_EDGE_LONG_PCT`, updating the caveats in `long_term_issues.md`'s table, or the README —
  ALL happen in a later pass, decided by the reviewer from your measured numbers. A claim that
  fails its z_paired gets **retired**, not softened (same standard as the README REJECTED table).

## DO NOT TOUCH
`tools.py`, `mcp_server.py`, `config.py`, `README.md`, `features.py`, any `test_*.py`, and every
existing `backtest_*.py`. This pass only ADDS three files and makes the one small `simulate_trades`
change in `backtest_engine.py`.
