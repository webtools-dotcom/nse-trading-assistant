"""Validate the edge-concentration finding: is the RSI<30 edge real only on days when many
names trigger at once, and is that anything more than the volatility regime we already trade?

edge_concentration_finding.md observed, in-sample, that 11% of days carry all the profit. Four
things have to hold before that is worth acting on:

  A. OUT OF SAMPLE. Chronological walk-forward with the threshold chosen on TRAIN data only.
     Reading the cut-point off the full sample is what makes a bucket sort curve-fit.

  B. NOT JUST MARKET BETA. If random entries also profit on high-candidate days, then panic
     days simply bounce and the strategy deserves no credit. Every bucket is compared against a
     random-entry control drawn from the same universe on the same days.

  C. ADDS SOMETHING BEYOND VOL REGIME. Position sizing already scales down in calm markets. If
     candidate count is just a noisy restatement of the volatility percentile it is redundant.
     Tested two-way: vol quartile x candidate tercile.

  D. GRADIENT, NOT A CLIFF. A real effect grades smoothly across buckets; a fitted one spikes.

Market volatility percentile is reproduced exactly as cache_manager.refresh_market_breadth
computes it live - cross-sectional mean atr_pct, ranked within its own trailing 252 days,
point-in-time.
"""

import numpy as np
import pandas as pd
from scipy import stats

from backtest_engine import simulate_trades
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR

PANEL_FILE = "cache/backtest_5y_short.pkl"
HORIZON = 6
VOL_WINDOW = 252


def build():
    """Candidate trades, random-control trades, and a per-day table of count + vol percentile."""
    panel = pd.read_pickle(PANEL_FILE)
    rng = np.random.default_rng(42)
    cand, ctrl, atr_rows = [], [], []

    for ticker, df in panel.items():
        if CAP_BUCKET_MAP.get(ticker) not in ('Mid', 'Small'):
            continue
        d = df.sort_values('date').reset_index(drop=True)
        if len(d) < 300:
            continue
        atr_rows.append(d[['date', 'atr_pct']])

        mask = ((d['rsi'] < 30) & (d['turnover_60d'] >= MIN_TURNOVER_INR)).fillna(False).values
        rand = rng.random(len(d)) < 0.10
        dates = d['date'].values
        for lst, m in ((cand, mask), (ctrl, rand)):
            for t in simulate_trades(d, m, horizon_days=HORIZON):
                lst.append({'date': dates[t['entry_idx']], 'net_pct': t['net_pct']})

    cand = pd.DataFrame(cand)
    ctrl = pd.DataFrame(ctrl)

    # Market vol percentile, exactly as the live tool computes it.
    atr = pd.concat(atr_rows).dropna()
    mkt = atr.groupby('date')['atr_pct'].mean().sort_index()
    vol_pct = mkt.rolling(VOL_WINDOW).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)

    days = pd.DataFrame({'n_cands': cand.groupby('date').size()})
    days['vol_pct'] = vol_pct.reindex(days.index)
    return cand.join(days, on='date'), ctrl.join(days, on='date'), days


def cell(trades, label):
    if len(trades) < 20:
        return f"{label:<26} {len(trades):>5} trades   -"
    return (f"{label:<26} {len(trades):>5} trades  {trades['net_pct'].mean():+7.3f}%  "
            f"win {(trades['net_pct'] > 0).mean() * 100:4.1f}%")


def day_ttest(a_days, b_days):
    """Compare two sets of DAY means - trades within a day are not independent."""
    if len(a_days) < 3 or len(b_days) < 3:
        return 0.0
    se = np.sqrt(a_days.var(ddof=1) / len(a_days) + b_days.var(ddof=1) / len(b_days))
    return float((a_days.mean() - b_days.mean()) / se) if se > 0 else 0.0


def test_a_walkforward(cand, days, n_folds=5):
    print("=" * 92)
    print("A. WALK-FORWARD - threshold picked on TRAIN only, applied to TEST")
    ordered = days.index.sort_values()
    fold = len(ordered) // (n_folds + 1)
    print(f"  {'fold':<6} {'train thr':>10} {'test high':>26} {'test low':>26} {'z':>6}")
    for k in range(1, n_folds + 1):
        tr_end = fold * k
        train_days, test_days = ordered[:tr_end], ordered[tr_end:tr_end + fold]
        if len(test_days) < 20:
            continue
        thr = days.loc[train_days, 'n_cands'].quantile(0.75)
        te = cand[cand['date'].isin(test_days)]
        hi, lo = te[te['n_cands'] >= thr], te[te['n_cands'] < thr]
        if len(hi) < 20 or len(lo) < 20:
            continue
        z = day_ttest(hi.groupby('date')['net_pct'].mean(), lo.groupby('date')['net_pct'].mean())
        print(f"  {k:<6} {thr:>10.0f} "
              f"{f'{len(hi):>5}tr {hi.net_pct.mean():+7.3f}%':>26} "
              f"{f'{len(lo):>5}tr {lo.net_pct.mean():+7.3f}%':>26} {z:>6.2f}")


def test_b_vs_control(cand, ctrl):
    print("\n" + "=" * 92)
    print("B. VS RANDOM CONTROL - do panic days simply bounce for everyone?")
    bins = [0, 2, 5, 10, 20, 1000]
    names = ['1-2', '3-5', '6-10', '11-20', '21+']
    cand = cand.assign(b=pd.cut(cand.n_cands, bins, labels=names))
    ctrl = ctrl.assign(b=pd.cut(ctrl.n_cands, bins, labels=names))
    print(f"  {'bucket':<8} {'strategy':>22} {'control':>22} {'edge':>9} {'z_day':>7}")
    for nm in names:
        s, c = cand[cand.b == nm], ctrl[ctrl.b == nm]
        if len(s) < 20 or len(c) < 20:
            continue
        z = day_ttest(s.groupby('date')['net_pct'].mean(), c.groupby('date')['net_pct'].mean())
        print(f"  {nm:<8} {f'{len(s):>5}tr {s.net_pct.mean():+7.3f}%':>22} "
              f"{f'{len(c):>5}tr {c.net_pct.mean():+7.3f}%':>22} "
              f"{s.net_pct.mean() - c.net_pct.mean():>+8.3f}% {z:>7.2f}")


def test_c_vs_vol(cand, days):
    print("\n" + "=" * 92)
    print("C. INDEPENDENT OF VOL REGIME? - vol quartile x candidate tercile (strategy net/trade)")
    d = cand.dropna(subset=['vol_pct']).copy()
    d['vq'] = pd.cut(d.vol_pct, [-.01, .25, .5, .75, 1.01], labels=['calm', 'q2', 'q3', 'panic'])
    d['ct'] = pd.qcut(d.n_cands, 3, labels=['few', 'mid', 'many'], duplicates='drop')
    piv = d.pivot_table(index='vq', columns='ct', values='net_pct', aggfunc='mean', observed=True)
    cnt = d.pivot_table(index='vq', columns='ct', values='net_pct', aggfunc='size', observed=True)
    print("\n  mean net/trade:"); print(piv.round(3).to_string())
    print("\n  trade counts:"); print(cnt.to_string())
    r = d[['vol_pct', 'n_cands']].corr().iloc[0, 1]
    print(f"\n  corr(vol percentile, candidate count) = {r:.3f}")
    within = d[d.vq == 'panic']
    if len(within) > 100:
        z = day_ttest(within[within.ct == 'many'].groupby('date')['net_pct'].mean(),
                      within[within.ct == 'few'].groupby('date')['net_pct'].mean())
        print(f"  within PANIC vol only, many vs few candidates: z_day = {z:.2f}")


def test_d_gradient(cand):
    print("\n" + "=" * 92)
    print("D. GRADIENT SHAPE - deciles of candidate count")
    d = cand.copy()
    d['dec'] = pd.qcut(d.n_cands, 10, labels=False, duplicates='drop')
    g = d.groupby('dec').agg(n_cands=('n_cands', 'median'), trades=('net_pct', 'size'),
                             net=('net_pct', 'mean'))
    print(g.round(3).to_string())
    rho, p = stats.spearmanr(g.index, g['net'])
    print(f"\n  Spearman rank correlation across deciles: rho={rho:.3f}, p={p:.4g}")
    print("  (a smooth monotonic gradient is the robust shape; a single spiking decile is not)")


def main():
    cand, ctrl, days = build()
    print(f"{len(cand):,} candidate trades, {len(ctrl):,} control trades, "
          f"{len(days)} days with candidates\n")
    test_a_walkforward(cand, days)
    test_b_vs_control(cand, ctrl)
    test_c_vs_vol(cand, days)
    test_d_gradient(cand)


if __name__ == "__main__":
    main()
