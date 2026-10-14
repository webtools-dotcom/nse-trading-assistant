"""Does the live long-term exit rule (-8% stop / +16% target) help or hurt the momentum basket?

The validated basket (backtest_longterm_xsec.py) was measured as a plain 20-day hold with NO stop
and NO target. The -8%/+16% numbers the scan prints were inherited from the retired 52w-high
screen and never tested on this signal. Pre-registered variants (fixed before any run):
    none (20d hold)  |  stop -8% only  |  target +16% only  |  stop+target (LIVE)  |  60d hold vs 3x20d

Method
- Basket = top quartile of liquid Mid/Small by 12M-1M momentum (what tools.py surfaces), plus the
  top 20 by momentum (what he actually reads). Entry = next session's open, costs charged.
- NON-OVERLAPPING monthly rebalances: one entry date every 20 sessions. The older scripts entered
  every day with a 20-day hold, so consecutive days share ~19/20 of their path and the day-level
  z counts the same month ~20 times. Here each rebalance is one independent observation; the
  result is repeated for all 20 possible start offsets and the median/min reported.
- Exit fills: gap through the stop fills at the open (worse), gap through the target fills at the
  open (better); if a day's range spans both, the STOP is assumed (conservative).
- Paired test: each variant vs `none` on the SAME trades, per rebalance date (day_clustered_edge).
- Pass bar: z_paired >= 2.0 and the right sign in >= 3 of 5 chronological periods. Tail stats
  (P(<-20%), 10th pct) are reported per trade because he holds 1-2 names, not a basket.

    python backtest_longterm_exits.py
"""

import os

import numpy as np
import pandas as pd

from backtest_engine import day_clustered_edge
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR, round_trip_cost_pct

PANEL = os.environ.get("LONG_PANEL", "cache/backtest_5y_long.pkl")   # LONG_PANEL=cache/backtest_max_long.pkl for full history
H, H_LONG, STEP = 20, 60, 20
VARIANTS = {'none': (None, None), 'stop8': (0.08, None), 'tgt16': (None, 0.16), 'live': (0.08, 0.16)}


def sim(o, h, l, c, i, hold, stop, tgt):
    """Gross % of a trade signalled at close i, entered at open i+1, exited by close i+1+hold."""
    e = o[i + 1]
    S = e * (1 - stop) if stop else -np.inf
    T = e * (1 + tgt) if tgt else np.inf
    for j in range(i + 1, i + 2 + hold):
        if j > i + 1 and o[j] <= S:
            return (o[j] - e) / e * 100
        if j > i + 1 and o[j] >= T:
            return (o[j] - e) / e * 100
        if l[j] <= S:
            return (S - e) / e * 100
        if h[j] >= T:
            return (T - e) / e * 100
    return (c[i + 1 + hold] - e) / e * 100


def build():
    d = pd.read_pickle(PANEL)
    rows = []
    for t, df in d.items():
        if CAP_BUCKET_MAP.get(t) not in ('Small', 'Mid'):
            continue
        df = df.sort_values('date').reset_index(drop=True)
        if len(df) < 300:
            continue
        o, h, l, c = (df[k].values for k in ('open', 'high', 'low', 'close'))
        turn, n = df['turnover_60d'].values, len(df)
        for i in range(252, n - H - 1):
            if c[i - 252] <= 0 or o[i + 1] <= 0 or not turn[i] >= MIN_TURNOVER_INR:
                continue
            rows.append((df['date'].iat[i], t, c[i - 21] / c[i - 252] - 1, i, turn[i]))
    a = pd.DataFrame(rows, columns=['date', 'ticker', 'mom', 'i', 'turn'])
    a['date'] = pd.to_datetime(a['date'])
    if os.environ.get("LONG_END"):                     # e.g. 2021-08-12: only data the 5y panel never saw
        a = a[a['date'] < os.environ["LONG_END"]]
    a = a[a.groupby('date')['ticker'].transform('size') >= 40]   # early years: too few liquid names to rank
    a['mom_rank'] = a.groupby('date')['mom'].rank(pct=True)
    a['mom_pos'] = a.groupby('date')['mom'].rank(ascending=False)
    arrs = {t: tuple(df.sort_values('date')[k].values for k in ('open', 'high', 'low', 'close')) for t, df in d.items()}
    return a, arrs


def add_returns(sel, d):
    """Simulate every variant for the selected (ticker, i) rows only - the path loop is the cost."""
    out = {k: [] for k in list(VARIANTS) + ['h60']}
    for t, i, turn in zip(sel['ticker'], sel['i'], sel['turn']):
        o, h, l, c = d[t]
        cost = round_trip_cost_pct(turn)
        for k, (s, tg) in VARIANTS.items():
            out[k].append(sim(o, h, l, c, i, H, s, tg) - cost)
        out['h60'].append(sim(o, h, l, c, i, H_LONG, None, None) - cost if i + 2 + H_LONG <= len(c) else np.nan)
    for k, v in out.items():
        sel[k] = v
    return sel


def paired(sel, col, base='none'):
    s = sel.dropna(subset=[col, base])
    return day_clustered_edge([{'entry_date': x, 'net_pct': r} for x, r in zip(s['date'], s[col])],
                              [{'entry_date': x, 'net_pct': r} for x, r in zip(s['date'], s[base])])


def tail(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return f"{x.mean():+6.2f}% {np.median(x):+6.2f}% {(x > 0).mean():5.0%} {(x < -10).mean():6.1%} {(x < -20).mean():6.1%} {np.percentile(x, 10):+7.1f}%"


def run():
    a, d = build()
    dates = np.sort(a['date'].unique())
    for bname, bmask in [("TOP QUARTILE (validated basket)", a['mom_rank'] >= 0.75),
                         ("TOP 20 by momentum (what the scan shows)", a['mom_pos'] <= 20)]:
        basket = a[bmask]
        print(f"\n=== {bname} ===")
        # Every offset: which rebalance calendar you happen to start on should not matter.
        zs = {k: [] for k in ['stop8', 'tgt16', 'live']}
        for off in range(STEP):
            reb = set(dates[off::STEP])
            sel = add_returns(basket[basket['date'].isin(reb)].copy(), d)
            for k in zs:
                r = paired(sel, k)
                zs[k].append(r['z_paired'] if r else np.nan)
            if off == 0:
                s0 = sel
        n_reb = s0['date'].nunique()
        print(f"offset 0: {n_reb} monthly rebalances, {len(s0)} trades, net of costs, entry next open\n")
        print(f"  {'variant':<8}{'mean':>8}{'median':>8}{'win':>6}{'P<-10%':>7}{'P<-20%':>7}{'10th pct':>9}"
              f"{'edge vs none':>14}{'z_paired':>9}{'z med/min over 20 offsets':>28}")
        for k in VARIANTS:
            r = paired(s0, k) if k != 'none' else None
            ed = f"{r['day_edge']:+.2f}%" if r else ''
            z = f"{r['z_paired']:.2f}" if r else ''
            zz = f"{np.nanmedian(zs[k]):.2f} / {np.nanmin(zs[k]):.2f}" if k in zs else ''
            print(f"  {k:<8}{tail(s0[k])}{ed:>14}{z:>9}{zz:>28}")

        print("\n  by chronological fifth (offset 0) - edge of each variant vs none, per rebalance:")
        cuts = np.array_split(np.sort(s0['date'].unique()), 5)
        print(f"  {'period':<26}" + ''.join(f"{k:>10}" for k in ['none', 'stop8', 'tgt16', 'live']))
        for ch in cuts:
            per = s0[s0['date'].isin(ch)]
            base = per.groupby('date')['none'].mean()
            cells = [f"{base.mean():+9.2f}%"] + [f"{(per.groupby('date')[k].mean() - base).mean():+9.2f}%"
                                                  for k in ['stop8', 'tgt16', 'live']]
            print(f"  {str(pd.Timestamp(ch[0]).date()) + ' -> ' + str(pd.Timestamp(ch[-1]).date()):<26}" + ''.join(f"{x:>10}" for x in cells))

        # 60d hold vs three chained 20d rebalances over the same 60 sessions (same capital, same window).
        z60 = []
        for off in range(0, H_LONG, STEP):
            r60 = sorted(set(dates[off::H_LONG]))
            idx = {x: n for n, x in enumerate(dates)}
            pairs = []
            for x in r60:
                p = idx[x]
                legs = [dates[p + m] for m in (0, 20, 40) if p + m < len(dates)]
                if len(legs) < 3:
                    continue
                sel = add_returns(basket[basket['date'].isin(legs)].copy(), d)
                g = sel.groupby('date')['none'].mean()
                h60 = sel[sel['date'] == x]['h60'].mean()
                if len(g) == 3 and np.isfinite(h60):
                    chained = (np.prod(1 + g.values / 100) - 1) * 100
                    pairs.append(h60 - chained)
            p = np.array(pairs)
            if len(p) > 2:
                z60.append((len(p), p.mean(), p.mean() / (p.std(ddof=1) / np.sqrt(len(p)))))
        print("\n  60d hold minus 3x chained 20d rebalances (same window, both net of costs):")
        for n, m, z in z60:
            print(f"    {n} windows: {m:+.2f}% per 60 days, z {z:.2f}")

    # Re-measure the headline with the same independence rule: basket vs universe, one date per month.
    print("\n=== HEADLINE RE-CHECK: basket vs whole liquid universe, non-overlapping monthly ===")
    u0 = add_returns(a[a['date'].isin(set(dates[0::STEP]))].copy(), d)
    q = u0[u0['mom_rank'] >= 0.75]
    r = day_clustered_edge([{'entry_date': x, 'net_pct': v} for x, v in zip(q['date'], q['none'])],
                           [{'entry_date': x, 'net_pct': v} for x, v in zip(u0['date'], u0['none'])])
    print(f"  top quartile {q['none'].mean():+.2f}%/trade vs universe {u0['none'].mean():+.2f}%, "
          f"{r['n_paired_days']} rebalances, z_paired {r['z_paired']:.2f}  (published every-day z ~9.5)")


if __name__ == "__main__":
    run()
