"""Maximum Adverse Excursion (MAE) of the RSI<30 signal: how far do oversold entries dip before
the 6-day horizon ends? Informs stop width - a stop tighter than the typical MAE shakes you out of
trades that would have worked (why the stop was widened to 4xATR).

Measured across ALL entries (winners AND losers) - averaging only over trades that bounced is
survivorship bias. Entry = live universe (RSI<30, Mid/Small, >=Rs25cr). Full 6-day hold with NO
stop (huge stop/target mults -> every trade time-exits), so MAE is the unclipped dip.

    python backtest_mae.py
"""

import numpy as np
import pandas as pd

from backtest_engine import simulate_trades
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR

PANEL = "cache/backtest_5y_short.pkl"
H = 6


def run():
    panel = pd.read_pickle(PANEL)
    depth_pct, mae_atr, wins = [], [], []      # depth_pct = positive % drawdown from entry
    for t, df in panel.items():
        if CAP_BUCKET_MAP.get(t) not in ('Mid', 'Small'):
            continue
        d = df.sort_values('date').reset_index(drop=True)
        if len(d) < 300:
            continue
        mask = ((d['rsi'] < 30) & (d['turnover_60d'] >= MIN_TURNOVER_INR)).fillna(False).values
        low = d['low'].values
        close = d['close'].values
        atr = d['atr'].values
        for tr in simulate_trades(d, mask, horizon_days=H, stop_atr_mult=100, target_atr_mult=100):
            i, held = tr['entry_idx'], tr['held']
            window_low = low[i + 1:i + held + 1].min()
            entry = close[i]
            if entry <= 0 or not np.isfinite(window_low):
                continue
            depth_pct.append((entry - window_low) / entry * 100)      # positive = how far it fell
            if atr[i] > 0:
                mae_atr.append((entry - window_low) / atr[i])          # in ATR multiples
            else:
                mae_atr.append(np.nan)
            wins.append(tr['net_pct'] > 0)

    depth_pct = np.array(depth_pct)
    mae_atr = np.array([x for x in mae_atr if np.isfinite(x)])
    wins = np.array(wins)
    print(f"{len(depth_pct)} oversold entries (ALL - winners + losers), {H}-day no-stop hold\n")

    def dist(name, arr):
        print(f"  {name:<9} median {np.median(arr):5.2f}%   75% within {np.percentile(arr,75):5.2f}%   "
              f"90% within {np.percentile(arr,90):5.2f}%   95% within {np.percentile(arr,95):5.2f}%")

    print("MAE as % drawdown from entry (how far it dips before the 6-day exit):")
    dist("ALL", depth_pct)
    dist("winners", depth_pct[wins])
    dist("losers", depth_pct[~wins])

    print("\nMAE in ATR multiples (directly comparable to the ATR stop multiple):")
    for p in (50, 75, 90, 95):
        print(f"  {p}th pct: {np.percentile(mae_atr, p):.2f} xATR")

    print("\nStop hit-rate - fraction of entries whose dip EXCEEDS the stop (would be stopped out):")
    for mult in (2, 3, 4, 6):
        print(f"  {mult}xATR stop: {(mae_atr > mult).mean()*100:4.0f}% of all entries")

    print("\nRead: set the stop past the bulk of MAE. If winners dip nearly as deep as losers, no stop")
    print("can separate them and a wide/no stop is correct (consistent with backtest_exits.py's 4xATR).")


if __name__ == "__main__":
    try:
        run()
    except FileNotFoundError:
        print("cache/backtest_5y_short.pkl not found - build the 5y panel first.")