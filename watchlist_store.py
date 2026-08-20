"""User Watchlist Storage: persistent JSON store for personal user watchlists.
Pure helper module with no Streamlit dependencies.
"""

import os
import json
from config import BASE_DIR

WATCHLIST_FILE = os.path.join(BASE_DIR, "user_watchlist.json")


def _normalize_ticker(ticker):
    """Normalizes ticker symbol: upper-cased with .NS suffix."""
    sym = str(ticker).strip().upper()
    if not sym:
        return ""
    if not sym.endswith(".NS") and not sym.endswith(".BO"):
        sym = f"{sym}.NS"
    return sym


def load_user_watchlist(file_path=None):
    """Load user watchlist from JSON file. Returns empty list if missing."""
    path = file_path or WATCHLIST_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(t) for t in data if t]
        return []
    except Exception:
        return []


def save_user_watchlist(tickers, file_path=None):
    """Save deduplicated user watchlist to JSON file."""
    path = file_path or WATCHLIST_FILE
    deduped = list(dict.fromkeys(tickers))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    return deduped


def add_to_watchlist(ticker, file_path=None):
    """Add a ticker to user watchlist with normalization and deduping."""
    sym = _normalize_ticker(ticker)
    if not sym:
        return load_user_watchlist(file_path)
    current = load_user_watchlist(file_path)
    if sym not in current:
        current.append(sym)
        save_user_watchlist(current, file_path)
    return current


def remove_from_watchlist(ticker, file_path=None):
    """Remove a ticker from user watchlist."""
    sym = _normalize_ticker(ticker)
    current = load_user_watchlist(file_path)
    updated = [t for t in current if t != sym]
    save_user_watchlist(updated, file_path)
    return updated


def demo():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = tf.name
    try:
        # initially empty
        assert load_user_watchlist(temp_path) == []
        # add ticker with normalization
        res = add_to_watchlist("tcs", temp_path)
        assert "TCS.NS" in res
        # idempotent add
        res2 = add_to_watchlist("TCS.NS", temp_path)
        assert res2.count("TCS.NS") == 1
        # add another
        res3 = add_to_watchlist("INFY", temp_path)
        assert "INFY.NS" in res3 and "TCS.NS" in res3
        # remove
        res4 = remove_from_watchlist("TCS", temp_path)
        assert "TCS.NS" not in res4 and "INFY.NS" in res4
        print("watchlist_store self-check OK")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    demo()
