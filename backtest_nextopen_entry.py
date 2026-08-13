"""Does entering the momentum picks at the NEXT-day open (the realistic time - you see the rank
after close, you buy next morning) beat/erode the current model, which enters at the signal-day
CLOSE? Same universe, same ranking, same costs, same day-clustered control as backtest_longterm_xsec.

  A close->close   : current model      enter close[i],   exit close[i+H]
  B nextopen->close: entry delayed 1 day enter open[i+1],  exit close[i+H]   (isolates gap cost)
  C nextopen->hold : realistic full hold enter open[i+1],  exit close[i+1+H]
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
        if CAP_BUCKET_MAP.get(t) not in ('Small', 'Mid'):
            continue
        df = df.sort_values('date').reset_index(drop=True)
        if len(df) < 300:
            continue
        c = df['close'].values
        o = df['open'].values
        turn = df['turnover_60d'].values
        n = len(c)
        mom = np.full(n, np.nan)
        fwd_A = np.full(n, np.nan)
        fwd_B = np.full(n, np.nan)
        fwd_C = np.full(n, np.nan)
        for i in range(252, n - H - 1):
            if c[i - 252] > 0:
                mom[i] = c[i - 21] / c[i - 252] - 1
            cost = round_trip_cost_pct(turn[i])
            if c[i] > 0:
                fwd_A[i] = (c[i + H] - c[i]) / c[i] * 100 - cost
            if o[i + 1] > 0:
                fwd_B[i] = (c[i + H] - o[i + 1]) / o[i + 1] * 100 - cost
                fwd_C[i] = (c[i + 1 + H] - o[i + 1]) / o[i + 1] * 100 - cost
        rows.append(pd.DataFrame({'date': df['date'].values, 'ticker': t, 'mom': mom,
                                  'fwd_A': fwd_A, 'fwd_B': fwd_B, 'fwd_C': fwd_C, 'turn': turn}))
    a = pd.concat(rows).dropna(subset=['mom', 'fwd_A', 'fwd_B', 'fwd_C'])
    return a[a['turn'] >= MIN_TURNOVER_INR].copy()


def clustered(sel, universe, col):
    strat = [{'entry_date': d, 'net_pct': r} for d, r in zip(sel['date'], sel[col])]
    ctrl = [{'entry_date': d, 'net_pct': r} for d, r in zip(universe['date'], universe[col])]
    return day_clustered_edge(strat, ctrl)


def run():
    a = build_rows()
    a['mom_rank'] = a.groupby('date')['mom'].rank(pct=True)
    sel = a[a['mom_rank'] >= 0.90]
    print(f"{a['ticker'].nunique()} Mid/Small liquid stocks, {len(sel)} top-decile stock-days, "
          f"{H}d hold, costs charged")
    print("Control = same-day mean of ALL liquid Mid/Small stocks (paired).\n")
    print(f"  {'entry -> exit':<34}{'net/tr':>10}{'z_paired':>10}")
    for label, col in [("A close[i]   -> close[i+H]  (current)", 'fwd_A'),
                       ("B open[i+1]  -> close[i+H]  (delay)", 'fwd_B'),
                       ("C open[i+1]  -> close[i+1+H] (real)", 'fwd_C')]:
        clu = clustered(sel, a, col)
        print(f"  {label:<34}{sel[col].mean():>+9.2f}%{clu['z_paired']:>10.2f}")
    print(f"\n(control net/tr for reference: A {a['fwd_A'].mean():+.2f}%  "
          f"C {a['fwd_C'].mean():+.2f}%)")


if __name__ == "__main__":
    run()
