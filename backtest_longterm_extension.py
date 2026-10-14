"""Is a stock that has ALREADY surged too far a worse buy? (the "Cupid question")

Answer: it does NOT return less - it carries a fatter left tail. Both gradients are real and
they point opposite ways, so this shipped as a per-name RISK LABEL, never a filter.
Full writeup and the reasoning error in the first pass: longterm_extension_results.md.

The live momentum scan ranks the liquid Mid/Small universe by 12M-1M momentum and shows the
top quartile sorted by momentum DESCENDING - so the most extended name in the market prints
first. That ordering was never tested. Neither was any over-extension cut.

Measured here, all inside the already-validated top-quartile basket, 20d hold, costs charged,
entry at next session's open:

  1. stretch buckets  - last-month return, % above 200DMA, distance from 52w high, RSI.
                        Control is BOTH the whole liquid universe (is the bucket tradeable?)
                        and the rest of the basket that same day (is the bucket worse than
                        its own peers? - the only question a FILTER answers).
  2. basket ordering  - top-N-by-momentum each day vs the basket mean. If the tool's sort is
                        backwards this shows it.
  3. rally age        - how long names stay in the basket, and forward return by how many days
                        they have already been in it. "When do we go in."

    python backtest_longterm_extension.py
"""

import numpy as np
import pandas as pd

from backtest_engine import day_clustered_edge
from backtest_longterm_xsec import build_rows, H

BANDS = [(0.30, 0.60), (0.60, 1.00), (1.00, 2.00), (2.00, 4.00), (4.00, 99.0)]


def zp(sel, ctrl, col='fwd'):
    sel, ctrl = sel.dropna(subset=[col]), ctrl.dropna(subset=[col])
    if len(sel) < 30:
        return None
    return day_clustered_edge(
        [{'entry_date': d, 'net_pct': r} for d, r in zip(sel['date'], sel[col])],
        [{'entry_date': d, 'net_pct': r} for d, r in zip(ctrl['date'], ctrl[col])])


def line(tag, sel, universe, basket):
    if len(sel) < 30:
        print(f"    {tag:<24}{len(sel):>8}  too few")
        return
    u, b = zp(sel, universe), zp(sel, basket[~basket.index.isin(sel.index)])
    print(f"    {tag:<24}{len(sel):>8}{sel['fwd'].mean():>+9.2f}%"
          f"{(u['z_paired'] if u else float('nan')):>10.2f}{(b['z_paired'] if b else float('nan')):>12.2f}")


def buckets(basket, universe, col, label, n=5):
    print(f"  {label} - quintiles inside the top-quartile basket:")
    print(f"    {'bucket':<24}{'trades':>8}{'net/tr':>10}{'z vs univ':>10}{'z vs basket':>12}")
    q = basket.groupby('date')[col].rank(pct=True)
    for k in range(n):
        lo, hi = k / n, (k + 1) / n
        sel = basket[(q > lo) & (q <= hi)] if k else basket[q <= hi]
        fmt = (lambda v: f"{v:.0f}") if col == 'rsi' else (lambda v: f"{v:+.0%}")
        rng = f"Q{k+1} ({fmt(sel[col].min())}..{fmt(sel[col].max())})" if len(sel) else f"Q{k+1}"
        line(rng, sel, universe, basket)
    print()


def run():
    a = build_rows()
    a['date'] = pd.to_datetime(a['date'])
    a = a.dropna(subset=['ret_1m', 'above200', 'dh', 'rsi']).reset_index(drop=True)
    a['mom_rank'] = a.groupby('date')['mom'].rank(pct=True)
    basket = a[a['mom_rank'] >= 0.75]

    print(f"{a['ticker'].nunique()} Mid/Small liquid stocks, {len(a)} stock-days, {H}d hold, "
          f"costs charged, entry next open.")
    print(f"Basket = top-quartile 12M-1M momentum ({len(basket)} stock-days).")
    bz = zp(basket, a)
    print(f"Baseline basket: net {basket['fwd'].mean():+.2f}%/trade, z vs universe {bz['z_paired']:.2f}\n")

    # 0. THE HEADLINE TEST: absolute momentum bands. Ranked quintiles (section 1 below) average a
    # +60% name together with a +630% name and hide the extreme tail entirely - that mistake is why
    # the first pass of this study reported the wrong conclusion. Bucket by the ABSOLUTE quantity
    # when the question is about an extreme.
    print("  ABSOLUTE 12M momentum bands inside the basket - return AND tail risk:")
    print(f"    {'band':<14}{'trades':>8}{'net/tr':>9}{'z vs bskt':>10}"
          f"{'P(-10%)':>9}{'P(-20%)':>9}{'p10':>8}{'net 60d':>9}")
    for lo, hi in BANDS:
        sel = basket[(basket['mom'] >= lo) & (basket['mom'] < hi)]
        tag = f"{lo:.0%}-{hi:.0%}" if hi < 90 else f"{lo:.0%}+"
        if len(sel) < 30:
            print(f"    {tag:<14}{len(sel):>8}  too few")
            continue
        z = zp(sel, basket[~basket.index.isin(sel.index)])
        print(f"    {tag:<14}{len(sel):>8}{sel['fwd'].mean():>+8.2f}%"
              f"{(z['z_paired'] if z else float('nan')):>10.2f}"
              f"{(sel['fwd'] < -10).mean():>8.0%}{(sel['fwd'] < -20).mean():>9.0%}"
              f"{sel['fwd'].quantile(0.10):>+7.1f}%{sel['fwd60'].mean():>+8.2f}%")
    print("    Return rises with momentum -> an over-extension CUT would delete the best names.")
    print("    P(-20%) rises with it too -> a basket absorbs that tail, a single position does not.\n")

    print("  Rank position inside the basket (the scan shows rank #1 first):")
    print(f"    {'slice':<14}{'trades':>8}{'net/tr':>9}{'z vs bskt':>10}{'P(-10%)':>9}{'P(-20%)':>9}{'p10':>8}")
    rk = basket.groupby('date')['mom'].rank(ascending=False, method='first')
    for tag, m in [('rank #1', rk == 1), ('rank 2-5', (rk > 1) & (rk <= 5)),
                   ('rank 6-20', (rk > 5) & (rk <= 20)), ('rank 21+', rk > 20)]:
        sel = basket[m]
        z = zp(sel, basket[~basket.index.isin(sel.index)])
        print(f"    {tag:<14}{len(sel):>8}{sel['fwd'].mean():>+8.2f}%"
              f"{(z['z_paired'] if z else float('nan')):>10.2f}"
              f"{(sel['fwd'] < -10).mean():>8.0%}{(sel['fwd'] < -20).mean():>9.0%}"
              f"{sel['fwd'].quantile(0.10):>+7.1f}%")
    print()

    print("  Is the RISK gradient stable? (the return means in thin bands are NOT - see below)")
    print(f"    {'band':<14}{'period':<14}{'trades':>8}{'P(-20%)':>9}{'p10':>8}")
    edges3 = pd.date_range(basket['date'].min(), basket['date'].max(), periods=4)
    for lo, hi in BANDS:
        for k in range(3):
            st, en = edges3[k], edges3[k + 1]
            sel = basket[(basket['date'] >= st) & (basket['date'] < en) &
                         (basket['mom'] >= lo) & (basket['mom'] < hi)]
            tag = (f"{lo:.0%}-{hi:.0%}" if hi < 90 else f"{lo:.0%}+") if k == 0 else ""
            if len(sel) < 50:
                print(f"    {tag:<14}{str(st.date()):<14}{len(sel):>8}   too few")
                continue
            print(f"    {tag:<14}{str(st.date()):<14}{len(sel):>8}"
                  f"{(sel['fwd'] < -20).mean():>8.0%}{sel['fwd'].quantile(0.10):>+7.1f}%")
    print()

    buckets(basket, a, 'ret_1m', "Last-month return (the surge he can see)")
    buckets(basket, a, 'above200', "% above 200DMA (stretch)")
    buckets(basket, a, 'dh', "Distance from 52-week high")
    buckets(basket, a, 'rsi', "RSI(14)")

    # 1b. the real "too risky" question: tail risk and whether the rally is given back later
    print("  Is the most-surged quintile RISKIER? (same quintiles, last-month return)")
    print(f"    {'bucket':<24}{'P(loss)':>9}{'10th pct':>10}{'net 60d':>10}{'z60 vs basket':>14}")
    q = basket.groupby('date')['ret_1m'].rank(pct=True)
    for k in range(5):
        lo, hi = k / 5, (k + 1) / 5
        sel = basket[(q > lo) & (q <= hi)] if k else basket[q <= hi]
        z60 = zp(sel, basket[~basket.index.isin(sel.index)], 'fwd60')
        print(f"    {'Q' + str(k + 1):<24}{(sel['fwd'] < 0).mean():>8.0%}"
              f"{sel['fwd'].quantile(0.10):>+9.1f}%{sel['fwd60'].mean():>+9.2f}%"
              f"{(z60['z_paired'] if z60 else float('nan')):>14.2f}")
    print()

    # 2. does the tool's momentum-descending ordering help?
    print("  Basket ORDERING - top N by momentum each day (tool shows highest first):")
    print(f"    {'slice':<24}{'trades':>8}{'net/tr':>10}{'z vs univ':>10}{'z vs basket':>12}")
    r = basket.groupby('date')['mom'].rank(ascending=False, method='first')
    for n_top in (5, 10, 20):
        line(f"top {n_top} by momentum", basket[r <= n_top], a, basket)
    line("rest of basket", basket[r > 20], a, basket)
    print()

    # 3. rally age: consecutive prior sessions already in the basket
    a['in'] = a['mom_rank'] >= 0.75
    a = a.sort_values(['ticker', 'date'])
    grp = (~a['in']).cumsum()
    a['age'] = a.groupby(['ticker', grp]).cumcount()      # 0 = first day in the basket
    basket = a[a['in']]
    runs = a[a['in']].groupby(['ticker', grp]).size()
    print(f"  Rally persistence: a name stays in the basket for a median {runs.median():.0f} sessions "
          f"(75th pct {runs.quantile(0.75):.0f}, max {runs.max()}).")
    print("  Forward return by how long it has ALREADY been in the basket:")
    print(f"    {'age at entry':<24}{'trades':>8}{'net/tr':>10}{'z vs univ':>10}{'z vs basket':>12}")
    for lo, hi, tag in [(0, 5, "0-5 sessions (fresh)"), (5, 21, "1 month in"),
                        (21, 63, "1-3 months in"), (63, 10**9, "3+ months in")]:
        line(tag, basket[(basket['age'] >= lo) & (basket['age'] < hi)], a, basket)
    # 4. stability of the only two rules that looked shippable
    print("  STABILITY of the two candidate rules - z vs the REST of the basket, by period:")
    print(f"    {'rule':<24}{'period':<14}{'trades':>8}{'net/tr':>10}{'z vs rest':>11}")
    r = basket.groupby('date')['mom'].rank(ascending=False, method='first')
    rules = {'top 20 by momentum': r <= 20, 'age >= 5 sessions': basket['age'] >= 5}
    edges = pd.date_range(basket['date'].min(), basket['date'].max(), periods=4)
    for name, m in rules.items():
        for k in range(3):
            lo, hi = edges[k], edges[k + 1]
            w = (basket['date'] >= lo) & (basket['date'] < hi)
            sel, rest = basket[w & m], basket[w & ~m]
            z = zp(sel, rest)
            print(f"    {name if k == 0 else '':<24}{str(lo.date()):<14}{len(sel):>8}"
                  f"{sel['fwd'].mean():>+9.2f}%{(z['z_paired'] if z else float('nan')):>11.2f}")
    print()

    print("\n  Read: 'z vs basket' is the FILTER question - only a clearly negative z there justifies")
    print("  dropping a bucket from the scan. 'z vs univ' just says the bucket still beats the market.")


if __name__ == "__main__":
    try:
        run()
    except FileNotFoundError:
        print("cache/backtest_5y_long.pkl not found - run build_backtest_panel_long.py first.")
