"""Does the long-term momentum basket's edge hold over the FULL Yahoo history, not just 5 years?

    LONG_PANEL=cache/backtest_max_long.pkl python backtest_longterm_history.py

Same method as backtest_longterm_exits.py (monthly non-overlapping, 20 offsets, next-open entry,
20d hold, costs charged, >=40 liquid names per date). Top quartile vs the whole liquid universe,
paired per rebalance, pooled and by era. The pre-2021-08 eras are data the 5y panel never saw.

BIASES, both flatter the basket, neither can be removed with this data:
- survivorship: only TODAY's 748 listed names exist in the panel; the ones that collapsed are gone.
- cap bucket is TODAY's (CAP_BUCKET_MAP): a 2012 micro-cap that grew into a 2026 small-cap is in.
"""

import numpy as np
import pandas as pd

from backtest_longterm_exits import STEP, build
from backtest_longterm_recheck import enrich, zp

ERAS = ["2000-01-01", "2012-01-01", "2016-01-01", "2021-08-12", "2030-01-01"]


def run():
    a, arrs = build()
    a = enrich(a, arrs)
    dates = np.sort(a['date'].unique())
    print(f"{a['ticker'].nunique()} stocks, rebalances from {pd.Timestamp(dates[0]).date()} to "
          f"{pd.Timestamp(dates[-1]).date()}, names per date median {int(a.groupby('date').size().median())}")
    for lo, hi in [(ERAS[0], ERAS[-1])] + list(zip(ERAS, ERAS[1:])):
        zs, es, ns, bs = [], [], [], []
        for off in range(STEP):
            u = a[a['date'].isin(set(dates[off::STEP])) & (a['date'] >= lo) & (a['date'] < hi)]
            if u['date'].nunique() < 5:
                continue
            q = u[u['mom_rank'] >= 0.75]
            z, e = zp(q, u)
            zs.append(z); es.append(e); ns.append(u['date'].nunique())
            bs.append((q.groupby('date')['fwd'].mean() < 0).mean())
        if not zs:
            continue
        zs = np.array(zs)
        tag = "ALL" if (lo, hi) == (ERAS[0], ERAS[-1]) else f"{lo[:7]} -> {hi[:7]}"
        print(f"  {tag:<20} months ~{int(np.median(ns)):>4}  edge {np.median(es):+.2f}%/month  "
              f"z_paired median {np.median(zs):5.2f} (range {zs.min():.2f}..{zs.max():.2f}, "
              f"{(zs >= 2).sum()}/{len(zs)} >= 2)  basket-down months {np.median(bs):.0%}")


if __name__ == "__main__":
    run()
