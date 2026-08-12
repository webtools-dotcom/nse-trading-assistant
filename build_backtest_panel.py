"""Rebuild the 5-year backtest panel (cache/backtest_5y_short.pkl) for the current universe.

The live caches (refresh_cache.py) only hold ~2y; the backtest scripts need 5y. There was no
committed builder for this file - it was a one-off that got deleted, which is how the panel went
stale when the universe changed. This is that builder, kept so it never goes stale silently again.

Run after build_universe.py whenever the universe changes:
    python build_backtest_panel.py
"""

import pickle

from config import WATCHLIST
from cache_manager import chunked_download, _retry_missing
from features import add_short_features, MIN_BARS

OUT = "cache/backtest_5y_short.pkl"


def build():
    print(f"Downloading 5y SHORT-TERM data for {len(WATCHLIST)} stocks (chunked)...")
    raw = chunked_download(WATCHLIST, chunk_size=100, period="5y", interval="1d", auto_adjust=True)

    panel, missing = {}, []
    for ticker in WATCHLIST:
        try:
            df = raw[ticker].copy() if len(WATCHLIST) > 1 else raw.copy()
            df = df.reset_index()
            df.columns = [str(c).lower() for c in df.columns]
            df = df.dropna(subset=['close'])
            if len(df) < MIN_BARS:
                missing.append(ticker)
                continue
            feat = add_short_features(df)
            feat['ticker'] = ticker          # panel format carries the ticker column
            panel[ticker] = feat
        except Exception:
            missing.append(ticker)

    panel = _retry_missing(missing, panel, add_short_features, "short")  # rate-limit recovery pass

    with open(OUT, 'wb') as f:
        pickle.dump(panel, f)
    print(f"Saved {OUT}: {len(panel)}/{len(WATCHLIST)} stocks")
    if panel:
        s = next(iter(panel.values()))
        print(f"  columns: {list(s.columns)}")
        print(f"  history: {s['date'].min().date()} -> {s['date'].max().date()}, ~{len(s)} bars/stock")


if __name__ == "__main__":
    build()
