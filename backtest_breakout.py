"""Backtest the Catalyst-Fueled Momentum Breakout (VCP / High-Tight-Base) engine for real edge.

Requirements:
- Entry signal: close > ema_20 > sma_50 > sma_200
               AND dist_from_high_252 between -0.15 and -0.025 (within 2.5–15% of 52W high)
               AND base_depth_pct <= 6.0
               AND vcp_ratio (atr_5 / atr_20) < 0.75
               AND turnover_60d >= MIN_TURNOVER_INR (Rs 25cr)
               Non-overlapping.
- Exit: horizon_days=7, stop_pct=0.045 (4.5%), charge_costs=True.
- Control: random-entry trades drawn from the same universe, same exit params.
- Inference: day-clustered paired z-score (z_paired) vs same-day control, split by cap tier.
- Confluence score check: bucket trades by score decile to check return monotonicity.
"""

import numpy as np
import pandas as pd
from scipy import stats

from backtest_engine import (
    simulate_trades,
    edge_vs_control,
    day_clustered_edge,
    average_uniqueness,
)
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR

PANEL_FILE = "cache/backtest_5y_short.pkl"
HORIZON_DAYS = 7
STOP_PCT = 0.045


def load_panel():
    panel = pd.read_pickle(PANEL_FILE)
    out = []
    for ticker, df in panel.items():
        df = df.sort_values('date').reset_index(drop=True)
        if len(df) < 300:
            continue
        out.append((ticker, CAP_BUCKET_MAP.get(ticker, 'Unknown'), df))
    return out


def breakout_signal(df):
    c1 = df['close'] > df['ema_20']
    c2 = df['ema_20'] > df['sma_50']
    c3 = df['sma_50'] > df['sma_200']
    c4 = (df['dist_from_high_252'] >= -0.15) & (df['dist_from_high_252'] <= -0.025)
    c5 = df['base_depth_pct'] <= 6.0
    c6 = df['vcp_ratio'] < 0.75
    c7 = df['turnover_60d'] >= MIN_TURNOVER_INR
    return c1 & c2 & c3 & c4 & c5 & c6 & c7


def compute_confluence_score(df, i):
    vcp_ratio = df['vcp_ratio'].iloc[i]
    base_depth_pct = df['base_depth_pct'].iloc[i]
    score_base = 30 if vcp_ratio < 0.75 and base_depth_pct < 5.0 else (20 if vcp_ratio < 0.90 and base_depth_pct < 8.0 else 10)

    dist_52w = df['dist_from_high_252'].iloc[i]
    close = df['close'].iloc[i]
    ema_20 = df['ema_20'].iloc[i]
    sma_50 = df['sma_50'].iloc[i]
    sma_200 = df['sma_200'].iloc[i]
    trend_aligned = bool(close >= ema_20 and ema_20 >= sma_50)
    stage2_strong = bool(trend_aligned and close >= sma_200)
    score_trend = 25 if dist_52w >= -0.10 and stage2_strong else (15 if dist_52w >= -0.20 and trend_aligned else 5)

    momentum_60d = df['momentum_60d'].iloc[i]
    score_rs = 20 if momentum_60d >= 30 else (15 if momentum_60d >= 15 else (10 if momentum_60d >= 0 else 0))

    turnover = df['turnover_60d'].iloc[i]
    turnover_cr = (turnover / 1e7) if pd.notna(turnover) else 0
    rvol = df['rvol'].iloc[i] if 'rvol' in df.columns and pd.notna(df['rvol'].iloc[i]) else 1.0
    score_vol = (15 if turnover_cr >= 25 else 5) + (10 if rvol and rvol >= 1.5 else 0)

    return score_base + score_trend + score_rs + score_vol


def collect_trades(panel, universe_filter=None, seed=42):
    rng = np.random.default_rng(seed)
    strat_trades, ctrl_trades = [], []
    all_uniqueness = []

    for ticker, cap, df in panel:
        if universe_filter is not None and not universe_filter(ticker, cap, df):
            continue

        mask = breakout_signal(df).fillna(False).values
        # Random control drawn from the exact same stock universe
        rand_mask = rng.random(len(df)) < 0.08
        dates = df['date'].values

        # Strategy trades
        s_tr = simulate_trades(
            df, mask, horizon_days=HORIZON_DAYS, stop_pct=STOP_PCT,
            charge_costs=True, allow_overlap=False
        )
        for t in s_tr:
            t['ticker'] = ticker
            t['cap_bucket'] = cap
            t['entry_date'] = dates[t['entry_idx']]
            t['confluence_score'] = compute_confluence_score(df, t['entry_idx'])
            strat_trades.append(t)

        if s_tr:
            all_uniqueness.append(average_uniqueness(s_tr, len(df)))

        # Control trades
        c_tr = simulate_trades(
            df, rand_mask, horizon_days=HORIZON_DAYS, stop_pct=STOP_PCT,
            charge_costs=True, allow_overlap=False
        )
        for t in c_tr:
            t['ticker'] = ticker
            t['cap_bucket'] = cap
            t['entry_date'] = dates[t['entry_idx']]
            ctrl_trades.append(t)

    avg_uniq = float(np.mean(all_uniqueness)) if all_uniqueness else 1.0
    return strat_trades, ctrl_trades, avg_uniq


def format_tier_report(label, strat, ctrl, avg_uniq):
    if len(strat) < 20:
        return f"  {label:<28} {len(strat):>7} {len(set(t['entry_date'] for t in strat)):>6} trades - sample too small"

    naive = edge_vs_control([t['net_pct'] for t in strat], [t['net_pct'] for t in ctrl])
    clu = day_clustered_edge(strat, ctrl)
    if clu is None:
        return f"  {label:<28} {len(strat):>7} trades - insufficient distinct days"

    win_rate = float(np.mean([t['net_pct'] > 0 for t in strat]) * 100)
    strat_net = float(np.mean([t['net_pct'] for t in strat]))
    ctrl_net = float(np.mean([t['net_pct'] for t in ctrl]))
    edge = strat_net - ctrl_net
    z_paired = clu['z_paired']
    n_days = clu['n_days']
    n_trades = len(strat)

    verdict = "VALIDATED (PASS)" if z_paired >= 2.0 else ("WEAK (FAIL)" if z_paired >= 1.0 else "DEAD (FAIL)")

    return (f"  {label:<28} {n_trades:>7} {n_days:>6}  {win_rate:>6.1f}%  "
            f"{strat_net:>+7.3f}%  {ctrl_net:>+7.3f}%  {edge:>+7.3f}%  "
            f"{naive['z']:>7.2f}  {z_paired:>8.2f}  {avg_uniq:>7.3f}   {verdict}")


def analyze_confluence_deciles(strat_trades):
    if not strat_trades:
        print("No trades to evaluate confluence deciles.")
        return

    df = pd.DataFrame(strat_trades)
    print("\n" + "=" * 88)
    print("CONFLUENCE SCORE PREDICTIVE POWER CHECK (Decile / Quantile Analysis)")
    print("=" * 88)
    print(f"Total strategy trades analyzed: {len(df)}")
    print("Score Summary: min={:.0f}, p25={:.0f}, median={:.0f}, p75={:.0f}, max={:.0f}".format(
        df['confluence_score'].min(), df['confluence_score'].quantile(0.25),
        df['confluence_score'].median(), df['confluence_score'].quantile(0.75),
        df['confluence_score'].max()
    ))

    # Bucket by score bins
    try:
        df['score_bin'] = pd.qcut(df['confluence_score'], q=5, duplicates='drop')
    except Exception:
        df['score_bin'] = pd.cut(df['confluence_score'], bins=5)

    grouped = df.groupby('score_bin', observed=False).agg(
        n_trades=('net_pct', 'count'),
        avg_score=('confluence_score', 'mean'),
        win_rate=('net_pct', lambda x: (x > 0).mean() * 100),
        net_return=('net_pct', 'mean'),
        gross_return=('gross_pct', 'mean')
    ).reset_index()

    print(f"\n  {'Score Range':<24} {'Trades':>8} {'Avg Score':>10} {'Win Rate':>10} {'Net Return %':>14} {'Gross Return %':>15}")
    print("  " + "-" * 85)
    for _, r in grouped.iterrows():
        print(f"  {str(r['score_bin']):<24} {int(r['n_trades']):>8} {r['avg_score']:>10.1f} {r['win_rate']:>9.1f}% {r['net_return']:>+13.3f}% {r['gross_return']:>+14.3f}%")

    # Linear correlation between confluence score and forward net return
    corr, pval = stats.pearsonr(df['confluence_score'], df['net_pct'])
    print(f"\nPearson correlation between Confluence Score & Net Return: r = {corr:+.4f} (p-value = {pval:.4f})")
    if pval < 0.05 and corr > 0.05:
        print("--> Result: Score shows statistically significant positive monotonic ranking power.")
    else:
        print("--> Result: Score does NOT have monotonic predictive power (flat/noisy) - de-emphasize ranking.")


def run_all():
    print("Loading 5-year panel (cache/backtest_5y_short.pkl)...")
    panel = load_panel()
    date_min = panel[0][2]['date'].min().date()
    date_max = panel[0][2]['date'].max().date()
    print(f"Universe: {len(panel)} stocks across {date_min} -> {date_max}")
    print(f"Strategy: Momentum Breakout (EMA trend + VCP Squeeze + 52W proximity + Turnover >= Rs25cr)")
    print(f"Exit Parameters: horizon_days={HORIZON_DAYS}, stop_pct={STOP_PCT*100:.1f}%, Indian costs charged=True\n")

    HEADER = (f"  {'Tier / Segment':<28} {'Trades':>7} {'Days':>6}  {'WinRate':>7}  "
              f"{'StratNet':>8}  {'CtrlNet':>8}  {'Edge':>8}  "
              f"{'NaiveZ':>7}  {'z_paired':>8}  {'Uniq':>7}   Verdict")

    print("=" * 115)
    print("TABLE 1: BREAKOUT STRATEGY EDGE BY CAP TIER (Day-Clustered Paired Control)")
    print("=" * 115)
    print(HEADER)
    print("  " + "-" * 110)

    all_strat_trades = []

    for cap in ['Small', 'Mid', 'Large']:
        strat, ctrl, avg_uniq = collect_trades(panel, universe_filter=lambda t, cp, d, cap=cap: cp == cap)
        all_strat_trades.extend(strat)
        print(format_tier_report(f"{cap}-Cap", strat, ctrl, avg_uniq))

    # Mid + Small combination (the core active universe)
    midsmall_filter = lambda t, cp, d: cp in ('Mid', 'Small')
    strat_ms, ctrl_ms, uniq_ms = collect_trades(panel, universe_filter=midsmall_filter)
    print(format_tier_report("Mid + Small (Liquid)", strat_ms, ctrl_ms, uniq_ms))

    # Full Universe
    strat_all, ctrl_all, uniq_all = collect_trades(panel, universe_filter=None)
    print(format_tier_report("All Tiers Combined", strat_all, ctrl_all, uniq_all))

    print("\n" + "=" * 115)
    print("Key:")
    print("  StratNet  = Average NET return % per trade (costs charged)")
    print("  CtrlNet   = Same-universe random-entry control NET return % per trade")
    print("  Edge      = StratNet - CtrlNet (excess return over random entry)")
    print("  NaiveZ    = Standard trade-level 2-sample z-score (inflated by cross-sectional co-movement)")
    print("  z_paired  = DAY-CLUSTERED paired z-score (the honest non-negotiable benchmark; PASS if >= 2.0)")
    print("  Uniq      = Average sample uniqueness (1.0 = fully independent)")

    # Part 1: Confluence score analysis
    analyze_confluence_deciles(strat_all)


if __name__ == "__main__":
    run_all()
