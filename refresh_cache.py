from cache_manager import (
    refresh_price_cache_short, refresh_price_cache_long,
    update_delivery_history, refresh_bulk_deals_cache, refresh_upcoming_results_cache,
    refresh_nifty_cache, refresh_sector_relative_strength, refresh_market_breadth,
    refresh_vix_cache, refresh_corp_announcements_cache, update_category_flows,
    CACHE_DIR, CACHE_META_FILE,
)
from config import WATCHLIST
import pickle
from datetime import datetime

STEPS = [
    ("price_cache_short", lambda: refresh_price_cache_short(WATCHLIST)),
    ("price_cache_long", lambda: refresh_price_cache_long(WATCHLIST)),
    ("nifty", refresh_nifty_cache),
    ("sector_rs", refresh_sector_relative_strength),
    ("market_breadth", refresh_market_breadth),
    ("delivery_history", lambda: update_delivery_history(WATCHLIST)),
    ("bulk_deals", refresh_bulk_deals_cache),
    ("upcoming_results", refresh_upcoming_results_cache),
    ("vix", refresh_vix_cache),
    ("corp_announcements", lambda: refresh_corp_announcements_cache(WATCHLIST)),
    ("category_flows", update_category_flows),
]

MIN_COVERAGE = 0.95  # below this, the universe is too thin to trust a scan


def _ok(result):
    if result is None:
        return False
    if hasattr(result, '__len__'):
        return len(result) > 0
    return True


def _staleness_note(name, result):
    """Flags a step that 'succeeded' by handing back previously-cached data.

    update_delivery_history returns the EXISTING history when today's fetch fails, which is
    non-empty and so passes a truthiness check - the summary printed 'OK: delivery_history'
    directly under 'Could not fetch today's delivery data'. Legitimate on weekends and
    holidays, but the user should be told the data is not current rather than shown a tick.
    """
    if name != 'delivery_history' or not hasattr(result, 'columns'):
        return None
    if 'DATE_FETCHED' not in getattr(result, 'columns', []):
        return None
    try:
        latest = max(datetime.strptime(d, '%d-%m-%Y') for d in result['DATE_FETCHED'].unique())
    except Exception:
        return None
    age_days = (datetime.now() - latest).days
    if age_days <= 1:
        return None
    return (f"  ⚠️  delivery_history: newest data is {latest.date()} ({age_days} days old) - today's "
            f"fetch did not succeed. Normal on weekends/holidays; if it persists on trading days, "
            f"delivery-% and institutional-activity readings are stale.")


def _coverage_note(name, result):
    """Reports how much of the watchlist actually made it into a price cache.

    A price cache that silently comes back 56 stocks short still passes a truthiness check,
    so 'All caches refreshed successfully!' used to print over a materially incomplete
    universe. Yahoo throttling reports missing tickers as 'possibly delisted', so a big
    shortfall almost always means rate-limiting, not real delistings.
    """
    if not name.startswith('price_cache') or not hasattr(result, '__len__'):
        return None
    cov = len(result) / len(WATCHLIST)
    if cov >= MIN_COVERAGE:
        return None
    return (f"  ⚠️  {name}: only {len(result)}/{len(WATCHLIST)} stocks ({cov*100:.1f}%). "
            f"Most 'possibly delisted' messages are Yahoo rate-limiting, not real delistings - "
            f"re-run refresh_cache.py to recover them.")


if __name__ == "__main__":
    print(f"Refreshing cache for {len(WATCHLIST)} stocks...")
    results, notes = {}, []
    for name, step in STEPS:
        try:
            out = step()
            results[name] = _ok(out)
            for note in (_coverage_note(name, out), _staleness_note(name, out)):
                if note:
                    notes.append(note)
        except Exception as e:
            print(f"  {name} FAILED: {e}")
            results[name] = False

    failed = [name for name, ok in results.items() if not ok]
    print("\n--- Refresh summary ---")
    for name, ok in results.items():
        print(f"  {'OK' if ok else 'FAILED'}: {name}")
    for n in notes:
        print(n)

    if results.get("price_cache_short") and results.get("price_cache_long"):
        with open(CACHE_META_FILE, 'wb') as f:
            pickle.dump({'last_refreshed': datetime.now()}, f)
        if failed:
            print(f"\nCache timestamp updated, but {len(failed)} step(s) failed: {', '.join(failed)}")
        elif notes:
            print("\nAll steps ran, but coverage is incomplete - see the warnings above.")
        else:
            print("\nAll caches refreshed successfully!")
    else:
        print("\nPrice cache refresh failed - NOT updating cache timestamp. Stale data would otherwise be reported as fresh.")
