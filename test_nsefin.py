import nsefin

nse = nsefin.NSEClient()

print("=== INSIDER TRADING ===")
try:
    insider_df = nse.get_insider_trading()
    print(insider_df.columns.tolist())
    print(insider_df.head())
    print("Total rows:", len(insider_df))
except Exception as e:
    print("Error:", e)

print("\n=== UPCOMING RESULTS ===")
try:
    results_df = nse.get_upcoming_results()
    print(results_df.columns.tolist())
    print(results_df.head())
    print("Total rows:", len(results_df))
except Exception as e:
    print("Error:", e)