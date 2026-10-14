"""Cross-sectional momentum (rank the universe, buy the top) vs the current screen, plus a low-vol
overlay. A TRUE fundamental-quality filter (ROE/debt) needs historical point-in-time fundamentals
the panel does not have - that is a LIVE filter, not backtestable here (see long-term-fix.md).

Each date: rank Mid/Small liquid stocks by 12M-1M momentum (close[t-21]/close[t-252]-1). Take the
top decile, ENTER AT THE NEXT SESSION'S OPEN (the screen runs after close, so signal-day close is
unbuyable look-ahead - see backtest_nextopen_entry.py), hold H=20 days, net of costs. Day-clustered
against the SAME-day mean of the whole liquid universe (the honest control for a cross-sectional sort).

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
        o = df['open'].values
        turn = df['turnover_60d'].values
        n = len(c)
        vol = pd.Series(c).rolling(10).std().values
        mom = np.full(n, np.nan)
        fwd = np.full(n, np.nan)
        ret_1m = np.full(n, np.nan)      # the month the 12M-1M rank deliberately skips
        fwd60 = np.full(n, np.nan)       # same entry, 3x the hold - does the rally give it back?
        ret_3m = np.full(n, np.nan)
        for i in range(252, n - H - 1):
            if c[i - 252] > 0:
                mom[i] = c[i - 21] / c[i - 252] - 1
            if c[i - 21] > 0:
                ret_1m[i] = c[i] / c[i - 21] - 1
            if c[i - 60] > 0:
                ret_3m[i] = c[i] / c[i - 60] - 1     # trailing 60d - the sector-strength input
            if o[i + 1] > 0:  # enter next open, exit close[i+1+H] - no signal-day-close look-ahead
                fwd[i] = (c[i + 1 + H] - o[i + 1]) / o[i + 1] * 100 - round_trip_cost_pct(turn[i])
                if i + 61 < n:
                    fwd60[i] = (c[i + 61] - o[i + 1]) / o[i + 1] * 100 - round_trip_cost_pct(turn[i])
        rows.append(pd.DataFrame({'date': df['date'].values, 'ticker': t, 'mom': mom,
                                  'vol': vol, 'fwd': fwd, 'turn': turn, 'ret_1m': ret_1m, 'fwd60': fwd60, 'ret_3m': ret_3m,
                                  'above200': c / df['sma_200'].values - 1,
                                  'dh': df['dist_from_high_252'].values,
                                  'rsi': df['rsi'].values}))
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