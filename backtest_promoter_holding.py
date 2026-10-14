"""Does a change in PROMOTER HOLDING predict forward returns?

WHY THIS TEST IS DIFFERENT FROM backtest_fundamentals.py. That file's docstring explains why an
annual-statement factor cannot really be measured here: Indian FYs are almost all March-end, so
clustering honestly leaves ~4 fiscal cohorts and z_paired has no power by construction. Quarterly
shareholding filings escape all three of those problems:

  - `broadcastDate` is when NSE made the filing public. Entry is the next session's open after
    it, so there is no look-ahead - the same rule as backtest_news_events.py.
  - They are never restated in place: a revision is filed as its own row, so the number that was
    public at broadcast time is recoverable. Revised rows are dropped here rather than trusted.
  - Events land on ~900 distinct broadcast days, median ONE event per day. Day-clustering barely
    bites, unlike the RSI scan where hundreds of names fire together.

WHAT WILL LOOK LIKE AN EDGE AND IS NOT. Promoter holding drifts DOWN across this universe:
mean QoQ change -0.19pp, and falls outnumber rises 2.5:1. So a "promoters sold -> stock falls"
result can be entirely the universe's own drift plus whatever the market did on those days.
Only the day-paired control answers the question. This is the open_offer trap from CLAUDE.md
(naive z=7.17, paired z=0.44) waiting to happen again.

    python backtest_promoter_holding.py
    python backtest_promoter_holding.py --hold 10
"""

import argparse

import numpy as np
import pandas as pd

from backtest_engine import day_clustered_edge, edge_vs_control
from cache_manager import load_shareholding_archive
from config import CAP_BUCKET_MAP, round_trip_cost_pct

PANEL = "cache/backtest_5y_short.pkl"

# NSE bulk-loaded every pre-2022 filing into its archive in Jan-2022, giving them broadcast
# timestamps of 02:55 on 07-JAN-2022. Those are database artifacts, not disclosure dates, and
# using them as entry triggers would be look-ahead by another name.
BACKFILL_CUTOFF = '2022-02-01'
MAX_LAG_DAYS = 120       # filed more than a quarter late is a data problem, not an event
BUCKETS = [                                      # (label, low, high) in percentage points
    ('promoters sold >=5pp', -np.inf, -5.0),
    ('promoters sold 2-5pp', -5.0, -2.0),
    ('promoters sold 1-2pp', -2.0, -1.0),
    ('promoters sold 0.5-1pp', -1.0, -0.5),
    ('unchanged (+/-0.5pp)', -0.5, 0.5),
    ('promoters bought 0.5-1pp', 0.5, 1.0),
    ('promoters bought 1-2pp', 1.0, 2.0),
    ('promoters bought >=2pp', 2.0, np.inf),
]


def load_events():
    """One row per symbol-quarter: the promoter % change and the day it became public."""
    arc = load_shareholding_archive()
    df = pd.DataFrame([r for rows in arc.values() for r in rows])
    df['quarter'] = pd.to_datetime(df['date'].str.upper(), format='%d-%b-%Y', errors='coerce')
    df['bcast'] = pd.to_datetime(df['broadcastDate'].str.split().str[0].str.upper(),
                                 format='%d-%b-%Y', errors='coerce')
    df['pct'] = pd.to_numeric(df['pr_and_prgrp'], errors='coerce')
    df = df.dropna(subset=['quarter', 'bcast', 'pct'])

    # A revision restates a quarter already reported; the original row is the one that was public.
    df = df[df['revisedStatus'].astype(str).str.strip().isin(['-', '', 'None', 'nan'])]

    df = df.sort_values(['symbol', 'quarter'])
    df['chg'] = df['pct'] - df.groupby('symbol')['pct'].shift(1)
    df = df.dropna(subset=['chg'])

    lag = (df['bcast'] - df['quarter']).dt.days
    return df[(df['bcast'] >= BACKFILL_CUTOFF) & (lag.between(0, MAX_LAG_DAYS))]


def load_prices():
    panel = pd.read_pickle(PANEL)
    out = {}
    for ticker, d in panel.items():
        d = d.sort_values('date').reset_index(drop=True).copy()
        d['date'] = pd.to_datetime(d['date'])
        out[ticker.replace('.NS', '')] = d
    return out


def _trade(d, i, hold):
    """Entry at open of session i, exit at close hold sessions later, net of costs."""
    if i == 0 or i + hold >= len(d):
        return None
    entry, prev_close = d['open'].iloc[i], d['close'].iloc[i - 1]
    exit_px = d['close'].iloc[i + hold - 1]
    if not (np.isfinite(entry) and np.isfinite(exit_px) and entry > 0 and prev_close > 0):
        return None
    cost = round_trip_cost_pct(d['turnover_60d'].iloc[i] if 'turnover_60d' in d else None)
    return {'entry_date': d['date'].iloc[i],
            'gap_pct': (entry - prev_close) / prev_close * 100,
            'net_pct': (exit_px - entry) / entry * 100 - cost}


def simulate(events, prices, hold):
    trades = []
    for ev in events.itertuples():
        d = prices.get(ev.symbol)
        if d is None:
            continue
        idx = d.index[d['date'] > ev.bcast]      # first session whose OPEN is after the filing
        if len(idx) == 0:
            continue
        t = _trade(d, idx[0], hold)
        if t:
            trades.append({**t, 'symbol': ev.symbol, 'chg': ev.chg,
                           'cap': CAP_BUCKET_MAP.get(ev.symbol + '.NS', 'Unknown')})
    return pd.DataFrame(trades)


def control_trades(prices, dates, hold, per_day=12, seed=7):
    """Random Mid/Small entries on the SAME days. The market's own move is not an edge."""
    rng = np.random.default_rng(seed)
    syms = [s for s in prices if CAP_BUCKET_MAP.get(s + '.NS') in ('Mid', 'Small')]
    out = []
    for day in pd.unique(dates):
        for sym in rng.choice(syms, size=min(per_day, len(syms)), replace=False):
            d = prices[sym]
            idx = d.index[d['date'] >= day]
            if len(idx) == 0:
                continue
            t = _trade(d, idx[0], hold)
            if t:
                out.append(t)
    return pd.DataFrame(out)


def _rows(df):
    return [{'net_pct': r.net_pct, 'entry_date': r.entry_date} for r in df.itertuples()]


def report(label, sub, ctrl):
    if len(sub) < 30:
        return f"  {label:<28} {len(sub):>5}   too few to test"
    clu = day_clustered_edge(_rows(sub), _rows(ctrl))
    naive = edge_vs_control(sub['net_pct'], ctrl['net_pct'])
    zp = f"{clu['z_paired']:>8.2f}" if clu else "       -"
    days = f"{clu['n_paired_days']:>5}" if clu else "    -"
    return (f"  {label:<28} {len(sub):>5} {days} {sub['gap_pct'].mean():>+8.2f}% "
            f"{sub['net_pct'].mean():>+9.2f}% {naive['z']:>7.2f} {zp}")


HEADER = (f"  {'bucket':<28} {'n':>5} {'days':>5} {'gap':>9} {'net/trade':>10} "
          f"{'z_naive':>7} {'z_paired':>8}")


def main(hold):
    events, prices = load_events(), load_prices()
    trades = simulate(events, prices, hold)
    if trades.empty:
        print("no trades - is cache/backtest_5y_short.pkl built?")
        return
    ctrl = control_trades(prices, trades['entry_date'].values, hold)

    print("=" * 94)
    print(f"PROMOTER HOLDING CHANGE -> forward return, hold {hold} sessions, "
          f"entry next open after the NSE filing")
    print(f"events {len(trades)}  broadcast days {trades['entry_date'].nunique()}  "
          f"control trades {len(ctrl)}  control mean {ctrl['net_pct'].mean():+.2f}%")
    print("=" * 94)
    print(HEADER)
    for label, lo, hi in BUCKETS:
        print(report(label, trades[(trades['chg'] > lo) & (trades['chg'] <= hi)], ctrl))

    print("\n  " + "-" * 90)
    print("  Directional, any size beyond noise:")
    for label, sel in (("all sells (<= -0.5pp)", trades[trades['chg'] <= -0.5]),
                       ("all buys  (>= +0.5pp)", trades[trades['chg'] >= 0.5])):
        print(report(label, sel, ctrl))
        for cap in ('Small', 'Mid', 'Large'):
            print(report(f"    {label.split('(')[0].strip()} - {cap}",
                         sel[sel['cap'] == cap], ctrl))

    print("\n  z_paired is the headline. |z_paired| < 2.0 = not distinguishable from entering "
          "at random\n  on the same days, no matter how large z_naive looks: promoter holding "
          "drifts DOWN across\n  this universe (falls outnumber rises 2.5:1), so the naive "
          "number partly measures that drift.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=5, help="sessions held (default 5)")
    main(ap.parse_args().hold)
