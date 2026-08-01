"""Do stock-level behavioral proxies add anything to the RSI<30 mid/small entry?

Tests the buildable proxies from behavioral_rule_spec_2.md. Unlike the market-level flow gates
(backtest_flow_gate.py, rejected), these vary ACROSS STOCKS ON THE SAME DAY, so they select
stocks within a day rather than selecting days - which is what survives day-clustering.

Three things this is careful about:

1. CROSS-SECTIONAL RANKS ARE COMPUTED ACROSS THE WHOLE UNIVERSE PER DAY, which is how these
   anomalies are defined in the literature - not among that day's oversold candidates only.

2. EVERY GATE IS COMPARED AGAINST A MATCHED BASELINE. A 504-day CGO lookback silently drops the
   first two years; comparing that against a full-sample baseline would credit the filter for a
   change of period. Each gate's baseline is the ungated signal on exactly the rows where that
   proxy is computable.

3. DAY-CLUSTERED INFERENCE. See backtest_engine.day_clustered_edge.

CGO CAVEAT: Grinblatt-Han weight the reference price by turnover = volume / shares outstanding.
Shares outstanding is not in this project's data, so this uses a volume-weighted average price
over the same 504-day window. Defensible substitute, NOT the published estimator.
"""

import numpy as np
import pandas as pd

from backtest_engine import simulate_trades, edge_vs_control, day_clustered_edge
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR

PANEL_FILE = "cache/backtest_5y_short.pkl"
HORIZON = 6
MAX_WINDOW = 21      # trailing month, per Bali et al.
PTH_WINDOW = 252     # 52 weeks
CGO_WINDOW = 504     # 2 years, per Grinblatt-Han


def build_long_panel():
    """One long DataFrame with per-stock proxies plus per-day cross-sectional percentiles."""
    panel = pd.read_pickle(PANEL_FILE)
    frames = []
    for ticker, df in panel.items():
        if CAP_BUCKET_MAP.get(ticker) not in ('Mid', 'Small'):
            continue
        d = df.sort_values('date').reset_index(drop=True).copy()
        if len(d) < 300:
            continue
        d['ticker'] = ticker
        ret = d['close'].pct_change()
        d['max21'] = ret.rolling(MAX_WINDOW).max()
        d['nominal_price'] = d['close']
        d['pth'] = d['close'] / d['high'].rolling(PTH_WINDOW).max()
        vwap = (d['close'] * d['volume']).rolling(CGO_WINDOW).sum() / d['volume'].rolling(CGO_WINDOW).sum()
        d['cgo'] = (d['close'] - vwap) / d['close']
        frames.append(d)

    long = pd.concat(frames, ignore_index=True)
    # Cross-sectional percentile within each trading day, across the whole universe - the
    # literature's definition. Ranking only among that day's oversold names would measure a
    # different thing.
    for col in ['max21', 'nominal_price', 'pth', 'cgo']:
        long[col + '_pctl'] = long.groupby('date')[col].rank(pct=True)
    return long


def base_signal(d):
    return (d['rsi'] < 30) & (d['turnover_60d'] >= MIN_TURNOVER_INR)


def run_pair(long, gate, proxy_col):
    """Returns (gated_trades, matched_baseline_trades, control_trades).

    The baseline is restricted to rows where proxy_col is computable, so the gate is never
    credited for the change of sample its own lookback imposes.
    """
    rng = np.random.default_rng(42)
    gated, baseline, control = [], [], []
    for ticker, d in long.groupby('ticker', sort=False):
        d = d.reset_index(drop=True)
        computable = d[proxy_col].notna()
        base = (base_signal(d) & computable).fillna(False)
        gmask = (base & gate(d)).fillna(False)
        cmask = pd.Series(rng.random(len(d)) < 0.10, index=d.index) & computable

        dates = d['date'].values
        for lst, m in ((gated, gmask), (baseline, base), (control, cmask)):
            for t in simulate_trades(d, m.values, horizon_days=HORIZON):
                t['entry_date'] = dates[t['entry_idx']]
                lst.append(t)
    return gated, baseline, control


def line(label, trades, control, base_z=None):
    if len(trades) < 30:
        return f"  {label:<40} {len(trades):>6}  too few trades"
    naive = edge_vs_control([t['net_pct'] for t in trades], [t['net_pct'] for t in control])
    clu = day_clustered_edge(trades, control)
    if clu is None:
        return f"  {label:<40} {len(trades):>6}  insufficient days"
    delta = "" if base_z is None else f"  {clu['z_paired'] - base_z:+6.2f} vs base"
    return (f"  {label:<40} {naive['n_strategy']:>6} {clu['n_days']:>6}  "
            f"{naive['strategy_avg']:+7.3f}%  {naive['z']:>6.2f}  {clu['z_paired']:>7.2f}{delta}")


HEADER = (f"  {'gate':<40} {'trades':>6} {'days':>6}  {'net/tr':>8}  {'z':>6}  {'z_paired':>7}")


def main():
    long = build_long_panel()
    print(f"Universe: {long['ticker'].nunique()} mid/small stocks, "
          f"{long['date'].min().date()} -> {long['date'].max().date()}, {len(long):,} stock-days\n")

    tests = [
        ("MAX", 'max21_pctl', [
            ("EXCLUDE top decile MAX", lambda d: d['max21_pctl'] <= 0.90),
            ("EXCLUDE top quintile MAX", lambda d: d['max21_pctl'] <= 0.80),
            ("EXCLUDE top half MAX", lambda d: d['max21_pctl'] <= 0.50),
            ("INCLUDE only top decile MAX (inverse)", lambda d: d['max21_pctl'] > 0.90),
        ]),
        ("Nominal price", 'nominal_price_pctl', [
            ("INCLUDE bottom quintile price", lambda d: d['nominal_price_pctl'] <= 0.20),
            ("INCLUDE bottom half price", lambda d: d['nominal_price_pctl'] <= 0.50),
            ("INCLUDE top quintile price (inverse)", lambda d: d['nominal_price_pctl'] > 0.80),
        ]),
        ("52w-high nearness", 'pth_pctl', [
            ("INCLUDE top decile PTH", lambda d: d['pth_pctl'] > 0.90),
            ("INCLUDE top quartile PTH", lambda d: d['pth_pctl'] > 0.75),
            ("INCLUDE PTH > 0.90 (absolute)", lambda d: d['pth'] > 0.90),
        ]),
        ("CGO (approximated)", 'cgo_pctl', [
            ("INCLUDE positive CGO", lambda d: d['cgo'] > 0),
            ("INCLUDE top quartile CGO", lambda d: d['cgo_pctl'] > 0.75),
            ("INCLUDE bottom quartile CGO (inverse)", lambda d: d['cgo_pctl'] < 0.25),
        ]),
    ]

    for family, proxy_col, gates in tests:
        print("=" * 100)
        print(f"{family}   (baseline matched to rows where this proxy is computable)")
        print(HEADER)
        _, baseline, control = run_pair(long, lambda d: pd.Series(True, index=d.index), proxy_col)
        base = day_clustered_edge(baseline, control)
        print(line("BASELINE  RSI<30, ungated", baseline, control))
        for label, gate in gates:
            gated, _, _ = run_pair(long, gate, proxy_col)
            print(line(label, gated, control, base_z=base['z_paired'] if base else None))
        print()

    print("=" * 100)
    print("A filter earns its place only by beating its OWN baseline row, not by looking good alone.")
    print("13 gates were tried across 4 families; the best is the max of 13 noisy draws.")


if __name__ == "__main__":
    main()
