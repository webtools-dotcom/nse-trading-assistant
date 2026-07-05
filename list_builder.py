import pandas as pd
import requests
import io

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Referer": "https://www.niftyindices.com/",
}

def fetch_index_list(url):
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    return df

microcap_url = "https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv"
smallcap_url = "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv"

microcap_df = fetch_index_list(microcap_url)
smallcap_df = fetch_index_list(smallcap_url)

print("=== MICROCAP 250 ===")
print(microcap_df.columns.tolist())
print(microcap_df.head())
print("Total:", len(microcap_df))

print("\n=== SMALLCAP 250 ===")
print(smallcap_df.columns.tolist())
print(smallcap_df.head())
print("Total:", len(smallcap_df))

# Combine both lists, tag which index each came from
microcap_df['category'] = 'microcap'
smallcap_df['category'] = 'smallcap'

combined = pd.concat([microcap_df, smallcap_df], ignore_index=True)

# Clean symbol column and add .NS suffix for yfinance compatibility
combined['ticker'] = combined['Symbol'].str.strip() + ".NS"

# Remove any duplicates (a stock could theoretically appear in both indices during transitions)
combined = combined.drop_duplicates(subset='Symbol')

print(f"\nTotal unique stocks across both indices: {len(combined)}")
print("\nSample industries available:")
print(combined['Industry'].value_counts().head(15))

# Save the full list to a file so we don't need to re-fetch every time
combined.to_csv('nse_watchlist_full.csv', index=False)
print("\nSaved full list to nse_watchlist_full.csv")