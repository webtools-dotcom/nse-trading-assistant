import yfinance as yf
import pandas as pd
import numpy as np
from features import add_short_features


def download_watchlist_history(tickers, period="5y"):
    print(f"Downloading {len(tickers)} stocks (batched)...")
    raw = yf.download(tickers, period=period, interval="1d", progress=True, auto_adjust=True, group_by='ticker')

    all_data = []
    for ticker in tickers:
        try:
            stock_df = raw[ticker].copy() if len(tickers) > 1 else raw.copy()
            stock_df = stock_df.reset_index()
            stock_df.columns = [str(c).lower() for c in stock_df.columns]
            stock_df = stock_df.dropna(subset=['close'])
            if len(stock_df) < 100:
                continue
            stock_df['ticker'] = ticker
            all_data.append(stock_df)
        except Exception as e:
            print(f"  Skipped {ticker}: {e}")

    return pd.concat(all_data, ignore_index=True)


def add_features(stock_df, horizon=6):
    """Short-term feature set - validated for 4-6 day horizon (RSI<30, z-score 8.08)."""
    stock_df = add_short_features(stock_df)
    stock_df['future_close'] = stock_df['close'].shift(-horizon)
    stock_df['target_pct'] = ((stock_df['future_close'] - stock_df['close']) / stock_df['close']) * 100
    return stock_df


def build_training_dataset(tickers, period="5y", horizon=6):
    combined_df = download_watchlist_history(tickers, period)

    feature_dfs = []
    for ticker in combined_df['ticker'].unique():
        stock_df = combined_df[combined_df['ticker'] == ticker].copy()
        stock_df = add_features(stock_df, horizon)
        feature_dfs.append(stock_df)

    full_df = pd.concat(feature_dfs, ignore_index=True)
    full_df = full_df.replace([np.inf, -np.inf], np.nan)
    full_df_clean = full_df.dropna()

    lower_cap = full_df_clean['target_pct'].quantile(0.01)
    upper_cap = full_df_clean['target_pct'].quantile(0.99)
    full_df_clean = full_df_clean.copy()
    full_df_clean['target_pct_capped'] = full_df_clean['target_pct'].clip(lower_cap, upper_cap)

    return full_df_clean


def get_live_price(ticker):
    """Single, lightweight real-time quote - bypasses the daily-bar cache entirely,
    always reflects the current live price regardless of Yahoo's daily-close finalization lag."""
    try:
        stock = yf.Ticker(ticker)
        price = stock.fast_info.get('last_price')
        if price is None:
            price = stock.info.get('currentPrice') or stock.info.get('regularMarketPrice')
        return price
    except Exception:
        return None