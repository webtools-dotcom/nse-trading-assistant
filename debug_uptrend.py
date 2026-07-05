from data_fetcher import download_watchlist_history, add_features
from config import WATCHLIST
import pandas as pd

print("Downloading a small sample for debugging...")
combined_df = download_watchlist_history(WATCHLIST[:20], period="5y")  # just 20 stocks, faster

total_rsi_oversold = 0
total_uptrend = 0
total_both = 0
total_rows = 0

for ticker in combined_df['ticker'].unique():
    stock_df = combined_df[combined_df['ticker'] == ticker].copy()
    stock_df = add_features(stock_df, horizon=6).reset_index(drop=True)

    valid = stock_df.dropna(subset=['rsi', 'sma_50', 'close'])
    total_rows += len(valid)
    total_rsi_oversold += (valid['rsi'] < 35).sum()
    total_uptrend += (valid['close'] > valid['sma_50']).sum()
    total_both += ((valid['rsi'] < 35) & (valid['close'] > valid['sma_50'])).sum()

print(f"Total valid rows checked: {total_rows}")
print(f"RSI < 35 alone: {total_rsi_oversold}")
print(f"Close > SMA50 alone: {total_uptrend}")
print(f"BOTH conditions together: {total_both}")