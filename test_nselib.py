from nselib import capital_market

# Test 1: Delivery data for one stock
df = capital_market.price_volume_and_deliverable_position_data(
    symbol='TATASTEEL',
    from_date='01-06-2026',
    to_date='30-06-2026'
)
print("=== DELIVERY DATA ===")
print(df.columns.tolist())
print(df.head())

# Test 2: Bulk deals across the market for a date range
df2 = capital_market.bulk_deal_data(
    from_date='01-06-2026',
    to_date='30-06-2026'
)
print("\n=== BULK DEALS ===")
print(df2.columns.tolist())
print(df2.head())