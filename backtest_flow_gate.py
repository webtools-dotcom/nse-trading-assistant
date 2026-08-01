"""Does conditioning the validated RSI<30 mid/small entry on NSE participant-category cash
flows improve it?

Tests the market-level flow variables as a REGIME GATE, the same shape as the validated
volatility-regime rule - not as a standalone signal. The stock-level flow rules in
behavioral_rule_spec.md are not implementable: NSE publishes one net figure per category per
day for the whole market, with no per-stock breakdown.

Two things this is careful about:

1. FLOWS ARE LAGGED ONE DAY. NSE publishes the file after the close, so an entry at the close
   of day t can only know day t-1's flows. Not shifting would leak.

2. THE BASELINE IS RESTRICTED TO THE SAME WINDOW. Flow history starts 2023-04, so a gated
   result compared against the published 5-year baseline would be comparing periods, not
   rules. Every number here is computed inside 2023-04 -> 2026-07.
"""

import numpy as np
import pandas as pd

from backtest_engine import simulate_trades, edge_vs_control, sharpe, average_uniqueness
from cache_manager import load_category_flows
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR

PANEL_FILE = "cache/backtest_5y_short.pkl"
HORIZON = 6
DII_CATEGORIES = ['MUTUAL_FUNDS', 'INSURANCE', 'BANK', 'AIF', 'PMS']
PCTL_WINDOW = 252


def build_flow_features():
    """Market-level daily flow features, lagged one day, percentile-ranked point-in-time.

    The percentile is computed over a trailing window only - ranking against the full sample
    would let 2026 information set the threshold for a 2023 trade.
    """
    raw = load_category_flows()
    wide = raw.pivot_table(index='date', columns='category', values='net_cr', aggfunc='sum')
    wide = wide.sort_index()

    f = pd.DataFrame(index=wide.index)
    f['fpi_net'] = wide.get('FPI')
    f['retail_net'] = wide.get('RETAIL')
    f['dii_net'] = wide[[c for c in DII_CATEGORIES if c in wide.columns]].sum(axis=1)
    # Retail buying into foreign selling. Positive = the divergence the literature describes.
    f['divergence'] = f['retail_net'] - f['fpi_net']

    for col in ['fpi_net', 'retail_net', 'dii_net', 'divergence']:
        f[col + '_5d'] = f[col].rolling(5).mean()
        f[col + '_pctl'] = (f[col].rolling(PCTL_WINDOW)
                            .rank(pct=True))
        f[col + '_5d_pctl'] = (f[col + '_5d'].rolling(PCTL_WINDOW)
                               .rank(pct=True))

    # Known only after the close of the day it describes.
    return f.shift(1)


def load_universe(flow_start):
    """Mid/small-cap, liquid, restricted to the flow-data window - the live strategy's universe."""
    panel = pd.read_pickle(PANEL_FILE)
    out = []
    for ticker, df in panel.items():
        if CAP_BUCKET_MAP.get(ticker) not in ('Mid', 'Small'):
            continue
        df = df.sort_values('date').reset_index(drop=True)
        df = df[df['date'] >= flow_start].reset_index(drop=True)
        if len(df) < HORIZON + 30:
            continue
        out.append((ticker, df))
    return out


def day_clustered_test(trades, control_trades):
    """Cluster inference by entry DATE, not by trade.

    A market-level gate selects days, so every trade it admits comes from a small set of
    dates whose forward returns share the common market factor. Counting them as independent
    observations is the cross-sectional twin of the overlapping-trade error: 2,577 trades on
    180 days carry roughly 180 observations' worth of information, not 2,577. Averaging within
    each day and testing the day means is the honest correction.
    """
    if not trades:
        return None
    s = pd.Series([t['net_pct'] for t in trades],
                  index=[t['entry_date'] for t in trades]).groupby(level=0).mean()
    c = pd.Series([t['net_pct'] for t in control_trades],
                  index=[t['entry_date'] for t in control_trades]).groupby(level=0).mean()
    if len(s) < 3:
        return None
    se = np.sqrt(s.var(ddof=1) / len(s) + c.var(ddof=1) / len(c))
    edge = s.mean() - c.mean()

    # Paired: each gate day against the SAME day's random control. This nets out the common
    # market factor instead of merely acknowledging it, so it is both fairer and more
    # powerful than the unpaired day test - a gate that picks genuinely better stocks on the
    # days it fires still shows up here.
    paired = (s - c).dropna()
    z_pair = (float(paired.mean() / (paired.std(ddof=1) / np.sqrt(len(paired))))
              if len(paired) > 2 and paired.std(ddof=1) > 0 else 0.0)

    return {'n_days': len(s), 'edge': float(edge),
            'z': float(edge / se) if se > 0 else 0.0,
            'z_pair': z_pair, 'n_paired': len(paired)}


def trades_for(stocks, flows, gate=None, random_control=False, seed=42):
    rng = np.random.default_rng(seed)
    trades, total_bars = [], 0
    for _, df in stocks:
        merged = df.merge(flows, left_on='date', right_index=True, how='left')
        if random_control:
            mask = pd.Series(rng.random(len(merged)) < 0.10, index=merged.index)
        else:
            mask = (merged['rsi'] < 30) & (merged['turnover_60d'] >= MIN_TURNOVER_INR)
            if gate is not None:
                mask &= gate(merged)
        mask = mask.fillna(False).values
        dates = merged['date'].values
        for t in simulate_trades(merged, mask, horizon_days=HORIZON):
            t['entry_date'] = dates[t['entry_idx']]
            trades.append(t)
        total_bars += len(merged)
    return trades, total_bars


def summarize(name, trades, control_trades):
    if len(trades) < 30:
        return f"{name:<44} {len(trades):>6} trades   (too few to judge)"
    net = [t['net_pct'] for t in trades]
    res = edge_vs_control(net, [t['net_pct'] for t in control_trades])
    clu = day_clustered_test(trades, control_trades)
    return (f"{name:<44} {res['n_strategy']:>6}  {clu['n_days']:>5}  "
            f"{res['strategy_avg']:+7.3f}%  {res['edge']:+7.3f}%  "
            f"z={res['z']:>6.2f}  {clu['z']:>7.2f}  {clu['z_pair']:>8.2f}  win={res['win_rate']:>4.1f}%")


def run():
    flows = build_flow_features()
    flow_start = flows.dropna(subset=['fpi_net']).index.min()
    print(f"Flow window: {flow_start.date()} -> {flows.index.max().date()}  ({len(flows)} days)")

    stocks = load_universe(flow_start)
    print(f"Universe: {len(stocks)} mid/small-cap stocks, turnover >= Rs {MIN_TURNOVER_INR/1e7:.0f} cr\n")

    control, _ = trades_for(stocks, flows, random_control=True)
    control_net = [t['net_pct'] for t in control]
    print(f"Random control (same window): {len(control)} trades, "
          f"{np.mean(control_net):+.3f}% net/trade\n")
    print("z        = naive, treats every trade as independent (OVERSTATED - do not read this one)")
    print("z_day    = clustered by entry date, unpaired")
    print("z_paired = each gate day vs the SAME day's random control - the fairest test.")
    print("           A gate is only worth having if z_paired beats the BASELINE row.\n")

    # A gate can only ever help by dropping trades, so the honest comparison is baseline-first.
    gates = [
        ("BASELINE  RSI<30, no flow gate", None),
        ("FPI selling hard   (fpi pctl < 0.25)", lambda d: d['fpi_net_pctl'] < 0.25),
        ("FPI buying hard    (fpi pctl > 0.75)", lambda d: d['fpi_net_pctl'] > 0.75),
        ("FPI 5d selling     (fpi 5d pctl < 0.25)", lambda d: d['fpi_net_5d_pctl'] < 0.25),
        ("FPI 5d buying      (fpi 5d pctl > 0.75)", lambda d: d['fpi_net_5d_pctl'] > 0.75),
        ("Retail selling     (retail pctl < 0.25)", lambda d: d['retail_net_pctl'] < 0.25),
        ("Retail buying      (retail pctl > 0.75)", lambda d: d['retail_net_pctl'] > 0.75),
        ("Retail 5d selling  (retail 5d pctl < 0.25)", lambda d: d['retail_net_5d_pctl'] < 0.25),
        ("Retail 5d buying   (retail 5d pctl > 0.75)", lambda d: d['retail_net_5d_pctl'] > 0.75),
        ("DII absorbing      (dii_net > 0)", lambda d: d['dii_net'] > 0),
        ("DII buying hard    (dii pctl > 0.75)", lambda d: d['dii_net_pctl'] > 0.75),
        ("DII 5d buying      (dii 5d pctl > 0.75)", lambda d: d['dii_net_5d_pctl'] > 0.75),
        ("Divergence high    (retail-FPI pctl > 0.75)", lambda d: d['divergence_pctl'] > 0.75),
        ("Divergence low     (retail-FPI pctl < 0.25)", lambda d: d['divergence_pctl'] < 0.25),
        ("Opposite signs     (retail>0 & FPI<0)", lambda d: (d['retail_net'] > 0) & (d['fpi_net'] < 0)),
        ("Both selling       (retail<0 & FPI<0)", lambda d: (d['retail_net'] < 0) & (d['fpi_net'] < 0)),
    ]

    print(f"{'gate':<44} {'n':>6} {'days':>5}  {'net/tr':>8}  {'edge':>8}  {'z':>8} {'z_day':>7} {'z_paired':>8}  {'win':>8}")
    print("-" * 112)
    for name, gate in gates:
        trades, _ = trades_for(stocks, flows, gate=gate)
        print(summarize(name, trades, control))

    print("\nNOTE: 16 gates were tried. The best-looking one is the maximum of 16 noisy draws;")
    print("treat any single z-score here as search-inflated unless it survives a deflated-Sharpe")
    print("or block-bootstrap check. Sample is 3.3 years of one regime (persistent FPI selling).")


if __name__ == "__main__":
    run()
