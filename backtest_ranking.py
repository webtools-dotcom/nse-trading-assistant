"""When you can only take 1-3 trades a day, does ranking candidates differently pay?

backtest_stock_proxies.py rejected price and CGO as GATES: they raise return per trade but cut
trade count, so aggregate edge falls. That criterion assumes you take every signal. With finite
capital you take two or three, and then expected value per trade is what matters.

This tests them as RANKINGS instead: on each day, order that day's candidates by a scheme, take
the top N, and compare schemes on the SAME days (paired), so a scheme cannot win by trading on
easier days.

Two properties of this design worth noting:
  - At N=1 there is one trade per day, so trades are near-independent by construction and the
    day-clustering problem that sank the flow gates does not arise.
  - A RANDOM pick among each day's candidates is included. If no scheme beats random selection,
    ranking does not matter and the current sort is not evidence-based either.

SIMPLIFICATIONS (deliberate):
  - Per-stock non-overlap is enforced, but a name already held can be picked again on a later
    day by a different scheme; there is no portfolio-level position cap.
  - The 'net_ev' scheme reproduces only the deterministic part of the live sort (RSI-band gross
    edge minus round-trip cost). The live tool also uses meta-model P(win), which is not
    computable historically here. So this is a proxy for the current ranking, not a replica.
"""

import numpy as np
import pandas as pd

from backtest_engine import simulate_trades
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR, gross_edge_for_rsi, round_trip_cost_pct

PANEL_FILE = "cache/backtest_5y_short.pkl"
HORIZON = 6
CGO_WINDOW = 504


def build_candidate_trades():
    """Every RSI<30 candidate trade, with its ranking variables frozen at entry."""
    panel = pd.read_pickle(PANEL_FILE)
    rows = []
    for ticker, df in panel.items():
        if CAP_BUCKET_MAP.get(ticker) not in ('Mid', 'Small'):
            continue
        d = df.sort_values('date').reset_index(drop=True).copy()
        if len(d) < 300:
            continue
        vwap = ((d['close'] * d['volume']).rolling(CGO_WINDOW).sum()
                / d['volume'].rolling(CGO_WINDOW).sum())
        d['cgo'] = (d['close'] - vwap) / d['close']
        d['nominal_price'] = d['close']

        mask = ((d['rsi'] < 30) & (d['turnover_60d'] >= MIN_TURNOVER_INR)).fillna(False).values
        for t in simulate_trades(d, mask, horizon_days=HORIZON):
            i = t['entry_idx']
            rows.append({
                'ticker': ticker, 'date': d['date'].iloc[i], 'net_pct': t['net_pct'],
                'rsi': d['rsi'].iloc[i], 'turnover_60d': d['turnover_60d'].iloc[i],
                'nominal_price': d['nominal_price'].iloc[i], 'cgo': d['cgo'].iloc[i],
            })
    trades = pd.DataFrame(rows)

    # Cross-sectional percentiles among the candidates competing on the same day - this is a
    # ranking test, so the comparison set is that day's actual choices.
    for col in ['nominal_price', 'cgo']:
        trades[col + '_pctl'] = trades.groupby('date')[col].rank(pct=True)

    trades['net_ev'] = [gross_edge_for_rsi(r) - round_trip_cost_pct(t)
                        for r, t in zip(trades['rsi'], trades['turnover_60d'])]
    return trades


def pick(trades, scheme, n, seed=0):
    """Top-n per day under a scheme. Returns a Series of mean net return per day."""
    rng = np.random.default_rng(seed)
    if scheme == 'random':
        key = pd.Series(rng.random(len(trades)), index=trades.index)
    elif scheme == 'net_ev':
        key = -trades['net_ev']
    elif scheme == 'price_low':
        key = trades['nominal_price_pctl']
    elif scheme == 'cgo_high':
        key = -trades['cgo_pctl']
    elif scheme == 'deep_rsi':
        key = trades['rsi']
    elif scheme == 'composite':
        # equal-weight: cheap, high CGO, high net EV
        key = -((1 - trades['nominal_price_pctl']) + trades['cgo_pctl'].fillna(0.5)
                + trades['net_ev'].rank(pct=True))
    else:
        raise ValueError(scheme)

    t = trades.assign(_k=key).sort_values(['date', '_k'])
    return t.groupby('date').head(n).groupby('date')['net_pct'].mean()


def compare(trades, n, schemes, reference='net_ev'):
    ref = pick(trades, reference, n)
    print(f"\n--- top {n} per day " + "-" * 60)
    print(f"  {'scheme':<14} {'days':>6} {'net/trade':>10} {'vs ref':>9} {'z_paired':>9}")
    for s in schemes:
        got = pick(trades, s, n)
        if s == reference:
            print(f"  {s:<14} {len(got):>6} {got.mean():>+9.3f}%  {'(ref)':>8} {'':>9}")
            continue
        diff = (got - ref).dropna()
        z = (diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)))) if len(diff) > 2 else 0.0
        print(f"  {s:<14} {len(got):>6} {got.mean():>+9.3f}% {got.mean() - ref.mean():>+8.3f}% "
              f"{z:>9.2f}")


def main():
    trades = build_candidate_trades()
    print(f"{len(trades):,} candidate trades on {trades['date'].nunique()} days "
          f"({trades['date'].min().date()} -> {trades['date'].max().date()})")
    per_day = trades.groupby('date').size()
    print(f"candidates per day: median {per_day.median():.0f}, mean {per_day.mean():.1f}, "
          f"max {per_day.max()}")
    print(f"all candidates, mean net/trade: {trades['net_pct'].mean():+.3f}%")

    schemes = ['net_ev', 'random', 'deep_rsi', 'price_low', 'cgo_high', 'composite']
    for n in (1, 2, 3):
        compare(trades, n, schemes)

    print("\n" + "=" * 78)
    print("z_paired compares each scheme to net_ev on the SAME days. 5 schemes x 3 depths")
    print("= 15 comparisons; treat the best as the max of 15 noisy draws.")


if __name__ == "__main__":
    main()
