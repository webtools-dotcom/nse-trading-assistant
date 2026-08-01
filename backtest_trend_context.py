# backtest_trend_context.py
import pandas as pd
import numpy as np
from data_fetcher import download_watchlist_history, add_features
from config import WATCHLIST


def add_trend_context(stock_df):
    stock_df = stock_df.sort_values('date').reset_index(drop=True)
    stock_df['change_252d'] = stock_df['close'].pct_change(252) * 100
    stock_df['change_60d'] = stock_df['close'].pct_change(60) * 100
    return stock_df


def simulate_trades(stock_df, entry_condition, horizon_days=6, stop_atr_mult=2, target_atr_mult=2):
    trades = []
    for i in range(len(stock_df) - horizon_days - 1):
        row = stock_df.iloc[i]
        if pd.isna(row.get('rsi')) or pd.isna(row.get('atr')) or pd.isna(row.get('change_252d')):
            continue
        if not entry_condition(row):
            continue
        entry_price = row['close']
        atr = row['atr']
        stop_loss = entry_price - stop_atr_mult * atr
        target = entry_price + target_atr_mult * atr
        outcome, exit_price = None, None
        for j in range(1, horizon_days + 1):
            if i + j >= len(stock_df):
                break
            future_row = stock_df.iloc[i + j]
            if future_row['low'] <= stop_loss:
                outcome, exit_price = 'stop_loss', stop_loss
                break
            if future_row['high'] >= target:
                outcome, exit_price = 'target', target
                break
        if outcome is None:
            if i + horizon_days < len(stock_df):
                exit_price = stock_df.iloc[i + horizon_days]['close']
                outcome = 'time_exit'
            else:
                continue
        return_pct = ((exit_price - entry_price) / entry_price) * 100
        trades.append({'return_pct': return_pct, 'outcome': outcome})
    return trades


def compute_stats(trades):
    if len(trades) == 0:
        return None
    df = pd.DataFrame(trades)
    n = len(df)
    avg = df['return_pct'].mean()
    std = df['return_pct'].std()
    return {'n_trades': n, 'avg_return': avg, 'stderr': std / np.sqrt(n)}


def run():
    print("Downloading data...")
    combined_df = download_watchlist_history(WATCHLIST, period="5y")

    buckets = {
        'RSI<30, in DOWNTREND (1yr change < -20%)': [],
        'RSI<30, in MILD/FLAT trend (1yr change -20% to +20%)': [],
        'RSI<30, in UPTREND (1yr change > +20%)': [],
    }
    random_trades = []
    np.random.seed(42)

    for ticker in combined_df['ticker'].unique():
        stock_df = combined_df[combined_df['ticker'] == ticker].copy()
        stock_df = add_features(stock_df, horizon=6)
        stock_df = add_trend_context(stock_df)

        buckets['RSI<30, in DOWNTREND (1yr change < -20%)'].extend(
            simulate_trades(stock_df, lambda r: r['rsi'] < 30 and r['change_252d'] < -20))
        buckets['RSI<30, in MILD/FLAT trend (1yr change -20% to +20%)'].extend(
            simulate_trades(stock_df, lambda r: r['rsi'] < 30 and -20 <= r['change_252d'] <= 20))
        buckets['RSI<30, in UPTREND (1yr change > +20%)'].extend(
            simulate_trades(stock_df, lambda r: r['rsi'] < 30 and r['change_252d'] > 20))

        stock_df['random_signal'] = np.random.random(len(stock_df)) < 0.10
        random_trades.extend(simulate_trades(stock_df, lambda r: r['random_signal']))

    random_stats = compute_stats(random_trades)
    print(f"\n{'='*90}\nRANDOM CONTROL: {random_stats}\n{'='*90}")

    for name, trades in buckets.items():
        stats = compute_stats(trades)
        if stats is None:
            print(f"\n{name}: no trades")
            continue
        edge = stats['avg_return'] - random_stats['avg_return']
        combined_se = np.sqrt(stats['stderr']**2 + random_stats['stderr']**2)
        z = edge / combined_se if combined_se > 0 else 0
        print(f"\n{name}")
        print(f"  Trades: {stats['n_trades']}, Avg return: {stats['avg_return']:.2f}%, Edge vs random: {edge:.2f}%, Z-score: {z:.2f}")


if __name__ == "__main__":
    run()