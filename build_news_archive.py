"""Builds a historical corporate-announcement archive from NSE.

The README has always said news signals "cannot be backtested at all (no historical news
archive)". That turns out to be wrong: NSE's corporate-announcements endpoint accepts arbitrary
from_date/to_date and serves filings from at least two years back. Verified 2024-08, 2026-02,
2026-07 - all return full result sets.

So this pages through history a window at a time and stores every watchlist filing. With the
5-year price panel already cached, event-driven strategies become measurable rather than
matters of opinion.

    python build_news_archive.py                 # default: 2 years back
    python build_news_archive.py --years 3
    python build_news_archive.py --status        # what has been collected so far

Resumable: each window is recorded once fetched, so re-running continues rather than restarts.
Interrupt it freely.
"""

import argparse
import json
import os
import pickle
import sys
import time
from datetime import datetime, timedelta

import requests

from news_watcher import BROWSER_HEADERS, NSE_ANNOUNCEMENTS, NSE_HOME, load_watchlist

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
ARCHIVE_FILE = os.path.join(CACHE_DIR, "news_archive.pkl")
PROGRESS_FILE = os.path.join(CACHE_DIR, "news_archive_progress.json")

WINDOW_DAYS = 5        # NSE truncates very wide ranges; small windows are reliable
SLEEP_SEC = 1.5        # be a good citizen - aggressive scraping gets the IP banned
TEXT_LIMIT = 1500      # attchmntText is the substance, but full text would bloat the archive

# Only these fields are kept. The raw payload has 20 columns of mostly-empty metadata.
KEEP = ('symbol', 'an_dt', 'sort_date', 'desc', 'seq_id', 'smIndustry')


def _load(path, default):
    try:
        if path.endswith('.pkl'):
            with open(path, 'rb') as f:
                return pickle.load(f)
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    os.makedirs(CACHE_DIR, exist_ok=True)
    if path.endswith('.pkl'):
        with open(path, 'wb') as f:
            pickle.dump(obj, f)
    else:
        with open(path, 'w') as f:
            json.dump(obj, f)


def _session():
    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)
    s.get(NSE_HOME, timeout=25)
    s.get(BROWSER_HEADERS['Referer'], timeout=25)
    return s


def fetch_window(s, start, end, symbols):
    r = s.get(NSE_ANNOUNCEMENTS, timeout=60, params={
        'index': 'equities',
        'from_date': start.strftime('%d-%m-%Y'),
        'to_date': end.strftime('%d-%m-%Y')})
    r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else data.get('data', [])
    out = []
    for row in rows:
        sym = (row.get('symbol') or '').strip()
        if sym not in symbols:
            continue
        rec = {k: row.get(k) for k in KEEP}
        rec['attchmntText'] = (row.get('attchmntText') or '')[:TEXT_LIMIT]
        out.append(rec)
    return out


def status():
    archive = _load(ARCHIVE_FILE, {})
    progress = _load(PROGRESS_FILE, {'windows': []})
    if not archive:
        print("No archive yet. Run: python build_news_archive.py")
        return
    dates = sorted({str(r.get('sort_date') or '')[:10] for r in archive.values() if r.get('sort_date')})
    print(f"Archive: {len(archive):,} filings, {len(progress['windows'])} windows fetched")
    if dates:
        print(f"Date range: {dates[0]} -> {dates[-1]}")
    syms = {r['symbol'] for r in archive.values()}
    print(f"Distinct symbols: {len(syms)}")
    print(f"File size: {os.path.getsize(ARCHIVE_FILE)/1e6:.1f} MB")


def build(years=2):
    symbols, _ = load_watchlist()
    archive = _load(ARCHIVE_FILE, {})          # seq_id -> record
    progress = _load(PROGRESS_FILE, {'windows': []})
    done = set(progress['windows'])

    end = datetime.now()
    start = end - timedelta(days=int(years * 365))
    windows = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=WINDOW_DAYS), end)
        windows.append((cur, nxt))
        cur = nxt

    todo = [(a, b) for a, b in windows if f"{a:%Y-%m-%d}_{b:%Y-%m-%d}" not in done]
    print(f"{len(windows)} windows over {years}y | {len(done)} already done | {len(todo)} to fetch")
    print(f"Estimated time: {len(todo) * (SLEEP_SEC + 2) / 60:.0f} min\n")

    s = _session()
    added_total = 0
    for i, (a, b) in enumerate(todo, 1):
        key = f"{a:%Y-%m-%d}_{b:%Y-%m-%d}"
        try:
            rows = fetch_window(s, a, b, symbols)
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {key}: {type(e).__name__} - will retry on next run")
            s = _session()                      # cookies may have gone stale
            time.sleep(5)
            continue

        added = 0
        for rec in rows:
            sid = str(rec.get('seq_id') or '').strip()
            if not sid:
                sid = f"{rec['symbol']}|{rec['an_dt']}|{rec['desc']}"
            if sid not in archive:
                archive[sid] = rec
                added += 1
        added_total += added
        progress['windows'].append(key)
        done.add(key)

        if i % 10 == 0 or i == len(todo):
            _save(ARCHIVE_FILE, archive)
            _save(PROGRESS_FILE, progress)
            print(f"  [{i}/{len(todo)}] {key}: +{added} (archive {len(archive):,}) [saved]")
        else:
            print(f"  [{i}/{len(todo)}] {key}: +{added} (archive {len(archive):,})")
        time.sleep(SLEEP_SEC)

    _save(ARCHIVE_FILE, archive)
    _save(PROGRESS_FILE, progress)
    print(f"\nDone. {len(archive):,} filings total, {added_total:,} new this run.")
    status()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=2)
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        status()
    else:
        build(args.years)
