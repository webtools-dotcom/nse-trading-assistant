"""Decay vs regime for the last 12 months: is the signal broken, or is this just a low-vol
market the strategy is KNOWN to lose in?

decay_monitor.diagnose() already separates the edge (strategy - same-window control) from the
market baseline, and it deliberately refuses to label "regime vs decay" - one period cannot
separate them from the equity curve alone. This script adds the one lever diagnose() does not
use: the strategy's MEASURED volatility-regime dependence (calm -0.81%/trade, panic +1.64%,
config.py). That gives a real test the equity curve cannot:

  Part 1  Official diagnose() + live CUSUM - the existing, agnostic verdict.
  Part 2  Was the recent window unusually CALM? If so, a loss is the strategy behaving exactly
          as its own vol table predicts - that is regime, and it is predicted, not decay.
  Part 3  THE DECISIVE TEST. Condition on vol regime. On high-vol (panic) days - where the
          strategy is SUPPOSED to win - did the edge over control survive recently?
            edge intact on panic days  -> negative headline is regime MIX (a calm market) -> REGIME
            edge gone even on panic days -> the signal itself broke -> DECAY

Nothing here is a trade. It answers one question: should this strategy be trading at all now.

    python decay_regime.py
"""

import sys

import numpy as np
import pandas as pd

from backtest_engine import simulate_trades, day_clustered_edge
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR
from decay_monitor import diagnose, format_diagnosis, cusum

PANEL_FILE = "cache/backtest_5y_short.pkl"
HORIZON = 6
VOL_WINDOW = 252
RECENT_START = pd.Timestamp('2025-07-29')          # last ~12 months of the panel
QCUTS = [0.0, 0.25, 0.50, 0.75, 1.01]
QNAMES = ['calm <25', '25-50', '50-75', 'panic 75+']


def build():
    """Strategy + random-control trades over the live universe (Mid/Small, RSI<30, >=Rs25cr),
    each tagged with the point-in-time market vol percentile and whether it falls in the recent
    window. Vol percentile is computed exactly as the live tool does (backtest_concentration)."""
    panel = pd.read_pickle(PANEL_FILE)
    rng = np.random.default_rng(42)
    strat, ctrl, atr_rows = [], [], []

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
        for lst, m in ((strat, mask), (ctrl, rand)):
            for t in simulate_trades(d, m, horizon_days=HORIZON):
                lst.append({'date': dates[t['entry_idx']], 'net_pct': t['net_pct']})

    strat, ctrl = pd.DataFrame(strat), pd.DataFrame(ctrl)

    # Cross-sectional mean atr_pct, ranked within its own trailing 252 days = the live percentile.
    atr = pd.concat(atr_rows).dropna()
    mkt = atr.groupby('date')['atr_pct'].mean().sort_index()
    vol_pct = mkt.rolling(VOL_WINDOW).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)
    vol_pct.index = pd.to_datetime(vol_pct.index)

    for t in (strat, ctrl):
        t['date'] = pd.to_datetime(t['date'])
        t['vol_pct'] = t['date'].map(vol_pct)
        t['vq'] = pd.cut(t['vol_pct'], QCUTS, labels=QNAMES, right=False)
        t['recent'] = t['date'] >= RECENT_START
    return strat.sort_values('date').reset_index(drop=True), ctrl.sort_values('date').reset_index(drop=True)


def part1_official(strat, ctrl):
    print("=" * 92)
    print("PART 1 - Official decay diagnosis (decay_monitor, agnostic on cause)")
    d = diagnose(strat['net_pct'].values, ctrl['net_pct'].values,
                 labels=['B1 oldest', 'B2', 'B3', 'B4', 'B5 recent'])
    print(format_diagnosis(d))
    n = len(strat)
    hist_mean = float(strat['net_pct'].iloc[:int(0.8 * n)].mean())
    cu = cusum(strat['net_pct'].values, expected_mean=hist_mean)
    print(f"\n  live CUSUM: {cu['pct_of_threshold']:.0f}% of alarm threshold "
          f"(expected_mean {hist_mean:+.3f}%, alarm={cu['alarm']}, ever_fired={cu['ever_fired']})")


def part2_regime_mix(strat):
    print("\n" + "=" * 92)
    print("PART 2 - Was the recent window unusually CALM? (the strategy is KNOWN to lose in calm)")
    prior, recent = strat[~strat['recent']], strat[strat['recent']]
    print(f"  mean market vol percentile : prior {prior['vol_pct'].mean():.3f}   "
          f"recent {recent['vol_pct'].mean():.3f}")
    counts = strat.groupby(['recent', 'vq'], observed=False).size().unstack(fill_value=0)
    mix = counts.div(counts.sum(axis=1), axis=0) * 100
    print("  share of trades by vol quartile (%):")
    print(f"    {'window':<8}" + "".join(f"{q:>12}" for q in QNAMES))
    for flag, lbl in [(False, 'prior'), (True, 'recent')]:
        print(f"    {lbl:<8}" + "".join(f"{mix.loc[flag, q]:>11.1f}%" for q in QNAMES))
    print("  Read: recent mass shifted toward the calm quartiles -> the strategy is SUPPOSED to")
    print("  lose there. A negative headline then is regime (a calm market), not a broken signal.")


def part3_decisive(strat, ctrl):
    print("\n" + "=" * 92)
    print("PART 3 - DECISIVE: within each vol regime, did the edge over control survive recently?")
    print(f"  {'vol quartile':<12} | {'PRIOR strat/ctrl/edge (n)':>34} | {'RECENT strat/ctrl/edge (n)':>34}")

    def cellval(df, flag, q):
        sub = df[(df['recent'] == flag) & (df['vq'] == q)]
        return sub['net_pct'].mean() if len(sub) else np.nan, len(sub)

    for q in QNAMES:
        cells = []
        for flag in (False, True):
            sm, _ = cellval(strat, flag, q)
            cm, cn = cellval(ctrl, flag, q)
            edge = sm - cm if (sm == sm and cm == cm) else np.nan
            sn = len(strat[(strat['recent'] == flag) & (strat['vq'] == q)])
            cells.append(f"{sm:+6.2f}/{cm:+6.2f}/{edge:+6.2f} ({sn:>4})")
        print(f"  {q:<12} | {cells[0]:>34} | {cells[1]:>34}")

    print()
    print("  NOTE: these are raw POOLED means - vulnerable to day-clustering (a few bad panic days,")
    print("  each with many trades, can drag the pooled mean negative even when most days won).")
    print("  The AUTHORITATIVE panic-day read is PART 4, which pairs by day and nets out the market.")


def _to_trades(df):
    """DataFrame rows -> the {'entry_date','net_pct'} dicts day_clustered_edge expects."""
    return [{'entry_date': d, 'net_pct': n} for d, n in zip(df['date'], df['net_pct'])]


def panic_edge_tripwire(strat, ctrl, vol_floor=0.75, min_days=8):
    """The decay signal, isolated. Filters to high-vol (panic) days - where the strategy is
    SUPPOSED to be strongest - and runs the day-clustered PAIRED test (not raw means) of the
    edge over the same-day random control. Regime (a calm market) is removed by construction,
    so a vanished edge HERE is the signal breaking, not the market being quiet.

    Uses strat['recent'] (set by build) to split prior vs recent panic. Returns per-window
    day_clustered_edge results plus a tripwire STATE from the RECENT panic window."""
    ps, pc = strat[strat['vol_pct'] >= vol_floor], ctrl[ctrl['vol_pct'] >= vol_floor]
    out = {'vol_floor': vol_floor}
    for label, sm, cm in [
            ('all panic', ps, pc),
            ('prior panic', ps[~ps['recent']], pc[~pc['recent']]),
            ('recent panic', ps[ps['recent']], pc[pc['recent']])]:
        out[label] = day_clustered_edge(_to_trades(sm), _to_trades(cm))

    rec = out['recent panic']
    if rec is None or rec['n_paired_days'] < min_days:
        out['state'], out['note'] = 'NOT ARMED', f"< {min_days} recent panic days - cannot judge yet"
    elif rec['day_edge'] > 0 and rec['z_paired'] >= 2.0:
        out['state'], out['note'] = 'HEALTHY', 'edge intact and significant on panic days'
    elif rec['day_edge'] > 0:
        out['state'], out['note'] = 'WATCH', 'edge still positive on panic days but not significant (low power)'
    else:
        out['state'], out['note'] = 'TRIPPED', 'edge gone/negative where the signal should be strongest - decay'
    return out


def part4_tripwire(strat, ctrl):
    print("\n" + "=" * 92)
    print("PART 4 - PANIC-DAY EDGE TRIPWIRE (day-clustered paired test, regime filtered out)")
    print(f"  {'floor  window':<22} {'days':>5} {'day_edge':>10} {'z_paired':>9}")
    for floor in (0.75, 0.90):   # 0.90 addresses the relative-percentile caveat: genuine panic only
        tw = panic_edge_tripwire(strat, ctrl, vol_floor=floor)
        for w in ('prior panic', 'recent panic'):
            r = tw[w]
            tag = f"{floor:.2f}  {w.split()[0]}"
            if r is None:
                print(f"  {tag:<22} {'-':>5} {'-':>10} {'-':>9}")
            else:
                print(f"  {tag:<22} {r['n_paired_days']:>5} {r['day_edge']:>+9.3f}% {r['z_paired']:>9.2f}")
        print(f"    -> floor {floor:.2f}: {tw['state']} - {tw['note']}")
    print("  TRIPPED = decay (fails on panic days) | WATCH/NOT ARMED = wait for more genuine panic days.")


def run():
    strat, ctrl = build()
    print(f"Panel: strategy {len(strat)} trades, control {len(ctrl)}, "
          f"recent window >= {RECENT_START.date()}, costs charged\n")
    part1_official(strat, ctrl)
    part2_regime_mix(strat)
    part3_decisive(strat, ctrl)
    part4_tripwire(strat, ctrl)
    print("\n" + "=" * 92)
    print("decay = signal broke (fails even in panic) | regime = calm market (edge holds in panic,")
    print("just fewer panic days). One year is short - treat this as a lean, not a proof.")


def demo():
    """No-network check of the tripwire's state logic: an intact panic-day edge must read
    HEALTHY, an inverted one must read TRIPPED."""
    rng = np.random.default_rng(0)

    def make(recent_edge):
        s, c = [], []
        for base, recent, s_edge in [(pd.Timestamp('2022-01-01'), False, 1.5),
                                     (pd.Timestamp('2025-09-01'), True, recent_edge)]:
            for k in range(20):                      # 20 distinct panic days per window
                day = base + pd.Timedelta(days=k)
                for _ in range(5):
                    s.append({'date': day, 'net_pct': s_edge + rng.normal(0, 0.3),
                              'vol_pct': 0.9, 'recent': recent})
                    c.append({'date': day, 'net_pct': rng.normal(0, 0.3),
                              'vol_pct': 0.9, 'recent': recent})
        return pd.DataFrame(s), pd.DataFrame(c)

    s, c = make(recent_edge=1.5)
    assert panic_edge_tripwire(s, c)['state'] == 'HEALTHY'
    s, c = make(recent_edge=-1.0)
    assert panic_edge_tripwire(s, c)['state'] == 'TRIPPED'
    s, c = make(recent_edge=1.5)
    assert panic_edge_tripwire(s, c, min_days=999)['state'] == 'NOT ARMED'
    print("decay_regime.py tripwire self-check passed")


if __name__ == "__main__":
    if 'selfcheck' in sys.argv:
        demo()
    else:
        try:
            run()
        except FileNotFoundError:
            print("cache/backtest_5y_short.pkl not found - build the 5y panel first.")
