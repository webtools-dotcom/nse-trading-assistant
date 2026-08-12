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