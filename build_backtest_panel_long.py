"""Build the 5-year LONG-feature panel (cache/backtest_5y_long.pkl) - the long-term twin of
build_backtest_panel.py. Run after build_universe.py whenever the universe changes.

    python build_backtest_panel_long.py          # 5y  -> cache/backtest_5y_long.pkl
    python build_backtest_panel_long.py max      # all Yahoo history -> cache/backtest_max_long.pkl
      (max = TODAY's 748 survivors back in time: survivorship bias flatters old momentum returns)
"""

import pickle
import sys

from config import WATCHLIST
from cache_manager import chunked_download, _retry_missing
from features import add_long_features, MIN_BARS

PERIOD = sys.argv[1] if len(sys.argv) > 1 else "5y"
OUT = f"cache/backtest_{PERIOD}_long.pkl"


def build():
    print(f"Downloading {PERIOD} data for {len(WATCHLIST)} stocks (chunked)...")
    raw = chunked_download(WATCHLIST, chunk_size=100, period=PERIOD, interval="1d", auto_adjust=True)

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
            feat = add_long_features(df)
            feat['ticker'] = ticker
            panel[ticker] = feat
        except Exception:
            missing.append(ticker)

    panel = _retry_missing(missing, panel, add_long_features, "long", period=PERIOD)
    with open(OUT, 'wb') as f:
        pickle.dump(panel, f)
    print(f"Saved {OUT}: {len(panel)}/{len(WATCHLIST)} stocks")
    if panel:
        s = next(iter(panel.values()))
        print(f"  columns: {list(s.columns)}")
        print(f"  history: {s['date'].min().date()} -> {s['date'].max().date()}, ~{len(s)} bars/stock")


if __name__ == "__main__":
    build()