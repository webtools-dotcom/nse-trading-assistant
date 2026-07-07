import pandas as pd
import requests
import io
from data_fetcher_long import get_fundamentals

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Referer": "https://www.niftyindices.com/",
}

def fetch_index_list(url):
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return pd.read_csv(io.StringIO(response.text))

print("Fetching Nifty 500 list...")
nifty500_df = fetch_index_list("https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv")
nifty500_df['ticker'] = nifty500_df['Symbol'].str.strip() + ".NS"

# Your existing microcap/smallcap list, already built earlier
existing_df = pd.read_csv('nse_watchlist_full.csv')

combined = pd.concat([
    existing_df[['Company Name', 'Industry', 'Symbol', 'ticker']],
    nifty500_df[['Company Name', 'Industry', 'Symbol', 'ticker']]
], ignore_index=True)
combined = combined.drop_duplicates(subset='Symbol').reset_index(drop=True)

print(f"Total unique combined universe: {len(combined)} stocks")
print("Fetching real market cap for each stock - this is slow (one API call per stock), expect 20-40+ minutes...")

market_caps = []
for i, ticker in enumerate(combined['ticker']):
    try:
        fund = get_fundamentals(ticker)
        mc = fund.get('market_cap')
    except Exception:
        mc = None
    market_caps.append(mc)
    if (i + 1) % 50 == 0:
        print(f"  {i + 1}/{len(combined)} done...")

combined['market_cap'] = market_caps
before_drop = len(combined)
combined = combined.dropna(subset=['market_cap'])
print(f"Dropped {before_drop - len(combined)} stocks with no market cap data available")

combined = combined.sort_values('market_cap', ascending=False).reset_index(drop=True)
combined['cap_rank'] = combined.index + 1

def bucket(rank):
    if rank <= 100:
        return 'Large'
    elif rank <= 250:
        return 'Mid'
    else:
        return 'Small'

combined['cap_bucket'] = combined['cap_rank'].apply(bucket)

combined.to_csv('nse_watchlist_expanded.csv', index=False)
print(f"\nSaved nse_watchlist_expanded.csv: {len(combined)} total stocks")
print("\nBucket breakdown:")
print(combined['cap_bucket'].value_counts())