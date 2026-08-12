"""OOS / stability gate for the cross-sectional long-term momentum strategy (validated pooled in
backtest_longterm_xsec.py, z 8-9). The rank is pre-committed (no threshold fitted), so the honest
out-of-sample question is TEMPORAL: does the edge hold across chronological periods - especially
the recent one - or is the pooled z carried by a few good years?

Reuses backtest_longterm_xsec.build_rows (same data path). Adds: z_paired per chronological fifth,
recent-third vs older, and a deflated-Sharpe across the variants tested.

    python backtest_longterm_oos.py
"""

import numpy as np
import pandas as pd

from backtest_engine import day_clustered_edge, sharpe, deflated_sharpe
from backtest_longterm_xsec import build_rows, H


def zp(sel, universe):
    strat = [{'entry_date': d, 'net_pct': r} for d, r in zip(sel['date'], sel['fwd'])]
    ctrl = [{'entry_date': d, 'net_pct': r} for d, r in zip(universe['date'], universe['fwd'])]
    return day_clustered_edge(strat, ctrl)


def line(tag, sel, universe):
    clu = zp(sel, universe)
    if clu is None or len(sel) < 30:
        print(f"    {tag:<26}{len(sel):>7}  too few")
        return
    print(f"    {tag:<26}{len(sel):>7}{clu['n_paired_days']:>6}{sel['fwd'].mean():>+9.2f}%{clu['z_paired']:>9.2f}")


def run():
    a = build_rows()
    a['date'] = pd.to_datetime(a['date'])
    a['mom_rank'] = a.groupby('date')['mom'].rank(pct=True)
    a['vol_rank'] = a.groupby('date')['vol'].rank(pct=True)
    a['decile'] = a['mom_rank'] >= 0.90
    a['decile_lv'] = (a['mom_rank'] >= 0.90) & (a['vol_rank'] <= 0.50)

    print(f"{a['ticker'].nunique()} Mid/Small stocks, {len(a)} stock-days, {H}d hold, costs charged.")
    print("Control = same-day universe mean. z_paired >= 2 per period = holds out of sample.\n")

    edges = pd.date_range(a['date'].min(), a['date'].max(), periods=6)
    for col, label in [('decile', 'top-decile momentum'), ('decile_lv', 'top-decile + low-vol')]:
        print(f"  {label} - by chronological fifth:")
        print(f"    {'period':<26}{'trades':>7}{'days':>6}{'net/tr':>10}{'z_paired':>9}")
        for k in range(5):
            s, e = edges[k], edges[k + 1]
            per = a[(a['date'] >= s) & (a['date'] < e)]
            line(f"{s.date()} -> {e.date()}", per[per[col]], per)
        print()

    print("  Recent third vs older two-thirds:")
    print(f"    {'window':<26}{'trades':>7}{'days':>6}{'net/tr':>10}{'z_paired':>9}")
    cut = a['date'].quantile(0.67)
    for col, label in [('decile', 'decile'), ('decile_lv', 'decile+lowvol')]:
        for wlabel, w in [(f"{label} older 2/3", a['date'] < cut), (f"{label} recent 1/3", a['date'] >= cut)]:
            per = a[w]
            line(wlabel, per[per[col]], per)
    print()

    # Deflated Sharpe across the variants tried (weak guard - few, correlated variants).
    variants = {'decile': a['decile'], 'decile_lv': a['decile_lv'],
                'quartile': a['mom_rank'] >= 0.75}
    srs = {}
    for name, m in variants.items():
        daily = a[m].groupby('date')['fwd'].mean()
        srs[name] = sharpe(daily.values, holding_days=H)
    best = max(srs, key=srs.get)
    d = deflated_sharpe(srs[best], list(srs.values()), n_obs=int(a['date'].nunique()))
    print(f"  Deflated Sharpe: best='{best}' SR={srs[best]:.2f}, "
          f"P(real)={d['dsr']:.2f} over {len(srs)} variants (weak at this count; want > 0.95).")
    print("\n  Read: if z_paired >= 2 in most fifths AND the recent third holds, it survives OOS.")
    print("  A recent third that is negative-absolute but still z>2 vs control = regime, not decay.")


if __name__ == "__main__":
    try:
        run()
    except FileNotFoundError:
        print("cache/backtest_5y_long.pkl not found - run build_backtest_panel_long.py first.")
