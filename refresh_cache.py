from cache_manager import (
    refresh_price_cache_short, refresh_price_cache_long,
    update_delivery_history, refresh_bulk_deals_cache, refresh_upcoming_results_cache,
    refresh_nifty_cache, refresh_sector_relative_strength, refresh_market_breadth)

from config import WATCHLIST
import pickle
from datetime import datetime
import os

if __name__ == "__main__":
    print(f"Refreshing cache for {len(WATCHLIST)} stocks...")
    refresh_price_cache_short(WATCHLIST)
    refresh_price_cache_long(WATCHLIST)
    refresh_nifty_cache()
    refresh_sector_relative_strength()
    refresh_market_breadth()  
    update_delivery_history(WATCHLIST)
    refresh_bulk_deals_cache()
    refresh_upcoming_results_cache()
    

    os.makedirs("cache", exist_ok=True)
    with open(os.path.join("cache", "cache_meta.pkl"), 'wb') as f:
        pickle.dump({'last_refreshed': datetime.now()}, f)
    print("\nAll caches refreshed successfully!")