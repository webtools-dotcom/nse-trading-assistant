import pandas as pd
import yfinance as yf
from nselib import capital_market
from datetime import datetime, timedelta
import ta
import pickle
import os
import time
import nsefin
import logging
from features import add_short_features, add_long_features, MIN_BARS

# yfinance logs a "possibly delisted" line PER ticker on every rate-limit hit -- pure
# noise, since the batch retry pass recovers them. Mute its logger; our own
# "recovered X, still missing Y" prints report the real outcome.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
PRICE_CACHE_FILE_SHORT = os.path.join(CACHE_DIR, "price_data_short.pkl")
PRICE_CACHE_FILE_LONG = os.path.join(CACHE_DIR, "price_data_long.pkl")
BULK_DEALS_CACHE_FILE = os.path.join(CACHE_DIR, "bulk_deals_data.pkl")
CACHE_META_FILE = os.path.join(CACHE_DIR, "cache_meta.pkl")
DELIVERY_HISTORY_FILE = os.path.join(CACHE_DIR, "delivery_history.pkl")
RESULTS_CACHE_FILE = os.path.join(CACHE_DIR, "upcoming_results.pkl")
NIFTY_CACHE_FILE = os.path.join(CACHE_DIR, "nifty_data.pkl")
SECTOR_RS_CACHE_FILE = os.path.join(CACHE_DIR, "sector_rs_data.pkl")
MARKET_BREADTH_CACHE_FILE = os.path.join(CACHE_DIR, "market_breadth.pkl")
CORP_ANNOUNCEMENTS_CACHE_FILE = os.path.join(CACHE_DIR, "corp_announcements.pkl")
VIX_CACHE_FILE = os.path.join(CACHE_DIR, "vix_data.pkl")
CATEGORY_FLOWS_FILE = os.path.join(CACHE_DIR, "category_flows.pkl")

os.makedirs(CACHE_DIR, exist_ok=True)


def _load_pickle(path, what):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{what} cache missing ({os.path.basename(path)}) - run refresh_cache.py")
    with open(path, 'rb') as f:
        return pickle.load(f)


def refresh_price_cache_long(tickers):
    print(f"Downloading LONG-TERM price data for {len(tickers)} stocks...")
    # Must be chunked exactly like the short path. Firing all ~750 tickers at Yahoo in one
    # call gets throttled hard, and yfinance reports throttled tickers as "possibly delisted;
    # no price data found" - which is why SBIN, HINDUNILVR, HCLTECH etc. appeared to vanish.
    raw = chunked_download(tickers, chunk_size=100, period="2y", interval="1d", auto_adjust=True)

    all_features, missing = {}, []
    for ticker in tickers:
        try:
            stock_df = raw[ticker].copy() if len(tickers) > 1 else raw.copy()
            stock_df = stock_df.reset_index()
            stock_df.columns = [str(c).lower() for c in stock_df.columns]
            stock_df = stock_df.dropna(subset=['close'])

            if len(stock_df) < MIN_BARS:
                missing.append(ticker)
                continue

            all_features[ticker] = add_long_features(stock_df)
        except Exception:
            missing.append(ticker)

    all_features = _retry_missing(missing, all_features, add_long_features, "long")
    return _save_price_cache_no_regress(all_features, PRICE_CACHE_FILE_LONG, "long-term")


def _newest_bar_date(all_features):
    """Latest 'date' across a dict of feature frames, or None if empty."""
    dates = [df['date'].iloc[-1] for df in all_features.values() if len(df)]
    return max(dates) if dates else None


def _save_price_cache_no_regress(all_features, cache_file, label):
    """Overwrite the price cache ONLY if the new pull is at least as fresh as what's cached.

    Yahoo posts NSE daily bars late and sometimes serves data a full session behind. A blind
    overwrite lets a stale night-time refresh clobber correct end-of-day prices with older ones
    (the '10pm refresh pulls 2-day-old data' problem). This guard makes refreshes monotonic:
    they can move the newest bar forward or update the current day, never backward.
    ponytail: global newest-date guard; a per-ticker merge would be finer but Yahoo lag is
    systemic (all .NS regress together), so the global check covers the real failure mode.
    """
    new_date = _newest_bar_date(all_features)
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                old = pickle.load(f)
            old_date = _newest_bar_date(old)
        except Exception:
            old_date = None
        if new_date is not None and old_date is not None and new_date < old_date:
            print(f"  KEEPING existing {label} cache: fresh pull is stale "
                  f"(newest {str(new_date)[:10]} < cached {str(old_date)[:10]}). "
                  f"Yahoo likely hasn't posted the latest bar yet - re-run later.")
            return old

    with open(cache_file, 'wb') as f:
        pickle.dump(all_features, f)
    print(f"{label.capitalize()} price cache saved: {len(all_features)} stocks"
          f" (newest bar {str(new_date)[:10]})")
    return all_features


def _retry_missing(missing, all_features, feature_fn, label, chunk_size=25):
    """Second pass over tickers that came back empty.

    Most first-pass failures are throttling, not delisting - a smaller, slower retry usually
    recovers the bulk of them. Anything still missing after this is genuinely unavailable.
    """
    if not missing:
        return all_features
    print(f"  retrying {len(missing)} {label} ticker(s) that returned no data...")
    time.sleep(5)
    try:
        raw = chunked_download(missing, chunk_size=chunk_size, period="2y",
                               interval="1d", auto_adjust=True)
    except Exception as e:
        print(f"  retry failed: {e}")
        return all_features

    recovered = 0
    for ticker in missing:
        try:
            df = raw[ticker].copy() if len(missing) > 1 else raw.copy()
            df = df.reset_index()
            df.columns = [str(c).lower() for c in df.columns]
            df = df.dropna(subset=['close'])
            if len(df) < MIN_BARS:
                continue
            all_features[ticker] = feature_fn(df)
            recovered += 1
        except Exception:
            continue
    still = len(missing) - recovered
    print(f"  recovered {recovered}, still missing {still}"
          + (f" (likely genuinely delisted/suspended)" if still else ""))
    return all_features

def refresh_bulk_deals_cache(days=60):
    """Fetches whole-market bulk deals for the date range, caches it."""
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)
    print(f"Downloading bulk deals from {from_date.date()} to {to_date.date()}...")
    try:
        df = capital_market.bulk_deal_data(
            from_date=from_date.strftime('%d-%m-%Y'),
            to_date=to_date.strftime('%d-%m-%Y')
        )
        df.columns = [c.replace('ï»¿"Symbol"', 'Symbol').replace('"', '').strip() for c in df.columns]
        with open(BULK_DEALS_CACHE_FILE, 'wb') as f:
            pickle.dump(df, f)
        print(f"Bulk deals cache saved: {len(df)} rows")
        return df
    except Exception as e:
        print(f"Bulk deals cache failed: {e}")
        return None


def get_cache_age():
    """Returns how old the cache is, so tools can warn you if it's stale."""
    if not os.path.exists(CACHE_META_FILE):
        return None
    with open(CACHE_META_FILE, 'rb') as f:
        meta = pickle.load(f)
    age = datetime.now() - meta['last_refreshed']
    return age


def newest_short_data_date():
    """Newest bar date across the short price cache - the actual DATA vintage (not file age).
    Yahoo's NSE feed can lag, so a fresh refresh can still hold stale prices; this catches that."""
    cache = load_price_cache_short()
    if not cache:
        return None
    dates = [df['date'].max() for df in cache.values() if len(df)]
    return max(dates) if dates else None


def get_data_date():
    """Newest price-bar date recorded at the last refresh, or None if not recorded yet."""
    if not os.path.exists(CACHE_META_FILE):
        return None
    with open(CACHE_META_FILE, 'rb') as f:
        meta = pickle.load(f)
    return meta.get('newest_data_date')


def load_bulk_deals_cache():
    return _load_pickle(BULK_DEALS_CACHE_FILE, "bulk deals")

def backfill_delivery_history(tickers, target_days=30, max_calendar_days_back=50):
    """One-time backfill: pulls the last ~30 trading days of delivery data. Run this once."""
    symbols = set(t.replace(".NS", "") for t in tickers)
    collected = {}
    current_date = datetime.now()
    checked = 0

    while len(collected) < target_days and checked < max_calendar_days_back:
        date_str = current_date.strftime('%d-%m-%Y')
        try:
            df = capital_market.bhav_copy_with_delivery(trade_date=date_str)
            df_filtered = df[df['SYMBOL'].isin(symbols)].copy()
            if len(df_filtered) > 0:
                df_filtered['DATE_FETCHED'] = date_str
                collected[date_str] = df_filtered
                print(f"  Got {date_str}: {len(df_filtered)} stocks")
        except Exception:
            pass  # weekend/holiday, skip silently
        current_date -= timedelta(days=1)
        checked += 1

    if collected:
        combined = pd.concat(collected.values(), ignore_index=True)
        with open(DELIVERY_HISTORY_FILE, 'wb') as f:
            pickle.dump(combined, f)
        print(f"Delivery history backfilled: {len(collected)} trading days, {len(combined)} rows")
    return collected


def update_delivery_history(tickers, keep_days=30, max_lookback_days=7):
    """Daily incremental update: backfills any missing recent trading day (not just today),
    drops oldest, keeps a rolling window. A single day's fetch failing (late NSE publish,
    weekend, holiday) no longer strands the history behind - the next run fills the gap."""
    symbols = set(t.replace(".NS", "") for t in tickers)

    if os.path.exists(DELIVERY_HISTORY_FILE):
        with open(DELIVERY_HISTORY_FILE, 'rb') as f:
            history = pickle.load(f)
        have_dates = set(history['DATE_FETCHED'].unique())
    else:
        history = None
        have_dates = set()

    fetched = []
    current_date = datetime.now()
    for _ in range(max_lookback_days):
        date_str = current_date.strftime('%d-%m-%Y')
        current_date -= timedelta(days=1)
        if date_str in have_dates:
            continue  # already have it
        try:
            df = capital_market.bhav_copy_with_delivery(trade_date=date_str)
            df = df[df['SYMBOL'].isin(symbols)].copy()
            df['DATE_FETCHED'] = date_str
            if len(df) > 0:
                fetched.append(df)
                print(f"  Delivery data fetched for {date_str}: {len(df)} stocks")
        except Exception:
            pass  # weekend/holiday/not-yet-published, skip silently

    if not fetched:
        print("Could not fetch any new delivery data (weekend/holiday, or NSE not yet published).")
        return history

    frames = ([history] if history is not None else []) + fetched
    history = pd.concat(frames, ignore_index=True)

    unique_dates = sorted(history['DATE_FETCHED'].unique(), key=lambda d: datetime.strptime(d, '%d-%m-%Y'))
    if len(unique_dates) > keep_days:
        history = history[history['DATE_FETCHED'].isin(unique_dates[-keep_days:])]

    with open(DELIVERY_HISTORY_FILE, 'wb') as f:
        pickle.dump(history, f)
    print(f"Delivery history updated: {len(history['DATE_FETCHED'].unique())} trading days kept")
    return history


def load_delivery_history():
    return _load_pickle(DELIVERY_HISTORY_FILE, "delivery history")

def refresh_upcoming_results_cache():
    """Fetches the whole-market upcoming results/board meeting calendar in one call."""
    print("Downloading upcoming results calendar...")
    try:
        nse = nsefin.NSEClient()
        df = nse.get_upcoming_results()
        with open(RESULTS_CACHE_FILE, 'wb') as f:
            pickle.dump(df, f)
        print(f"Upcoming results cache saved: {len(df)} companies")
        return df
    except Exception as e:
        print(f"Upcoming results cache failed: {e}")
        return None


def load_upcoming_results():
    return _load_pickle(RESULTS_CACHE_FILE, "upcoming results")

def refresh_price_cache_short(tickers):
    print(f"Downloading SHORT-TERM price data for {len(tickers)} stocks...")
    raw = chunked_download(tickers, chunk_size=100, period="2y", interval="1d", auto_adjust=True)

    all_features, missing = {}, []
    for ticker in tickers:
        try:
            stock_df = raw[ticker].copy() if len(tickers) > 1 else raw.copy()
            stock_df = stock_df.reset_index()
            stock_df.columns = [str(c).lower() for c in stock_df.columns]
            stock_df = stock_df.dropna(subset=['close'])
            if len(stock_df) < MIN_BARS:
                missing.append(ticker)
                continue

            all_features[ticker] = add_short_features(stock_df)
        except Exception:
            missing.append(ticker)

    all_features = _retry_missing(missing, all_features, add_short_features, "short")
    return _save_price_cache_no_regress(all_features, PRICE_CACHE_FILE_SHORT, "short-term")


def load_price_cache_short():
    return _load_pickle(PRICE_CACHE_FILE_SHORT, "short-term price")


def load_price_cache_long():
    return _load_pickle(PRICE_CACHE_FILE_LONG, "long-term price")

def refresh_nifty_cache():
    """Caches Nifty 50 index data - used to compute relative strength and overall market trend."""
    print("Downloading Nifty index data...")
    df = yf.download("^NSEI", period="2y", interval="1d", progress=False, auto_adjust=True)
    df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    df['momentum_60d'] = df['close'].pct_change(60) * 100
    df['momentum_6d'] = df['close'].pct_change(6) * 100
    df['sma_200'] = ta.trend.SMAIndicator(close=df['close'], window=200).sma_indicator()
    with open(NIFTY_CACHE_FILE, 'wb') as f:
        pickle.dump(df, f)
    print("Nifty cache saved")
    return df

def load_nifty_cache():
    return _load_pickle(NIFTY_CACHE_FILE, "Nifty")

def refresh_sector_relative_strength():
    """Computes each stock's 60-day momentum relative to its own industry peers - 
    catches cases where a stock is just riding a sector-wide rally, not genuinely outperforming."""
    price_cache = load_price_cache_long()
    watchlist_df = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nse_watchlist_expanded.csv'))
    ticker_to_industry = dict(zip(watchlist_df['ticker'], watchlist_df['Industry']))

    ticker_momentum = {}
    for ticker, stock_df in price_cache.items():
        valid = stock_df.dropna(subset=['momentum_60d'])
        if len(valid) == 0:
            continue
        ticker_momentum[ticker] = valid.iloc[-1]['momentum_60d']

    industry_momentums = {}
    for ticker, momentum in ticker_momentum.items():
        industry = ticker_to_industry.get(ticker, 'Unknown')
        industry_momentums.setdefault(industry, []).append(momentum)
    industry_avg = {industry: sum(vals) / len(vals) for industry, vals in industry_momentums.items()}

    sector_rs_data = {}
    for ticker, momentum in ticker_momentum.items():
        industry = ticker_to_industry.get(ticker, 'Unknown')
        sector_avg = industry_avg.get(industry, 0)
        sector_rs_data[ticker] = {
            'industry': industry,
            'stock_momentum_60d': round(momentum, 1),
            'sector_avg_momentum_60d': round(sector_avg, 1),
            'sector_relative_strength': round(momentum - sector_avg, 1),
            'outperforming_sector': bool(momentum > sector_avg),
        }

    with open(SECTOR_RS_CACHE_FILE, 'wb') as f:
        pickle.dump(sector_rs_data, f)
    print(f"Sector RS cache saved: {len(sector_rs_data)} stocks across {len(industry_avg)} industries")
    return sector_rs_data


def load_sector_rs_cache():
    return _load_pickle(SECTOR_RS_CACHE_FILE, "sector relative strength")

def refresh_market_breadth():
    """Computes overall market regime: % of watchlist stocks above their 200-day average (breadth), 
    and whether Nifty itself is above its own 200-day average (broad trend)."""
    price_cache = load_price_cache_long()
    nifty_df = load_nifty_cache()

    above_200_count = 0
    total_count = 0
    for ticker, stock_df in price_cache.items():
        valid = stock_df.dropna(subset=['sma_200', 'close'])
        if len(valid) == 0:
            continue
        latest = valid.iloc[-1]
        total_count += 1
        if latest['close'] > latest['sma_200']:
            above_200_count += 1

    breadth_pct = round((above_200_count / total_count) * 100, 1) if total_count > 0 else None

    # Market-wide volatility percentile within its own trailing year. Mean-reversion needs
    # panic to revert from: measured on 5y, RSI<30 nets -0.81%/trade in the calmest quartile
    # and +1.64% in the most volatile (z=9.27, point-in-time). This is the opposite of the
    # usual "cut risk when vol rises" rule, which is written for trend-following.
    vol_by_date = {}
    for _, stock_df in load_price_cache_short().items():
        for dt, a in zip(stock_df['date'].values, stock_df['atr_pct'].values):
            if pd.notna(a):
                vol_by_date.setdefault(dt, []).append(a)
    mkt_vol_pct = None
    if len(vol_by_date) > 60:
        series = pd.Series({k: sum(v) / len(v) for k, v in vol_by_date.items()}).sort_index()
        window = series.tail(252)
        if len(window) > 60:
            mkt_vol_pct = round(float((window[:-1] < window.iloc[-1]).mean()), 3)

    nifty_valid = nifty_df.dropna(subset=['sma_200', 'close'])
    if len(nifty_valid) == 0:
        return None
    nifty_latest = nifty_valid.iloc[-1]
    nifty_above_200 = bool(nifty_latest['close'] > nifty_latest['sma_200'])

    if breadth_pct is None:
        regime = "Unknown"
    elif breadth_pct > 60 and nifty_above_200:
        regime = "Broadly Bullish"
    elif breadth_pct < 40 and not nifty_above_200:
        regime = "Broadly Bearish"
    else:
        regime = "Mixed/Neutral"

    data = {
        'breadth_pct_above_200sma': breadth_pct,
        'nifty_above_200sma': nifty_above_200,
        'regime': regime,
        'stocks_checked': total_count,
        'market_vol_percentile': mkt_vol_pct,
    }

    with open(MARKET_BREADTH_CACHE_FILE, 'wb') as f:
        pickle.dump(data, f)
    print(f"Market breadth cache saved: {breadth_pct}% of stocks above 200SMA, regime={regime}")
    return data


def load_market_breadth_cache():
    return _load_pickle(MARKET_BREADTH_CACHE_FILE, "market breadth")

def chunked_download(tickers, chunk_size=100, **kwargs):
    """Downloads in smaller batches to avoid Yahoo rate-limiting on very large single requests."""
    all_chunks = []
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        print(f"  Downloading batch {i // chunk_size + 1} ({len(chunk)} stocks)...")
        chunk_df = yf.download(chunk, progress=False, group_by='ticker', **kwargs)
        all_chunks.append(chunk_df)
        time.sleep(2)  # brief pause between batches, reduces rate-limit risk

    combined = pd.concat(all_chunks, axis=1)
    return combined

def refresh_vix_cache():
    """Caches India VIX - the market's own measure of expected volatility/fear."""
    print("Downloading India VIX data...")
    df = None
    for attempt in range(3):  # single ticker, no batch retry pass -> retry here
        df = yf.download("^INDIAVIX", period="6mo", interval="1d", progress=False, auto_adjust=True)
        if not df.empty:
            break
        if attempt < 2:
            time.sleep(5)
    if df is None or df.empty:
        # rate-limited on every attempt: keep the last good cache, don't clobber it
        print("VIX: no data after 3 attempts (rate-limited); keeping existing cache")
        return load_vix_cache()
    df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    with open(VIX_CACHE_FILE, 'wb') as f:
        pickle.dump(df, f)
    print("VIX cache saved")
    return df

def load_vix_cache():
    return _load_pickle(VIX_CACHE_FILE, "VIX")

def refresh_corp_announcements_cache(tickers, days_back=8):  # must exceed DILUTION_LOOKBACK_DAYS (7)
    """Caches recent corporate announcements filtered to the watchlist - whole-market volume is too large to cache in full."""
    nse = nsefin.NSEClient()
    symbols = set(t.replace(".NS", "") for t in tickers)
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days_back)

    print(f"Downloading corporate announcements ({days_back} days)...")
    try:
        df = nse.get_corporate_announcements(
            from_date_str=from_date.strftime('%d-%m-%Y'),
            to_date_str=to_date.strftime('%d-%m-%Y')
        )
        df_filtered = df[df['symbol'].isin(symbols)].copy()
        with open(CORP_ANNOUNCEMENTS_CACHE_FILE, 'wb') as f:
            pickle.dump(df_filtered, f)
        print(f"Corporate announcements cache saved: {len(df_filtered)} rows for watchlist")
        return df_filtered
    except Exception as e:
        print(f"Corporate announcements cache failed: {e}")
        return None

def load_corp_announcements_cache():
    return _load_pickle(CORP_ANNOUNCEMENTS_CACHE_FILE, "corporate announcements")


# NSE changed this file's schema around April 2023. Before that it published only
# BNK / DFI / PRO-TRADES / OTHERS - no FPI or Retail split - so earlier dates are
# useless for flow analysis and are not worth fetching.
CATEGORY_FLOWS_START = "2023-04-01"
_CATEGORY_ALIASES = {'AIFS': 'AIF', 'INSURANCE_COMPANIES': 'INSURANCE', 'BNK': 'BANK'}


def _normalize_flows(df):
    """NSE's category labels drift ('Retail'/'RETAIL', 'AIFs'/'AIF', 'BNK'/'Bank') - fold them
    together, or a query for one category silently misses part of the history."""
    out = pd.DataFrame({
        'date': pd.to_datetime(df['Trade Date'], format='%d-%b-%Y', errors='coerce'),
        'category': (df['Category'].astype(str).str.strip().str.upper()
                     .str.replace(r'[\s\-]+', '_', regex=True)),
        'buy_cr': pd.to_numeric(df['Buy Value in Rs.Crores'], errors='coerce'),
        'sell_cr': pd.to_numeric(df['Sell Value in Rs.Crores'], errors='coerce'),
        'net_cr': pd.to_numeric(df['Net Value in Rs.Crores'], errors='coerce'),
    })
    out['category'] = out['category'].replace(_CATEGORY_ALIASES)
    return out.dropna(subset=['date'])


def _merge_flows(existing, new):
    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=['date', 'category'], keep='last')
    return combined.sort_values(['date', 'category']).reset_index(drop=True)


def update_category_flows(days_back=10, since=None):
    """Appends NSE's category-wise cash turnover: daily net buy/sell in Rs crores per
    participant type (FPI, MUTUAL_FUNDS, INSURANCE, BANK, AIF, PMS, RETAIL, OTHERS).

    This is the closest thing Indian markets publish to a direct retail-vs-institutional
    positioning read. One file per trading day, published with roughly a one-day lag, so
    this walks a date window and fetches whatever is missing. Weekends, holidays and
    not-yet-published days 404 and are skipped.
    """
    try:
        existing = _load_pickle(CATEGORY_FLOWS_FILE, "category flows")
    except FileNotFoundError:
        existing = pd.DataFrame(columns=['date', 'category', 'buy_cr', 'sell_cr', 'net_cr'])

    start = pd.Timestamp(since) if since else pd.Timestamp.today() - pd.Timedelta(days=days_back)
    start = max(start, pd.Timestamp(CATEGORY_FLOWS_START))
    have = set(pd.to_datetime(existing['date'])) if len(existing) else set()
    wanted = [d for d in pd.bdate_range(start, pd.Timestamp.today()) if d not in have]

    print(f"Downloading category flows for {len(wanted)} missing day(s)...")
    fetched, no_file = [], 0
    for d in wanted:
        try:
            raw = capital_market.category_turnover_cash(d.strftime('%d-%m-%Y'))
            fetched.append(_normalize_flows(raw))
        except Exception:
            no_file += 1
        time.sleep(0.3)

    if fetched:
        existing = _merge_flows(existing, pd.concat(fetched, ignore_index=True))
        with open(CATEGORY_FLOWS_FILE, 'wb') as f:
            pickle.dump(existing, f)

    days = existing['date'].nunique() if len(existing) else 0
    print(f"Category flows cache: {len(existing)} rows over {days} trading days "
          f"({no_file} of {len(wanted)} requested day(s) had no file - weekends/holidays/lag)")
    return existing


def load_category_flows():
    return _load_pickle(CATEGORY_FLOWS_FILE, "category flows")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "backfill-flows":
        since = sys.argv[2] if len(sys.argv) > 2 else CATEGORY_FLOWS_START
        update_category_flows(since=since)
    else:
        print("usage: python cache_manager.py backfill-flows [YYYY-MM-DD]")