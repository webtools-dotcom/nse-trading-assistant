"""Re-check the long-term scan's other claims with NON-overlapping monthly rebalances, then test
'frog in the pan' (Da, Gurun & Warachka 2014) - pre-registered before running.

Same method as backtest_longterm_exits.py: one entry date every 20 sessions, all 20 start offsets,
entry next open, 20d hold, no stop/target, costs charged. Each comparison is PAIRED on the same
rebalance date (A's mean minus B's mean), so the market move cancels.

Re-checks (claims printed by tools.scan_watchlist_text_long_momentum, all measured every-day):
  R1  low-vol tilt: quartile names with atr% below the quartile's median  vs  the high-atr% half
  R2  top 20 by momentum  vs  the rest of the quartile   (old claim z_paired +5.33)
  R3  tail-risk bands: P(down >20% in 20d) by absolute 12M momentum band (per-trade rate; overlap
      does not bias a rate, only its confidence - so this one is re-counted, not re-tested)

Test #2 - information discreteness, ID = sign(PRET) * (%neg days - %pos days) over the same
t-252..t-21 window as the momentum rank. Low ID = the gain came in many small steps (smooth).
  F1  quartile, smooth half (ID below the quartile median)  vs  jumpy half
  pass: z_paired >= 2 (median over offsets) and right sign in >= 3 of 5 periods. Also reported:
  P(<-20%) smooth vs jumpy - the part that matters for a 1-2 name holder.

    python backtest_longterm_recheck.py
"""

import numpy as np
import pandas as pd

from backtest_engine import day_clustered_edge
from backtest_longterm_exits import PANEL, H, STEP, build
from config import round_trip_cost_pct


def enrich(a, arrs):
    d = pd.read_pickle(PANEL)
    fwd, atr, idd = [], [], []
    cache = {}
    for t, i, turn in zip(a['ticker'], a['i'], a['turn']):
        if t not in cache:
            df = d[t].sort_values('date')
            c = df['close'].values
            r = np.diff(c, prepend=c[0])
            cache[t] = (np.cumsum(r > 0), np.cumsum(r < 0), df['atr_pct'].values)
        pos, neg, ap = cache[t]
        o, _, _, c = arrs[t]
        fwd.append((c[i + 1 + H] - o[i + 1]) / o[i + 1] * 100 - round_trip_cost_pct(turn))
        atr.append(ap[i])
        lo, hi = i - 252, i - 21                    # days (lo, hi] - the window the rank uses
        n = hi - lo
        pret = c[hi] / c[lo] - 1
        idd.append(np.sign(pret) * ((neg[hi] - neg[lo]) - (pos[hi] - pos[lo])) / n)
    a['fwd'], a['atr'], a['id'] = fwd, atr, idd
    return a


def zp(A, B):
    r = day_clustered_edge([{'entry_date': x, 'net_pct': v} for x, v in zip(A['date'], A['fwd'])],
                           [{'entry_date': x, 'net_pct': v} for x, v in zip(B['date'], B['fwd'])])
    return (r['z_paired'], r['day_edge']) if r else (np.nan, np.nan)


def compare(label, a, dates, split):
    """split(quartile_rows_on_one_date_set) -> (A, B). Paired A-B over 20 offsets + periods."""
    zs, es = [], []
    for off in range(STEP):
        q = a[a['date'].isin(set(dates[off::STEP]))]
        A, B = split(q)
        z, e = zp(A, B)
        zs.append(z); es.append(e)
        if off == 0:
            A0, B0 = A, B
    zs = np.array(zs)
    cuts = np.array_split(np.sort(A0['date'].unique()), 5)
    per = [A0[A0['date'].isin(ch)].groupby('date')['fwd'].mean().sub(
           B0[B0['date'].isin(ch)].groupby('date')['fwd'].mean()).mean() for ch in cuts]
    signs = sum(p > 0 for p in per)
    print(f"\n{label}")
    print(f"  A {A0['fwd'].mean():+.2f}%/trade (n={len(A0)})  vs  B {B0['fwd'].mean():+.2f}% (n={len(B0)})  [offset 0]")
    print(f"  edge A-B median {np.nanmedian(es):+.2f}%/month | z_paired median {np.nanmedian(zs):.2f}, "
          f"range {np.nanmin(zs):.2f}..{np.nanmax(zs):.2f}, {(zs >= 2).sum()}/20 offsets >= 2")
    print(f"  by period: " + '  '.join(f"{p:+.2f}%" for p in per) + f"   ({signs}/5 positive)")
    for tag, x in (('A', A0), ('B', B0)):
        f = x['fwd'].values
        print(f"  {tag}: P(<-20%) {(f < -20).mean():.1%}  P(<-10%) {(f < -10).mean():.1%}  10th pct {np.percentile(f, 10):+.1f}%")


def run():
    a, arrs = build()
    a = enrich(a, arrs)
    dates = np.sort(a['date'].unique())
    q = a[a['mom_rank'] >= 0.75].copy()

    def med_split(col):
        def f(x):
            m = x.groupby('date')[col].transform('median')
            return x[x[col] < m], x[x[col] >= m]
        return f

    print(f"Top quartile, monthly non-overlapping, 20 offsets. A-B paired per rebalance date.")
    compare("R1 low-vol tilt: A = atr% below quartile median, B = above", q, dates, med_split('atr'))
    compare("R2 top 20: A = top 20 by momentum, B = rest of quartile", q, dates,
            lambda x: (x[x['mom_pos'] <= 20], x[x['mom_pos'] > 20]))
    compare("F1 frog-in-the-pan: A = smooth (low ID), B = jumpy (high ID)", q, dates, med_split('id'))

    print("\nR3 tail-risk bands, all liquid names, offset-0 rebalances (per-trade rate, n in brackets):")
    m0 = a[a['date'].isin(set(dates[0::STEP]))]
    for lo, hi in [(.3, .6), (.6, 1), (1, 2), (2, 4), (4, 99)]:
        f = m0[(m0['mom'] >= lo) & (m0['mom'] < hi)]['fwd'].values
        allf = a[(a['mom'] >= lo) & (a['mom'] < hi)]['fwd'].values
        print(f"  {lo*100:.0f}-{hi*100:.0f}%: P(<-20%) {(f < -20).mean():.1%} [{len(f)}]   "
              f"every-day {(allf < -20).mean():.1%} [{len(allf)}]   mean {f.mean():+.2f}%")


if __name__ == "__main__":
    run()
