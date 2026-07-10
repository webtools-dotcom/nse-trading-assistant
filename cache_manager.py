import pandas as pd
import yfinance as yf
from nselib import capital_market
from datetime import datetime, timedelta
import ta
import pickle
import os
import time
import nsefin

CACHE_DIR = "cache"
PRICE_CACHE_FILE_SHORT = os.path.join(CACHE_DIR, "price_data_short.pkl")
PRICE_CACHE_FILE_LONG = os.path.join(CACHE_DIR, "price_data_long.pkl")
DELIVERY_CACHE_FILE = os.path.join(CACHE_DIR, "delivery_data.pkl")
BULK_DEALS_CACHE_FILE = os.path.join(CACHE_DIR, "bulk_deals_data.pkl")
CACHE_META_FILE = os.path.join(CACHE_DIR, "cache_meta.pkl")
DELIVERY_HISTORY_FILE = os.path.join(CACHE_DIR, "delivery_history.pkl")
RESULTS_CACHE_FILE = os.path.join(CACHE_DIR, "upcoming_results.pkl")
NIFTY_CACHE_FILE = os.path.join(CACHE_DIR, "nifty_data.pkl")
SECTOR_RS_CACHE_FILE = os.path.join(CACHE_DIR, "sector_rs_data.pkl")
MARKET_BREADTH_CACHE_FILE = os.path.join(CACHE_DIR, "market_breadth.pkl")

os.makedirs(CACHE_DIR, exist_ok=True)


def refresh_price_cache_long(tickers):
    print(f"Downloading price data for {len(tickers)} stocks (batched)...")
    raw = yf.download(tickers, period="2y", interval="1d", progress=True, auto_adjust=True, group_by='ticker')

    all_features = {}
    for ticker in tickers:
        try:
            stock_df = raw[ticker].copy() if len(tickers) > 1 else raw.copy()
            stock_df = stock_df.reset_index()
            stock_df.columns = [str(c).lower() for c in stock_df.columns]
            stock_df = stock_df.dropna(subset=['close'])

            if len(stock_df) < 260:
                continue

            stock_df['rsi'] = ta.momentum.RSIIndicator(close=stock_df['close'], window=14).rsi()
            stock_df['sma_50'] = ta.trend.SMAIndicator(close=stock_df['close'], window=50).sma_indicator()
            stock_df['sma_200'] = ta.trend.SMAIndicator(close=stock_df['close'], window=200).sma_indicator()
            stock_df['momentum_60d'] = stock_df['close'].pct_change(60) * 100
            stock_df['dist_from_high_252'] = (stock_df['close'] / stock_df['close'].rolling(252).max()) - 1
            stock_df['volume_change'] = stock_df['volume'].pct_change()
            stock_df['price_change'] = stock_df['close'].pct_change()

            atr_indicator = ta.volatility.AverageTrueRange(high=stock_df['high'], low=stock_df['low'], close=stock_df['close'], window=14)
            stock_df['atr'] = atr_indicator.average_true_range()
            stock_df['atr_pct'] = (stock_df['atr'] / stock_df['close']) * 100

            all_features[ticker] = stock_df
        except Exception as e:
            print(f"  Skipped {ticker}: {e}")

    with open(PRICE_CACHE_FILE_LONG, 'wb') as f:
        pickle.dump(all_features, f)
    print(f"Price cache saved: {len(all_features)} stocks")
    return all_features

def refresh_delivery_cache(trade_date=None):
    """Fetches WHOLE MARKET delivery data in one call, caches it."""
    if trade_date is None:
        trade_date = datetime.now().strftime('%d-%m-%Y')
    print(f"Downloading whole-market delivery data for {trade_date}...")
    try:
        df = capital_market.bhav_copy_with_delivery(trade_date=trade_date)
        with open(DELIVERY_CACHE_FILE, 'wb') as f:
            pickle.dump(df, f)
        print(f"Delivery cache saved: {len(df)} stocks")
        return df
    except Exception as e:
        print(f"Delivery cache failed (market may be closed today/holiday): {e}")
        return None


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


def load_delivery_cache():
    with open(DELIVERY_CACHE_FILE, 'rb') as f:
        return pickle.load(f)


def load_bulk_deals_cache():
    with open(BULK_DEALS_CACHE_FILE, 'rb') as f:
        return pickle.load(f)

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


def update_delivery_history(tickers, keep_days=30):
    """Daily incremental update: adds today, drops oldest, keeps a rolling window."""
    symbols = set(t.replace(".NS", "") for t in tickers)
    today_str = datetime.now().strftime('%d-%m-%Y')

    try:
        df_today = capital_market.bhav_copy_with_delivery(trade_date=today_str)
        df_today = df_today[df_today['SYMBOL'].isin(symbols)].copy()
        df_today['DATE_FETCHED'] = today_str
    except Exception as e:
        print(f"Could not fetch today's delivery data (market closed?): {e}")
        return load_delivery_history() if os.path.exists(DELIVERY_HISTORY_FILE) else None

    if os.path.exists(DELIVERY_HISTORY_FILE):
        with open(DELIVERY_HISTORY_FILE, 'rb') as f:
            history = pickle.load(f)
        history = history[history['DATE_FETCHED'] != today_str]  # avoid duplicate if rerun same day
        history = pd.concat([history, df_today], ignore_index=True)
    else:
        history = df_today

    unique_dates = sorted(history['DATE_FETCHED'].unique(), key=lambda d: datetime.strptime(d, '%d-%m-%Y'))
    if len(unique_dates) > keep_days:
        history = history[history['DATE_FETCHED'].isin(unique_dates[-keep_days:])]

    with open(DELIVERY_HISTORY_FILE, 'wb') as f:
        pickle.dump(history, f)
    print(f"Delivery history updated: {len(history['DATE_FETCHED'].unique())} trading days kept")
    return history


def load_delivery_history():
    with open(DELIVERY_HISTORY_FILE, 'rb') as f:
        return pickle.load(f)

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
    with open(RESULTS_CACHE_FILE, 'rb') as f:
        return pickle.load(f)

def refresh_price_cache_short(tickers):
    print(f"Downloading SHORT-TERM price data for {len(tickers)} stocks...")
    raw = chunked_download(tickers, chunk_size=100, period="6mo", interval="1d", auto_adjust=True)

    all_features = {}
    for ticker in tickers:
        try:
            stock_df = raw[ticker].copy() if len(tickers) > 1 else raw.copy()
            stock_df = stock_df.reset_index()
            stock_df.columns = [str(c).lower() for c in stock_df.columns]
            stock_df = stock_df.dropna(subset=['close'])
            if len(stock_df) < 60:
                continue

            stock_df['rsi'] = ta.momentum.RSIIndicator(close=stock_df['close'], window=14).rsi()
            macd = ta.trend.MACD(close=stock_df['close'])
            stock_df['macd'] = macd.macd()
            stock_df['macd_signal'] = macd.macd_signal()
            stock_df['sma_20'] = ta.trend.SMAIndicator(close=stock_df['close'], window=20).sma_indicator()
            stock_df['sma_50'] = ta.trend.SMAIndicator(close=stock_df['close'], window=50).sma_indicator()
            stock_df['volume_change'] = stock_df['volume'].pct_change()
            stock_df['price_change'] = stock_df['close'].pct_change()
            stock_df['volatility_10'] = stock_df['close'].rolling(10).std()
            stock_df['distance_from_high_50'] = (stock_df['close'] / stock_df['close'].rolling(50).max()) - 1

            atr_indicator = ta.volatility.AverageTrueRange(high=stock_df['high'], low=stock_df['low'], close=stock_df['close'], window=14)
            stock_df['atr'] = atr_indicator.average_true_range()
            stock_df['atr_pct'] = (stock_df['atr'] / stock_df['close']) * 100

            all_features[ticker] = stock_df
        except Exception as e:
            print(f"  Skipped {ticker}: {e}")

    with open(PRICE_CACHE_FILE_SHORT, 'wb') as f:
        pickle.dump(all_features, f)
    print(f"Short-term price cache saved: {len(all_features)} stocks")
    return all_features


def load_price_cache_short():
    with open(PRICE_CACHE_FILE_SHORT, 'rb') as f:
        return pickle.load(f)


def load_price_cache_long():
    with open(PRICE_CACHE_FILE_LONG, 'rb') as f:
        return pickle.load(f)

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
    with open(NIFTY_CACHE_FILE, 'rb') as f:
        return pickle.load(f)

def refresh_sector_relative_strength():
    """Computes each stock's 60-day momentum relative to its own industry peers - 
    catches cases where a stock is just riding a sector-wide rally, not genuinely outperforming."""
    price_cache = load_price_cache_long()
    watchlist_df = pd.read_csv('nse_watchlist_full.csv')
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
    with open(SECTOR_RS_CACHE_FILE, 'rb') as f:
        return pickle.load(f)

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

    nifty_valid = nifty_df.dropna(subset=['sma_200', 'close'])
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
    }

    with open(MARKET_BREADTH_CACHE_FILE, 'wb') as f:
        pickle.dump(data, f)
    print(f"Market breadth cache saved: {breadth_pct}% of stocks above 200SMA, regime={regime}")
    return data


def load_market_breadth_cache():
    with open(MARKET_BREADTH_CACHE_FILE, 'rb') as f:
        return pickle.load(f)

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