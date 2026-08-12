# reversal-entry-test.md — does waiting for the bounce to START beat buying while still falling?

**The idea to test:** the current strategy buys a stock while it's still oversold and falling
(RSI < 30). This tests an alternative: **wait until RSI turns back UP** (crosses above a threshold
after being oversold) — i.e. buy once the bounce has actually begun, giving up the exact bottom in
exchange for confirmation the turn started.

## Context for the executor (this repo)
- It's a backtested NSE swing-trading tool. All backtests reuse `backtest_engine.py` — do NOT
  reinvent stats. `simulate_trades(...)` runs non-overlapping trades with honest fills and costs;
  `day_clustered_edge(...)` gives the headline `z_paired` (trades on the same day aren't independent,
  so this is the honest significance, not trade-level z).
- The 5-year data panel is `cache/backtest_5y_short.pkl` — a dict `{ticker: DataFrame}` with columns
  including `date, open, high, low, close, rsi, atr, turnover_60d`.
- The live strategy: RSI<30, Mid/Small-cap, ≥₹25cr turnover, 6-day hold, **4×ATR stop**, costs charged.

## Your job
- Create the ONE file below **exactly**. Reuse the engine; change nothing else. Do NOT commit.
- Run it and **paste the full console output** back. `PYTHONIOENCODING=utf-8` on Windows.
- Do NOT change any live tool — this only MEASURES.

## Create `backtest_reversal.py` — EXACTLY this content:
```python
"""Reversal-confirmation entry test: does waiting for RSI to turn back UP beat buying while still
oversold (falling)?

Baseline (current strategy): enter when RSI < 30.
Reversal: enter when RSI CROSSES BACK ABOVE a threshold, having been < 30 the previous bar.

Same everywhere: live universe (Mid/Small, >=Rs25cr), 6-day hold, 4xATR stop, costs charged,
day-clustered vs a same-day random-entry control. Compare net/trade, win rate, z_paired, and
trade count (confirmation fires fewer, later trades).

    python backtest_reversal.py
"""

import numpy as np
import pandas as pd

from backtest_engine import simulate_trades, day_clustered_edge
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR

PANEL = "cache/backtest_5y_short.pkl"
H = 6
STOP = 4.0


def load():
    panel = pd.read_pickle(PANEL)
    out = []
    for t, df in panel.items():
        if CAP_BUCKET_MAP.get(t) not in ('Mid', 'Small'):
            continue
        d = df.sort_values('date').reset_index(drop=True)
        if len(d) < 300:
            continue
        out.append((t, d))
    return out


def baseline_mask(d):                      # buy while still oversold (current strategy)
    return ((d['rsi'] < 30) & (d['turnover_60d'] >= MIN_TURNOVER_INR)).fillna(False).values


def reversal_mask(d, thr):                 # buy when RSI crosses up to >=thr, was <30 the bar before
    rsi = d['rsi'].values
    prev_oversold = np.concatenate([[False], rsi[:-1] < 30])
    turn = np.nan_to_num(d['turnover_60d'].values) >= MIN_TURNOVER_INR
    return (rsi >= thr) & prev_oversold & turn


def collect(panel, sigfn, seed=42):
    rng = np.random.default_rng(seed)
    strat, ctrl = [], []
    for t, d in panel:
        dates = d['date'].values
        for lst, m in ((strat, sigfn(d)), (ctrl, rng.random(len(d)) < 0.05)):
            for tr in simulate_trades(d, m, horizon_days=H, stop_atr_mult=STOP):
                tr['entry_date'] = dates[tr['entry_idx']]
                lst.append(tr)
    return strat, ctrl


def row(label, strat, ctrl):
    if len(strat) < 30:
        print(f"  {label:<28}{len(strat):>7} trades - too few")
        return
    net = np.mean([x['net_pct'] for x in strat])
    clu = day_clustered_edge(strat, ctrl)
    z = clu['z_paired'] if clu else float('nan')
    days = clu['n_days'] if clu else 0
    win = np.mean([x['net_pct'] > 0 for x in strat]) * 100
    print(f"  {label:<28}{len(strat):>7}{days:>6}{net:>+9.3f}%{win:>6.0f}%{z:>9.2f}")


def run():
    panel = load()
    print(f"{len(panel)} Mid/Small stocks, {H}-day hold, {STOP:g}xATR stop, costs charged. "
          f"Control = same-day random entries.\n")
    print(f"  {'entry rule':<28}{'trades':>7}{'days':>6}{'net/tr':>10}{'win':>6}{'z_paired':>9}")
    s, c = collect(panel, baseline_mask)
    row("baseline: RSI<30 (falling)", s, c)
    for thr in (30, 33, 35):
        s, c = collect(panel, lambda d, thr=thr: reversal_mask(d, thr))
        row(f"reversal: RSI crosses >={thr}", s, c)
    print("\nRead: a reversal rule wins only if it beats baseline on net/trade AND z_paired. Expect")
    print("FEWER trades (confirmation is selective). Higher net at LOWER z_paired = fewer paired days /")
    print("weaker evidence, not a real win - z_paired is the headline number here.")


if __name__ == "__main__":
    try:
        run()
    except FileNotFoundError:
        print("cache/backtest_5y_short.pkl not found - build the 5y panel first.")
```

## What the numbers mean
- **baseline** = today's strategy (buy while falling).
- **reversal >=30/33/35** = buy once RSI has turned back up past that level.
- A reversal rule is only better if **both** net/trade **and** `z_paired` beat baseline. If it just
  has higher net/trade but lower `z_paired`, that's fewer trades / weaker evidence, not a real edge.
- Also compare **trade count**: confirmation trades later, so it fires less often — a big drop in
  count for only a small net gain is usually not worth it.
