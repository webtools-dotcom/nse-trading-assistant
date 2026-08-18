"""Offline check for the daily market-UI cache (no network).

load_market_ui_cache must return the snapshot on a same-day hit and None on a stale/missing
one, since app.py's market_snapshot()/get_watchlist_quotes() decide live-vs-cached per symbol
based on that return value - a wrong answer here means either stale prices shown as fresh, or
every `streamlit run app.py` start silently going back to a live yfinance call per symbol.
"""
import os
import pickle
from datetime import datetime, timedelta

import cache_manager as cm


def _write(date_str):
    with open(cm.UI_QUOTES_CACHE_FILE, 'wb') as f:
        pickle.dump({"date": date_str, "quotes": {"^NSEI": {"price": 100.0, "chg_pct": 1.0}},
                     "headline": "test"}, f)


def test_missing_file_returns_none():
    if os.path.exists(cm.UI_QUOTES_CACHE_FILE):
        os.remove(cm.UI_QUOTES_CACHE_FILE)
    assert cm.load_market_ui_cache() is None


def test_todays_cache_is_returned():
    _write(datetime.now(cm.IST).strftime("%Y-%m-%d"))
    data = cm.load_market_ui_cache()
    assert data is not None
    assert data["quotes"]["^NSEI"]["price"] == 100.0


def test_stale_cache_returns_none():
    yesterday = (datetime.now(cm.IST) - timedelta(days=1)).strftime("%Y-%m-%d")
    _write(yesterday)
    assert cm.load_market_ui_cache() is None


if __name__ == "__main__":
    test_missing_file_returns_none()
    test_todays_cache_is_returned()
    test_stale_cache_returns_none()
    os.remove(cm.UI_QUOTES_CACHE_FILE)
    print("OK: test_market_ui_cache")
