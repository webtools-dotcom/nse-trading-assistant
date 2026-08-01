"""Re-runs the README's headline strategy tables with day-clustered inference.

Why: every published z-score in the README treats each trade as an independent observation.
Non-overlapping entries make that true WITHIN a stock - which the 2026-07 correction fixed -
but not ACROSS stocks. On a day the whole market is oversold, hundreds of names trigger at
once and their forward returns share one market factor.

This re-measures the same tables with each day's strategy mean tested against the SAME day's
random-entry control, which isolates stock-selection skill from market-wide moves.

Nothing here changes the strategy. It changes how confident we are allowed to be about it.
"""

import numpy as np
import pandas as pd

from backtest_engine import simulate_trades, edge_vs_control, day_clustered_edge
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR

PANEL_FILE = "cache/backtest_5y_short.pkl"
HORIZON = 6


def load_panel():
    panel = pd.read_pickle(PANEL_FILE)
    out = []
    for ticker, df in panel.items():
        df = df.sort_values('date').reset_index(drop=True)
        if len(df) < 300:
            continue
        out.append((ticker, CAP_BUCKET_MAP.get(ticker), df))
    return out


def collect(panel, signal, universe=None, seed=42):
    """Returns (strategy_trades, control_trades) over the same stock subset.

    The control is drawn from exactly the universe the strategy is allowed to trade, so a
    result cannot come from the subset being an easier place to trade in general.
    """
    rng = np.random.default_rng(seed)
    strat, ctrl = [], []
    for ticker, cap, df in panel:
        if universe is not None and not universe(ticker, cap, df):
            continue
        mask = signal(df).fillna(False).values
        rand = rng.random(len(df)) < 0.10
        dates = df['date'].values
        for lst, m in ((strat, mask), (ctrl, rand)):
            for t in simulate_trades(df, m, horizon_days=HORIZON):
                t['entry_date'] = dates[t['entry_idx']]
                lst.append(t)
    return strat, ctrl


def row(label, strat, ctrl, published=None):
    if len(strat) < 30:
        return f"  {label:<34} {len(strat):>6} trades - too few"
    naive = edge_vs_control([t['net_pct'] for t in strat], [t['net_pct'] for t in ctrl])
    clu = day_clustered_edge(strat, ctrl)
    if clu is None:
        return f"  {label:<34} {len(strat):>6} trades - insufficient days"
    pub = f"{published:>6.2f}" if published is not None else "     -"
    verdict = "OK" if clu['z_paired'] >= 2.0 else ("weak" if clu['z_paired'] >= 1.0 else "GONE")
    return (f"  {label:<34} {naive['n_strategy']:>6} {clu['n_days']:>6}  "
            f"{naive['strategy_avg']:+7.3f}%  {pub}  {naive['z']:>7.2f}  "
            f"{clu['z_paired']:>8.2f}   {verdict}")


HEADER = (f"  {'segment':<34} {'trades':>6} {'days':>6}  {'net/tr':>8}  {'pub_z':>6}  "
          f"{'naive_z':>7}  {'z_paired':>8}   verdict")


def rsi30(df):
    return df['rsi'] < 30


def liquid_rsi30(df):
    return (df['rsi'] < 30) & (df['turnover_60d'] >= MIN_TURNOVER_INR)


def run():
    panel = load_panel()
    print(f"Panel: {len(panel)} stocks, {panel[0][2]['date'].min().date()} -> "
          f"{panel[0][2]['date'].max().date()}, horizon {HORIZON}d, costs charged\n")
    print("pub_z    = published corrected z in README (trade-level)")
    print("naive_z  = trade-level, reproduced here")
    print("z_paired = day-clustered vs same-day random control  <-- the honest number\n")

    print("=" * 104)
    print("TABLE 1 - Market-cap segment (RSI<30, no turnover filter, as published)")
    print(HEADER)
    for cap, pub in [('Small', 7.03), ('Mid', 5.20), ('Large', 0.55)]:
        s, c = collect(panel, rsi30, universe=lambda t, cp, d, cap=cap: cp == cap)
        print(row(cap + "-cap", s, c, pub))

    print("\n" + "=" * 104)
    print("TABLE 2 - 1-year trend context (RSI<30, Mid/Small, >=Rs25cr - the live universe)")
    print(HEADER)
    midsmall = lambda t, cp, d: cp in ('Mid', 'Small')
    tiers = [
        ("Uptrend (>+20% 1yr)", 7.58, lambda d: liquid_rsi30(d) & (d['change_252d'] > 20)),
        ("Flat/Mild (-20%..+20%)", 5.42, lambda d: liquid_rsi30(d) & d['change_252d'].between(-20, 20)),
        ("Downtrend (<-20% 1yr)", 3.18, lambda d: liquid_rsi30(d) & (d['change_252d'] < -20)),
    ]
    for label, pub, sig in tiers:
        s, c = collect(panel, sig, universe=midsmall)
        print(row(label, s, c, pub))

    print("\n" + "=" * 104)
    print("TABLE 3 - Oversold depth (Mid/Small, >=Rs25cr)")
    print(HEADER)
    bands = [("RSI < 24", 0, 24), ("RSI 24-26", 24, 26), ("RSI 26-28", 26, 28),
             ("RSI 28-30", 28, 30), ("RSI 30-35", 30, 35)]
    for label, lo, hi in bands:
        sig = (lambda d, lo=lo, hi=hi: (d['rsi'] >= lo) & (d['rsi'] < hi)
               & (d['turnover_60d'] >= MIN_TURNOVER_INR))
        s, c = collect(panel, sig, universe=midsmall)
        print(row(label, s, c))

    print("\n" + "=" * 104)
    print("TABLE 4 - Liquidity filter (the >=Rs25cr rule itself, Mid/Small, RSI<30)")
    print(HEADER)
    for label, sig in [("Unfiltered turnover", rsi30), ("Turnover >= Rs 25cr", liquid_rsi30)]:
        s, c = collect(panel, sig, universe=midsmall)
        print(row(label, s, c))

    print("\n" + "=" * 104)
    print("TABLE 5 - Chronological attribution (live universe: Mid/Small, >=Rs25cr, RSI<30)")
    print(HEADER)
    periods = [("2021-10 -> 2022-12", '2021-10-01', '2022-12-31'),
               ("2022-12 -> 2024-09", '2022-12-31', '2024-09-30'),
               ("2024-09 -> 2025-02", '2024-09-30', '2025-02-28'),
               ("2025-02 -> 2025-12", '2025-02-28', '2025-12-31'),
               ("2025-12 -> 2026-07", '2025-12-31', '2026-07-29')]
    for label, start, end in periods:
        sub = [(t, cp, d[(d['date'] >= start) & (d['date'] <= end)].reset_index(drop=True))
               for t, cp, d in panel]
        sub = [(t, cp, d) for t, cp, d in sub if len(d) > HORIZON + 20]
        s, c = collect(sub, liquid_rsi30, universe=midsmall)
        print(row(label, s, c))

    print("\n" + "=" * 104)
    print("z_paired >= 2.0 = holds up | 1.0-2.0 = weak | < 1.0 = not distinguishable from control")
    print("These are single tests, not search-adjusted. Table 3 and Table 5 rows are")
    print("subdivisions of one dataset, so their individual z-scores carry multiplicity.")


if __name__ == "__main__":
    run()
