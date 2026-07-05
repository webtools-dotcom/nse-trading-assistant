import pandas as pd
import numpy as np
from data_fetcher import download_watchlist_history, add_features
from config import WATCHLIST

def simulate_trades(stock_df, entry_condition, horizon_days=6, stop_atr_mult=2, target_atr_mult=2):
    """Walks through a stock's history day by day, simulating trades wherever entry_condition is True."""
    trades = []
    stock_df = stock_df.reset_index(drop=True)

    for i in range(len(stock_df) - horizon_days - 1):
        row = stock_df.iloc[i]
        if pd.isna(row.get('rsi')) or pd.isna(row.get('atr')):
            continue
        if not entry_condition(row):
            continue

        entry_price = row['close']
        atr = row['atr']
        stop_loss = entry_price - stop_atr_mult * atr
        target = entry_price + target_atr_mult * atr

        outcome, exit_price, exit_day = None, None, None
        for j in range(1, horizon_days + 1):
            if i + j >= len(stock_df):
                break
            future_row = stock_df.iloc[i + j]
            if future_row['low'] <= stop_loss:
                outcome, exit_price, exit_day = 'stop_loss', stop_loss, j
                break
            if future_row['high'] >= target:
                outcome, exit_price, exit_day = 'target', target, j
                break

        if outcome is None:
            if i + horizon_days < len(stock_df):
                exit_price = stock_df.iloc[i + horizon_days]['close']
                outcome, exit_day = 'time_exit', horizon_days
            else:
                continue

        return_pct = ((exit_price - entry_price) / entry_price) * 100
        trades.append({
            'entry_date': row['date'], 'entry_price': entry_price, 'exit_price': exit_price,
            'outcome': outcome, 'exit_day': exit_day, 'return_pct': return_pct
        })
    return trades


def run_backtest(tickers, period="5y", horizon_days=6):
    print("Downloading historical data for backtest (this takes a few minutes)...")
    combined_df = download_watchlist_history(tickers, period)

    rsi_trades = []
    random_trades = []
    np.random.seed(42)

    for ticker in combined_df['ticker'].unique():
        stock_df = combined_df[combined_df['ticker'] == ticker].copy()
        stock_df = add_features(stock_df, horizon=horizon_days)

        # Strategy: enter when RSI < 35 (oversold)
        rsi_trades.extend(simulate_trades(stock_df, lambda r: r['rsi'] < 35, horizon_days))

        # Baseline: enter on random days (same frequency as RSI signals would roughly trigger, ~15% of days)
        random_mask = np.random.random(len(stock_df)) < 0.10
        random_condition = lambda r, mask=random_mask: mask[stock_df.index.get_loc(r.name)] if r.name in stock_df.index else False

    # Simpler random baseline: reuse same loop structure but with random entries
    for ticker in combined_df['ticker'].unique():
        stock_df = combined_df[combined_df['ticker'] == ticker].copy()
        stock_df = add_features(stock_df, horizon=horizon_days).reset_index(drop=True)
        stock_df['random_signal'] = np.random.random(len(stock_df)) < 0.10
        random_trades.extend(simulate_trades(stock_df, lambda r: r['random_signal'], horizon_days))

    return pd.DataFrame(rsi_trades), pd.DataFrame(random_trades)


def summarize(trades_df, label):
    if len(trades_df) == 0:
        print(f"{label}: No trades generated.")
        return

    win_rate = (trades_df['outcome'] == 'target').mean()
    stop_rate = (trades_df['outcome'] == 'stop_loss').mean()
    time_exit_rate = (trades_df['outcome'] == 'time_exit').mean()
    avg_return = trades_df['return_pct'].mean()
    median_return = trades_df['return_pct'].median()

    print(f"\n{'='*50}")
    print(f"{label}")
    print(f"{'='*50}")
    print(f"Total trades: {len(trades_df)}")
    print(f"Hit target: {win_rate:.2%} | Hit stop loss: {stop_rate:.2%} | Time exit: {time_exit_rate:.2%}")
    print(f"Average return per trade: {avg_return:.2f}%")
    print(f"Median return per trade: {median_return:.2f}%")


if __name__ == "__main__":
    rsi_trades, random_trades = run_backtest(WATCHLIST, period="5y", horizon_days=6)
    summarize(rsi_trades, "RSI OVERSOLD STRATEGY (RSI < 35)")
    summarize(random_trades, "RANDOM ENTRY BASELINE (for comparison)")