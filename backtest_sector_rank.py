"""Does SECTOR STRENGTH improve the long-term momentum ranking? (option B)

The live scan ranks the liquid Mid/Small universe by 12M-1M momentum and shows the top quartile,
highest first. It never looks at whether the stock's sector is hot. The proposal: let sector
strength reorder the picks - "buy the momentum names whose sector is also running".

Two questions:

  1. Does sector strength separate winners INSIDE the basket? (quintiles, z vs the rest of the
     basket - the only control that can justify a reorder.)
  2. Does a combined rank BEAT the momentum-only rank head to head? Day-clustered paired test
     where the control IS the current strategy's picks. This is the decision.

Two industry taxonomies compete ON THE SAME STOCK-DAYS (rows where both have a >=MIN_PEERS peer
group), so a difference between them is the taxonomy and not the sample:
  - 'nse'  : macro-economic sector from nse_watchlist_expanded.csv - 20 buckets, "Capital Goods"
             holds 113 stocks from cement machinery to shipyards.
  - 'gics' : yfinance industry from build_industry_map.py - ~105 labels, so STLTECH and HFCL sit
             together in Communication Equipment and PARAS is Aerospace & Defense.

Sector momentum = mean trailing 60-day return of the stock's peers in the liquid universe,
point-in-time. Industries with fewer than MIN_PEERS names that day are dropped, not averaged.

CAVEAT to state with any result: industry LABELS are today's, applied backwards. Companies change
industry rarely, so this is mild, but it is not strictly point-in-time.

    python backtest_sector_rank.py
"""

import os
import pickle

import pandas as pd

from backtest_engine import day_clustered_edge, sharpe, deflated_sharpe
from backtest_longterm_xsec import build_rows, H
from config import BASE_DIR

MIN_PEERS = 5
TOP_N = 20          # the scan's display depth - a reorder only matters within what he sees
MAP_FILE = os.path.join(BASE_DIR, "cache", "industry_map.pkl")


def industry_maps():
    w = pd.read_csv(os.path.join(BASE_DIR, 'nse_watchlist_expanded.csv'))
    maps = {'nse': dict(zip(w['ticker'], w['Industry']))}
    if os.path.exists(MAP_FILE):
        with open(MAP_FILE, 'rb') as f:
            maps['gics'] = {t: v['industry'] for t, v in pickle.load(f).items()}
    else:
        print("cache/industry_map.pkl missing - run build_industry_map.py for the granular test.\n")
    return maps


def zp(sel, ctrl, col='fwd'):
    sel, ctrl = sel.dropna(subset=[col]), ctrl.dropna(subset=[col])
    if len(sel) < 30 or len(ctrl) < 30:
        return None
    return day_clustered_edge(
        [{'entry_date': d, 'net_pct': r} for d, r in zip(sel['date'], sel[col])],
        [{'entry_date': d, 'net_pct': r} for d, r in zip(ctrl['date'], ctrl[col])])


def add_sector(a, name, ind_map):
    """Point-in-time sector strength: mean trailing 60d return of same-industry peers that day."""
    ind = a['ticker'].map(ind_map).fillna('Unknown')
    g = a.assign(ind=ind).groupby(['date', 'ind'])['ret_3m']
    a[f'sec_{name}'] = g.transform('mean').where(g.transform('size') >= MIN_PEERS)
    a[f'rs_{name}'] = a['ret_3m'] - a[f'sec_{name}']
    return ind.nunique()


def quintiles(basket, col, label):
    print(f"    {label} - quintiles inside the basket:")
    print(f"      {'bucket':<10}{'trades':>8}{'net/tr':>10}{'z vs rest':>11}")
    q = basket.groupby('date')[col].rank(pct=True)
    for k in range(5):
        lo, hi = k / 5, (k + 1) / 5
        m = (q > lo) & (q <= hi) if k else (q <= hi)
        sel, rest = basket[m], basket[~m]          # boolean mask: the panel index is NOT unique
        z = zp(sel, rest)
        print(f"      {'Q' + str(k + 1):<10}{len(sel):>8}{sel['fwd'].mean():>+9.2f}%"
              + (f"{z['z_paired']:>11.2f}" if z else "        n/a"))


def head_to_head(basket, name):
    """THE decision: top-20 by combined rank vs top-20 by momentum alone, same days."""
    mom_rank = basket.groupby('date')['mom'].rank(ascending=False, method='first')
    base = basket[mom_rank <= TOP_N]
    print(f"    HEAD TO HEAD - top {TOP_N}/day, combined rank vs momentum-only "
          f"(z_paired > 2 = the reorder genuinely wins):")
    print(f"      {'weighting':<24}{'trades':>8}{'combo':>9}{'mom-only':>10}{'z_paired':>10}")
    out = {}
    pm = basket.groupby('date')['mom'].rank(pct=True)
    ps = basket.groupby('date')[f'sec_{name}'].rank(pct=True)
    for w in (0.25, 0.50, 0.75):
        combo = (1 - w) * pm + w * ps
        sel = basket[combo.groupby(basket['date']).rank(ascending=False, method='first') <= TOP_N]
        z = zp(sel, base)
        out[f"w={w:.2f}"] = sel
        print(f"      {f'{1-w:.0%} mom + {w:.0%} sector':<24}{len(sel):>8}{sel['fwd'].mean():>+8.2f}%"
              f"{base['fwd'].mean():>+9.2f}%" + (f"{z['z_paired']:>10.2f}" if z else "       n/a"))
    return base, out


def sector_tilt(basket, name, n_top=10):
    """Found AFTER looking at the quintiles: only the TOP sector quintile beat the basket, and a
    weighted blend dilutes that. So test the cut directly - keep only names whose sector is in the
    hottest quintile that day, then take the top n_top by momentum; control is the top n_top by
    momentum with no sector condition. Post-hoc, so the bar is higher: z>2 AND 4/5 fifths.
    """
    q = basket.groupby('date')[f'sec_{name}'].rank(pct=True)
    pool = basket[q >= 0.80]
    sel = pool[pool.groupby('date')['mom'].rank(ascending=False, method='first') <= n_top]
    base = basket[basket.groupby('date')['mom'].rank(ascending=False, method='first') <= n_top]
    z = zp(sel, base)
    print(f"    SECTOR-TILT CUT (hottest sector quintile, then top {n_top} by momentum) - post-hoc:")
    print(f"      {'slice':<24}{'trades':>8}{'net/tr':>10}{'z_paired':>10}")
    print(f"      {'tilted':<24}{len(sel):>8}{sel['fwd'].mean():>+9.2f}%"
          + (f"{z['z_paired']:>10.2f}" if z else "       n/a"))
    print(f"      {'momentum-only control':<24}{len(base):>8}{base['fwd'].mean():>+9.2f}%")
    edges = pd.date_range(basket['date'].min(), basket['date'].max(), periods=6)
    holds = 0
    for k in range(5):
        st, e = edges[k], edges[k + 1]
        c_ = sel[(sel['date'] >= st) & (sel['date'] < e)]
        b_ = base[(base['date'] >= st) & (base['date'] < e)]
        zz = zp(c_, b_)
        if zz and zz['z_paired'] > 2:
            holds += 1
        print(f"      {str(st.date()):<24}{len(c_):>8}{c_['fwd'].mean():>+9.2f}%"
              + (f"{zz['z_paired']:>10.2f}" if zz else "       n/a")
              + f"   (mom-only {b_['fwd'].mean():+.2f}%)")
    print(f"      holds (z>2) in {holds}/5 fifths - needs 4/5 to survive a post-hoc finding")
    print()


def stability(basket, base, variants, name):
    best = max(variants, key=lambda k: variants[k]['fwd'].mean())
    print(f"\n    STABILITY by chronological fifth ('{name}', best weighting {best}):")
    print(f"      {'period':<16}{'trades':>8}{'combo':>9}{'mom-only':>10}{'z_paired':>10}")
    sel = variants[best]
    edges = pd.date_range(basket['date'].min(), basket['date'].max(), periods=6)
    holds = 0
    for k in range(5):
        s, e = edges[k], edges[k + 1]
        c_ = sel[(sel['date'] >= s) & (sel['date'] < e)]
        b_ = base[(base['date'] >= s) & (base['date'] < e)]
        z = zp(c_, b_)
        if z and z['z_paired'] > 2:
            holds += 1
        print(f"      {str(s.date()):<16}{len(c_):>8}{c_['fwd'].mean():>+8.2f}%{b_['fwd'].mean():>+9.2f}%"
              + (f"{z['z_paired']:>10.2f}" if z else "       n/a"))
    srs = {k: sharpe(v.groupby('date')['fwd'].mean().values, holding_days=H)
           for k, v in variants.items()}
    srs['mom-only'] = sharpe(base.groupby('date')['fwd'].mean().values, holding_days=H)
    top = max(srs, key=srs.get)
    d = deflated_sharpe(srs[top], list(srs.values()), n_obs=int(basket['date'].nunique()))
    print(f"      holds (z>2) in {holds}/5 fifths | deflated Sharpe: best='{top}' SR={srs[top]:.2f}, "
          f"P(real)={d['dsr']:.2f}\n")


def run():
    a = build_rows()
    a['date'] = pd.to_datetime(a['date'])
    a = a.dropna(subset=['ret_3m']).reset_index(drop=True)   # index MUST be unique - it is not
    maps = industry_maps()                                    # in the raw panel (per-ticker concat)
    counts = {n: add_sector(a, n, m) for n, m in maps.items()}

    cols = [f'sec_{n}' for n in maps]
    common = a.dropna(subset=cols).reset_index(drop=True)
    print(f"{a['ticker'].nunique()} liquid Mid/Small stocks, {len(a)} stock-days, {H}d hold, "
          f"costs charged, entry next open.")
    for n in maps:
        print(f"  '{n}': {counts[n]} industries, "
              f"{a[f'sec_{n}'].notna().mean():.0%} of stock-days have a >={MIN_PEERS}-peer group")
    print(f"  MATCHED SAMPLE (both taxonomies usable): {len(common)} stock-days "
          f"({len(common)/len(a):.0%}) - all results below use it, so taxonomy differences are")
    print("  the taxonomy and not the sample.")
    print("  Industry LABELS are today's applied backwards - mild look-ahead, state it.\n")

    common['mom_rank'] = common.groupby('date')['mom'].rank(pct=True)
    basket = common[common['mom_rank'] >= 0.75].reset_index(drop=True)
    print(f"  basket = top-quartile momentum on the matched sample: {len(basket)} stock-days, "
          f"net {basket['fwd'].mean():+.2f}%/trade\n")

    for n in maps:
        print(f"  ===== taxonomy '{n}' =====")
        quintiles(basket, f'sec_{n}', "SECTOR strength (peer 60d mean)")
        print()
        quintiles(basket, f'rs_{n}', "STOCK vs its own sector")
        print()
        base, variants = head_to_head(basket, n)
        stability(basket, base, variants, n)
        sector_tilt(basket, n)

    print("  Decision rule: the reorder ships only if z_paired > 2 head-to-head AND it holds in")
    print("  most fifths. A positive net/trade with z < 2 is not evidence - it is the same trap")
    print("  that killed nominal price and the P(win) floor.")


if __name__ == "__main__":
    try:
        run()
    except FileNotFoundError:
        print("cache/backtest_5y_long.pkl not found - run build_backtest_panel_long.py first.")
