import pandas as pd
import numpy as np
from data_fetcher import download_watchlist_history, add_features
from config import WATCHLIST


def add_extra_signals(stock_df):
    """Adds derived boolean columns needed for the more complex strategies."""
    stock_df = stock_df.reset_index(drop=True)
    stock_df['macd_prev'] = stock_df['macd'].shift(1)
    stock_df['macd_signal_prev'] = stock_df['macd_signal'].shift(1)
    stock_df['macd_cross_up'] = (stock_df['macd'] > stock_df['macd_signal']) & \
                                 (stock_df['macd_prev'] <= stock_df['macd_signal_prev'])
    return stock_df


STRATEGIES = {
    "RSI < 30 (strict oversold)": lambda r: r['rsi'] < 30,
    "RSI < 35 (baseline)":        lambda r: r['rsi'] < 35,
    "RSI < 40 (loose oversold)":  lambda r: r['rsi'] < 40,
    "RSI < 35 + Long-term Uptrend (SMA100)": lambda r: r['rsi'] < 35 and r['close'] > r['sma_100'],
    "RSI < 35 + Volume Spike":    lambda r: r['rsi'] < 35 and r['volume_change'] > 0.5,
    "MACD Bullish Crossover":     lambda r: bool(r.get('macd_cross_up', False)),
}


def simulate_trades(stock_df, entry_condition, horizon_days=6, stop_atr_mult=2, target_atr_mult=2):
    trades = []
    for i in range(len(stock_df) - horizon_days - 1):
        row = stock_df.iloc[i]
        if pd.isna(row.get('rsi')) or pd.isna(row.get('atr')):
            continue
        try:
            if not entry_condition(row):
                continue
        except Exception:
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
    stderr = std / np.sqrt(n)
    risk_adjusted_ratio = avg / std if std > 0 else 0
    return {
        'n_trades': n,
        'avg_return': avg,
        'median_return': df['return_pct'].median(),
        'std_return': std,
        'stderr': stderr,
        'risk_adjusted_ratio': risk_adjusted_ratio,
        'hit_target_rate': (df['outcome'] == 'target').mean(),
        'stop_rate': (df['outcome'] == 'stop_loss').mean(),
    }

def run_multi_bench(tickers, period="5y", horizon_days=6):
    print("Downloading historical data once for all strategies...")
    combined_df = download_watchlist_history(tickers, period)

    prepared = {}
    for ticker in combined_df['ticker'].unique():
        stock_df = combined_df[combined_df['ticker'] == ticker].copy()
        stock_df = add_features(stock_df, horizon=horizon_days)
        stock_df = add_extra_signals(stock_df)
        prepared[ticker] = stock_df

    results = {}
    for name, condition in STRATEGIES.items():
        print(f"Testing: {name}...")
        all_trades = []
        for ticker, stock_df in prepared.items():
            all_trades.extend(simulate_trades(stock_df, condition, horizon_days))
        results[name] = compute_stats(all_trades)

    # Random control - same as before
    print("Testing: Random control...")
    np.random.seed(42)
    random_trades = []
    for ticker, stock_df in prepared.items():
        stock_df = stock_df.copy()
        stock_df['random_signal'] = np.random.random(len(stock_df)) < 0.10
        random_trades.extend(simulate_trades(stock_df, lambda r: r['random_signal'], horizon_days))
    results["Random control"] = compute_stats(random_trades)

    return results


def print_leaderboard(results):
    random_avg = results["Random control"]['avg_return'] if results.get("Random control") else 0
    random_se = results["Random control"]['stderr'] if results.get("Random control") else 0

    rows = []
    for name, stats in results.items():
        if stats is None:
            continue
        edge = stats['avg_return'] - random_avg
        combined_se = np.sqrt(stats['stderr']**2 + random_se**2)
        z_score = edge / combined_se if combined_se > 0 else 0
        rows.append({
            'Strategy': name,
            'Trades': stats['n_trades'],
            'Avg Return %': round(stats['avg_return'], 2),
            'Std Dev %': round(stats['std_return'], 2),
            'Risk-Adj Ratio': round(stats['risk_adjusted_ratio'], 3),
            'Hit Target %': round(stats['hit_target_rate'] * 100, 1),
            'Hit Stop %': round(stats['stop_rate'] * 100, 1),
            'Edge vs Random': round(edge, 2),
            'Z-score': round(z_score, 2),
        })

    leaderboard = pd.DataFrame(rows).sort_values('Risk-Adj Ratio', ascending=False)
    print("\n" + "=" * 110)
    print("MULTI-SIGNAL BENCH LEADERBOARD (ranked by risk-adjusted ratio)")
    print("=" * 110)
    print(leaderboard.to_string(index=False))
    print("=" * 110)
    print("Risk-Adj Ratio = avg return / std dev of returns per trade (higher = more consistent edge, not just bigger average)")
    print("Z-score above ~2.0 suggests the edge is unlikely to be random chance.")
    print("Z-score below ~2.0 means we can't confidently rule out luck.")


if __name__ == "__main__":
    results = run_multi_bench(WATCHLIST, period="5y", horizon_days=6)
    print_leaderboard(results)