import pandas as pd
import numpy as np
from data_fetcher import download_watchlist_history
from config import WATCHLIST
import ta


def add_longterm_features(stock_df):
    stock_df = stock_df.sort_values('date').reset_index(drop=True)
    stock_df['rsi'] = ta.momentum.RSIIndicator(close=stock_df['close'], window=14).rsi()
    stock_df['sma_50'] = ta.trend.SMAIndicator(close=stock_df['close'], window=50).sma_indicator()
    stock_df['sma_200'] = ta.trend.SMAIndicator(close=stock_df['close'], window=200).sma_indicator()
    stock_df['momentum_60d'] = stock_df['close'].pct_change(60) * 100
    stock_df['dist_from_high_252'] = (stock_df['close'] / stock_df['close'].rolling(252).max()) - 1
    stock_df['sma_50_prev'] = stock_df['sma_50'].shift(1)
    stock_df['sma_200_prev'] = stock_df['sma_200'].shift(1)
    stock_df['golden_cross'] = (stock_df['sma_50'] > stock_df['sma_200']) & \
                                (stock_df['sma_50_prev'] <= stock_df['sma_200_prev'])
    return stock_df


STRATEGIES = {
    "RSI < 30 (short-term signal, testing carryover)": lambda r: r['rsi'] < 30,
    "Long-term Uptrend (Price > SMA50 > SMA200)":       lambda r: r['close'] > r['sma_50'] > r['sma_200'],
    "Golden Cross (recent)":                            lambda r: bool(r.get('golden_cross', False)),
    "Positive 60-day Momentum":                         lambda r: r['momentum_60d'] > 5,
    "Near 52-week High (top 10%)":                      lambda r: r['dist_from_high_252'] > -0.10,
}


def simulate_trades_pct(stock_df, entry_condition, horizon_days, stop_pct=0.08, target_pct=0.16):
    """Fixed percentage stop/target - more appropriate for longer holds than daily ATR."""
    trades = []
    for i in range(len(stock_df) - horizon_days - 1):
        row = stock_df.iloc[i]
        if pd.isna(row.get('rsi')) or pd.isna(row.get('sma_200')):
            continue
        try:
            if not entry_condition(row):
                continue
        except Exception:
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
    return {
        'n_trades': n, 'avg_return': avg, 'std_return': std, 'stderr': stderr,
        'risk_adjusted_ratio': avg / std if std > 0 else 0,
        'hit_target_rate': (df['outcome'] == 'target').mean(),
        'stop_rate': (df['outcome'] == 'stop_loss').mean(),
    }


def run_bench(tickers, period, horizon_days, stop_pct, target_pct):
    print(f"\nDownloading data for {horizon_days}-day horizon test...")
    combined_df = download_watchlist_history(tickers, period)

    prepared = {}
    for ticker in combined_df['ticker'].unique():
        stock_df = combined_df[combined_df['ticker'] == ticker].copy()
        stock_df = add_longterm_features(stock_df)
        prepared[ticker] = stock_df

    results = {}
    for name, condition in STRATEGIES.items():
        all_trades = []
        for ticker, stock_df in prepared.items():
            all_trades.extend(simulate_trades_pct(stock_df, condition, horizon_days, stop_pct, target_pct))
        results[name] = compute_stats(all_trades)

    np.random.seed(42)
    random_trades = []
    for ticker, stock_df in prepared.items():
        stock_df = stock_df.copy()
        stock_df['random_signal'] = np.random.random(len(stock_df)) < 0.05
        random_trades.extend(simulate_trades_pct(stock_df, lambda r: r['random_signal'], horizon_days, stop_pct, target_pct))
    results["Random control"] = compute_stats(random_trades)

    return results


def print_leaderboard(results, title):
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
            'Strategy': name, 'Trades': stats['n_trades'],
            'Avg Return %': round(stats['avg_return'], 2),
            'Risk-Adj Ratio': round(stats['risk_adjusted_ratio'], 3),
            'Hit Target %': round(stats['hit_target_rate'] * 100, 1),
            'Hit Stop %': round(stats['stop_rate'] * 100, 1),
            'Edge vs Random': round(edge, 2), 'Z-score': round(z_score, 2),
        })

    leaderboard = pd.DataFrame(rows).sort_values('Risk-Adj Ratio', ascending=False)
    print(f"\n{'='*100}\n{title}\n{'='*100}")
    print(leaderboard.to_string(index=False))
    print("=" * 100)


if __name__ == "__main__":
    results_20 = run_bench(WATCHLIST, period="5y", horizon_days=20, stop_pct=0.08, target_pct=0.16)
    print_leaderboard(results_20, "~1 MONTH HORIZON (20 trading days), Stop -8% / Target +16%")

    results_40 = run_bench(WATCHLIST, period="5y", horizon_days=40, stop_pct=0.10, target_pct=0.20)
    print_leaderboard(results_40, "~2 MONTH HORIZON (40 trading days), Stop -10% / Target +20%")