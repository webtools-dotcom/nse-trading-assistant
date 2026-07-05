import yfinance as yf
import json

ticker = "CUPID.NS"
stock = yf.Ticker(ticker)
info = stock.info

fields_of_interest = [
    'trailingPE', 'forwardPE', 'priceToBook', 'marketCap', 'sector', 'industry',
    'profitMargins', 'revenueGrowth', 'earningsGrowth', 'returnOnEquity',
    'debtToEquity', 'beta', 'trailingEps', 'bookValue', 'dividendYield'
]

print(f"=== {ticker} fundamentals from yfinance ===\n")
for field in fields_of_interest:
    value = info.get(field, 'NOT AVAILABLE')
    print(f"{field}: {value}")