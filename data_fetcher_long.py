import yfinance as yf
import pandas as pd
import numpy as np
from features import add_long_features


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
            if len(stock_df) < 260:  # need enough history for 252-day high lookback
                continue
            stock_df['ticker'] = ticker
            all_data.append(stock_df)
        except Exception as e:
            print(f"  Skipped {ticker}: {e}")

    return pd.concat(all_data, ignore_index=True)


def add_features(stock_df, horizon=20):
    """Long-term feature set - validated for 1-2 month horizons via backtest_longterm.py"""
    stock_df = add_long_features(stock_df)
    stock_df['future_close'] = stock_df['close'].shift(-horizon)
    stock_df['target_pct'] = ((stock_df['future_close'] - stock_df['close']) / stock_df['close']) * 100
    return stock_df


def build_training_dataset(tickers, period="5y", horizon=20):
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


def get_fundamentals(ticker):
    """Fetches fundamental data via yfinance - free, no separate API needed."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            'trailing_pe': info.get('trailingPE'),
            'price_to_book': info.get('priceToBook'),
            'market_cap': info.get('marketCap'),
            'sector': info.get('sector'),
            'industry': info.get('industry'),
            'business_summary': info.get('longBusinessSummary'),
            'profit_margin_pct': round(info.get('profitMargins', 0) * 100, 1) if info.get('profitMargins') else None,
            'revenue_growth_pct': round(info.get('revenueGrowth', 0) * 100, 1) if info.get('revenueGrowth') else None,
            'earnings_growth_pct': round(info.get('earningsGrowth', 0) * 100, 1) if info.get('earningsGrowth') else None,
            'roe_pct': round(info.get('returnOnEquity', 0) * 100, 1) if info.get('returnOnEquity') else None,
            'debt_to_equity': info.get('debtToEquity'),
        }
    except Exception as e:
        return {'error': str(e)}