import pandas as pd
import numpy as np
from data_fetcher_long import download_watchlist_history, add_features
from config import WATCHLIST, CAP_BUCKET_MAP


def simulate_trades_pct(stock_df, entry_condition, horizon_days=20, stop_pct=0.08, target_pct=0.16):
    trades = []
    for i in range(len(stock_df) - horizon_days - 1):
        row = stock_df.iloc[i]
        if pd.isna(row.get('rsi')) or pd.isna(row.get('sma_200')):
            continue
        if not entry_condition(row):
            continue

        entry_price = row['close']
        stop_loss = entry_price * (1 - stop_pct)
        target = entry_price * (1 + target_pct)

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
    stderr = std / np.sqrt(n)
    return {'n_trades': n, 'avg_return': avg, 'stderr': stderr}


def run_stratified_backtest():
    print("Downloading data for stratified long-term backtest...")
    combined_df = download_watchlist_history(WATCHLIST, period="5y")

    bucket_trades = {'Large': [], 'Mid': [], 'Small': []}
    bucket_random_trades = {'Large': [], 'Mid': [], 'Small': []}
    np.random.seed(42)

    momentum_condition = lambda r: r['close'] > r['sma_50'] > r['sma_200'] and r['dist_from_high_252'] > -0.10

    for ticker in combined_df['ticker'].unique():
        bucket = CAP_BUCKET_MAP.get(ticker)
        if bucket is None:
            continue

        stock_df = combined_df[combined_df['ticker'] == ticker].copy()
        stock_df = add_features(stock_df, horizon=20).reset_index(drop=True)

        bucket_trades[bucket].extend(simulate_trades_pct(stock_df, momentum_condition))

        stock_df['random_signal'] = np.random.random(len(stock_df)) < 0.05
        bucket_random_trades[bucket].extend(simulate_trades_pct(stock_df, lambda r: r['random_signal']))

    print(f"\n{'='*90}")
    print("LONG-TERM STRATEGY (Near 52w High + Uptrend) - STRATIFIED BY MARKET CAP")
    print(f"{'='*90}")
    rows = []
    for bucket in ['Large', 'Mid', 'Small']:
        strat_stats = compute_stats(bucket_trades[bucket])
        rand_stats = compute_stats(bucket_random_trades[bucket])
        if strat_stats is None or rand_stats is None:
            continue
        edge = strat_stats['avg_return'] - rand_stats['avg_return']
        combined_se = np.sqrt(strat_stats['stderr']**2 + rand_stats['stderr']**2)
        z = edge / combined_se if combined_se > 0 else 0
        rows.append({
            'Bucket': bucket, 'Trades': strat_stats['n_trades'],
            'Strategy Avg %': round(strat_stats['avg_return'], 2),
            'Random Avg %': round(rand_stats['avg_return'], 2),
            'Edge': round(edge, 2), 'Z-score': round(z, 2)
        })
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"{'='*90}")


if __name__ == "__main__":
    run_stratified_backtest()