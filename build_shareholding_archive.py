"""Builds a historical promoter-shareholding archive from NSE.

NSE's corporate-share-holdings-master endpoint returns the FULL quarterly history for a symbol
in one call (~22 quarters, back to ~2021). Two properties make this worth having, and make it
different from the annual-statement fundamentals in backtest_fundamentals.py:

  - `broadcastDate` is when the filing became public, distinct from the quarter-end `date`.
    Entry can be the next session's open after broadcast - genuinely point-in-time.
  - ~20 quarterly cohorts over 5 years, not the ~4 fiscal cohorts that gut the statistical
    power of any annual-statement factor.

So "did promoter holding rise/fall this quarter" is a dated event, testable with the same
day_clustered_edge machinery as the news event study. That is the point of this archive.

Pledging is NOT historical: corporate-pledgedata serves only the current snapshot. It is
fetched anyway (one extra call per symbol) because it is a useful display field, but it can
never be backtested from this source.

    python build_shareholding_archive.py           # build/resume
    python build_shareholding_archive.py --status  # what has been collected

Resumable: each symbol is recorded once fetched, so re-running continues rather than restarts.
Interrupt it freely.
"""

import argparse
import json
import os
import pickle
import sys
import time

import requests

from build_news_archive import BROWSER_HEADERS, CACHE_DIR, NSE_HOME, _load, _save, load_watchlist

SHP_URL = f"{NSE_HOME}/api/corporate-share-holdings-master"
PLEDGE_URL = f"{NSE_HOME}/api/corporate-pledgedata"
SHP_REFERER = f"{NSE_HOME}/companies-listing/corporate-filings-shareholding-pattern"

ARCHIVE_FILE = os.path.join(CACHE_DIR, "shareholding_archive.pkl")
PLEDGE_FILE = os.path.join(CACHE_DIR, "pledge_snapshot.pkl")
PROGRESS_FILE = os.path.join(CACHE_DIR, "shareholding_progress.json")

SLEEP_SEC = 1.0        # be a good citizen - aggressive scraping gets the IP banned
SAVE_EVERY = 25

# `revisedStatus` is kept because NSE does restate patterns; a backtest must be able to tell a
# revised row from the one that was actually public at broadcastDate.
KEEP = ('date', 'broadcastDate', 'pr_and_prgrp', 'public_val', 'revisedStatus', 'revisedDate')


def _session():
    s = requests.Session()
    s.headers.update({**BROWSER_HEADERS, 'Referer': SHP_REFERER})
    for attempt in range(4):
        try:
            s.get(NSE_HOME, timeout=25)
            s.get(SHP_REFERER, timeout=25)
            return s
        except Exception as e:
            print(f"  session bootstrap retry {attempt + 1}: {e}")
            time.sleep(3)
    raise RuntimeError("could not open an NSE session")


def _get_json(s, url, symbol):
    r = s.get(url, params={'index': 'equities', 'symbol': symbol}, timeout=25)
    r.raise_for_status()
    return r.json()


def fetch_symbol(s, symbol):
    """(history_rows, pledge_row). Either may be empty - not every symbol has filed."""
    rows = []
    for rec in _get_json(s, SHP_URL, symbol) or []:
        if rec.get('date') and rec.get('pr_and_prgrp'):
            rows.append({'symbol': symbol, **{k: rec.get(k) for k in KEEP}})
    pledge = (_get_json(s, PLEDGE_URL, symbol) or {}).get('data') or []
    return rows, (pledge[0] if pledge else None)


def status():
    archive = _load(ARCHIVE_FILE, {})
    done = _load(PROGRESS_FILE, [])
    symbols, _ = load_watchlist()
    quarters = {r['date'] for rows in archive.values() for r in rows}
    print(f"symbols fetched : {len(done)}/{len(symbols)}")
    print(f"symbols with data: {len(archive)}")
    print(f"quarterly rows  : {sum(len(v) for v in archive.values())}")
    print(f"distinct quarters: {len(quarters)}")
    print(f"pledge snapshots : {len(_load(PLEDGE_FILE, {}))}")


def build():
    symbols, _ = load_watchlist()
    archive = _load(ARCHIVE_FILE, {})
    pledges = _load(PLEDGE_FILE, {})
    done = set(_load(PROGRESS_FILE, []))
    todo = sorted(symbols - done)
    print(f"{len(done)} already fetched, {len(todo)} to go")

    s = _session()
    failures = 0
    for i, sym in enumerate(todo, 1):
        try:
            rows, pledge = fetch_symbol(s, sym)
            failures = 0
        except Exception as e:
            failures += 1
            print(f"  {sym}: {e}")
            if failures >= 3:               # cookies go stale mid-run, same as the news archive
                print("  reopening session")
                s = _session()
                failures = 0
            time.sleep(SLEEP_SEC * 2)
            continue
        if rows:
            archive[sym] = rows
        if pledge:
            pledges[sym] = pledge
        done.add(sym)
        if i % SAVE_EVERY == 0:
            _save(ARCHIVE_FILE, archive)
            _save(PLEDGE_FILE, pledges)
            _save(PROGRESS_FILE, sorted(done))
            print(f"  {i}/{len(todo)} - {len(archive)} symbols with history")
        time.sleep(SLEEP_SEC)

    _save(ARCHIVE_FILE, archive)
    _save(PLEDGE_FILE, pledges)
    _save(PROGRESS_FILE, sorted(done))
    print(f"done: {len(archive)} symbols, {sum(len(v) for v in archive.values())} quarterly rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    status() if args.status else build()
