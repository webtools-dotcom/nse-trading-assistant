"""Granular industry labels for the whole watchlist, from yfinance.

The existing `Industry` column in nse_watchlist_expanded.csv is NSE's MACRO-economic sector -
20 buckets, so "Capital Goods" holds 113 stocks from cement machinery to shipyards. Useless as a
peer group. yfinance carries a GICS-style `industry` (~145 labels): PARAS is Aerospace & Defense,
STLTECH/HFCL are Communication Equipment, i.e. an actual theme.

Writes cache/industry_map.pkl: {ticker: {'sector':..., 'industry':...}}. Re-run occasionally;
labels almost never change. Existing entries are kept, so a re-run only fills the gaps.

    python build_industry_map.py
"""

import os
import pickle
import time
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

from config import BASE_DIR, WATCHLIST

OUT = os.path.join(BASE_DIR, "cache", "industry_map.pkl")


def fetch(ticker):
    for attempt in range(3):
        try:
            info = yf.Ticker(ticker).info
            ind = info.get('industry')
            if ind:
                return ticker, {'sector': info.get('sector', 'Unknown'), 'industry': ind}
            return ticker, None
        except Exception:
            time.sleep(1.5 * (attempt + 1))   # "delisted" here is usually rate-limiting
    return ticker, None


def run():
    tickers = list(dict.fromkeys(WATCHLIST))
    out = {}
    if os.path.exists(OUT):
        with open(OUT, 'rb') as f:
            out = pickle.load(f)
    todo = [t for t in tickers if t not in out]
    print(f"{len(tickers)} tickers, {len(out)} already mapped, fetching {len(todo)}")

    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for ticker, rec in pool.map(fetch, todo):
            done += 1
            if rec:
                out[ticker] = rec
            if done % 50 == 0:
                print(f"  {done}/{len(todo)} ... {len(out)} mapped")
                with open(OUT, 'wb') as f:      # checkpoint - a rate-limit stall loses nothing
                    pickle.dump(out, f)

    with open(OUT, 'wb') as f:
        pickle.dump(out, f)
    n_ind = len({v['industry'] for v in out.values()})
    missing = [t for t in tickers if t not in out]
    print(f"saved {OUT}: {len(out)}/{len(tickers)} tickers across {n_ind} industries")
    if missing:
        print(f"{len(missing)} unmapped (re-run to retry): {missing[:10]}")


if __name__ == "__main__":
    run()
