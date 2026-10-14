"""Market-state gate for the long-term momentum basket (Cooper, Gutierrez & Hameed 2004; Daniel &
Moskowitz 2016: momentum pays after UP markets and crashes after DOWN ones). Pre-registered:

    DOWN state = Nifty 50 trailing 12-month return < 0 on the rebalance (signal) date.
    Gate passes if (a) the basket's edge over the universe is lower in DOWN than UP months,
    Welch z >= 2 on the monthly edges, and (b) the basket's own return in DOWN months is <= 0
    (otherwise sitting out costs money even if the edge shrinks).

Same method as backtest_longterm_exits.py: one rebalance every 20 sessions, all 20 offsets,
entry next open, 20d hold, no stop/target, costs charged. Also reported (not pre-registered,
descriptive only): a secondary state from the Mid/Small universe's own equal-weight 12M return.

    python backtest_longterm_marketstate.py
"""

import numpy as np
import pandas as pd
import yfinance as yf

from backtest_longterm_exits import STEP, build
from backtest_longterm_recheck import enrich


def nifty_12m():
    n = yf.download("^NSEI", start="2012-01-01", progress=False, auto_adjust=True)['Close']
    n = n.squeeze() if isinstance(n, pd.DataFrame) else n
    n.index = pd.to_datetime(n.index).tz_localize(None)
    return n / n.shift(252) - 1


def monthly(a, dates, off):
    """Per rebalance date: basket mean, universe mean, edge."""
    u = a[a['date'].isin(set(dates[off::STEP]))]
    b = u[u['mom_rank'] >= 0.75].groupby('date')['fwd'].mean()
    m = u.groupby('date')['fwd'].mean()
    return pd.DataFrame({'basket': b, 'univ': m, 'edge': b - m})


def welch(x, y):
    if len(x) < 2 or len(y) < 2:
        return np.nan
    return (x.mean() - y.mean()) / np.sqrt(x.var(ddof=1) / len(x) + y.var(ddof=1) / len(y))


def report(tag, rows):
    """rows = list over offsets of (months_df with 'down' col)."""
    print(f"\n=== state: {tag} ===")
    zs, ds = [], []
    for k, r in enumerate(rows):
        dn, up = r[r['down']], r[~r['down']]
        zs.append(welch(up['edge'], dn['edge']))
        ds.append(len(dn))
        if k == 0:
            print(f"  offset 0: {len(r)} months, {len(dn)} DOWN")
            print(f"  {'':6}{'months':>7}{'basket':>9}{'universe':>10}{'edge':>8}{'basket<0':>10}{'worst month':>13}")
            for lab, x in (('UP', up), ('DOWN', dn)):
                if len(x):
                    print(f"  {lab:<6}{len(x):>7}{x['basket'].mean():>+8.2f}%{x['univ'].mean():>+9.2f}%"
                          f"{x['edge'].mean():>+7.2f}%{(x['basket'] < 0).mean():>10.0%}{x['basket'].min():>+12.1f}%")
            if len(dn):
                print("  DOWN months: " + ', '.join(f"{d.date()} {v:+.1f}%" for d, v in dn['basket'].items()))
    zs = np.array(zs, float)
    print(f"  edge UP minus DOWN, Welch z over 20 offsets: median {np.nanmedian(zs):.2f}, "
          f"range {np.nanmin(zs):.2f}..{np.nanmax(zs):.2f}  (DOWN months per offset {min(ds)}-{max(ds)})")


def run():
    a, arrs = build()
    a = enrich(a, arrs)
    a['date'] = pd.to_datetime(a['date'])
    dates = np.sort(a['date'].unique())
    n12 = nifty_12m()

    # secondary: equal-weight 12M return of the liquid Mid/Small universe (mom column is 12M-1M; use
    # the full-window cross-sectional mean of mom as a cheap proxy)
    ew = a.groupby('date')['mom'].mean()

    nif, ewr = [], []
    for off in range(STEP):
        r = monthly(a, dates, off)
        s = n12.reindex(r.index, method='ffill')
        nif.append(r.assign(down=(s < 0).values))
        ewr.append(r.assign(down=(ew.reindex(r.index) < 0).values))
    report("Nifty 50 trailing 12M < 0  (PRE-REGISTERED)", nif)
    report("Mid/Small equal-weight 12M-1M < 0  (descriptive only)", ewr)

    r = nif[0]
    print("\nWhere were the bad basket months? (offset 0, 5 worst)")
    for d, row in r.sort_values('basket').head(5).iterrows():
        print(f"  {d.date()}  basket {row['basket']:+.1f}%  universe {row['univ']:+.1f}%  "
              f"Nifty 12M {n12.reindex([d], method='ffill').iloc[0]:+.1%}")


if __name__ == "__main__":
    run()
