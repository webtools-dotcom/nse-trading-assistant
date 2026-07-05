from nselib import capital_market

df = capital_market.bhav_copy_with_delivery(trade_date='02-07-2026')
print(df.columns.tolist())
print(df.head())
print("Total stocks in this file:", len(df))