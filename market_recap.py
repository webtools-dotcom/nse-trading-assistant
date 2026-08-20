"""Pure data-crunching functions for Today's Market Recap.
Input: cached dicts/DataFrames (no Streamlit imports), output: plain lists/dicts.
Display-only: reads already-computed price and metadata caches.
"""

import os
import pandas as pd
from config import BASE_DIR


def load_meta_map():
    """Load company name, sector (Industry), and cap_bucket from nse_watchlist_expanded.csv."""
    path = os.path.join(BASE_DIR, 'nse_watchlist_expanded.csv')
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
        meta = {}
        for _, row in df.iterrows():
            tk = str(row['ticker'])
            meta[tk] = {
                'company': str(row.get('Company Name', '')),
                'sector': str(row.get('Industry', 'Unknown')),
                'cap_bucket': str(row.get('cap_bucket', 'Unknown')),
                'symbol': str(row.get('Symbol', '')),
            }
        return meta
    except Exception:
        return {}


def today_pct(df):
    """Helper: returns today's percentage price move from DataFrame."""
    if df is None or len(df) == 0:
        return 0.0
    if 'price_change' in df.columns:
        val = df['price_change'].iloc[-1]
        if pd.notna(val):
            return float(val) * 100.0
    return 0.0


def _extract_row(ticker, df, meta):
    if df is None or len(df) == 0:
        return None
    m = meta.get(ticker, {}) if meta else {}
    close = float(df['close'].iloc[-1]) if ('close' in df.columns and pd.notna(df['close'].iloc[-1])) else 0.0
    pct = today_pct(df)
    rvol = float(df['rvol'].iloc[-1]) if ('rvol' in df.columns and pd.notna(df['rvol'].iloc[-1])) else 1.0
    return {
        'ticker': ticker,
        'company': m.get('company', ticker.replace('.NS', '')),
        'sector': m.get('sector', 'Unknown'),
        'cap_bucket': m.get('cap_bucket', 'Unknown'),
        'pct': pct,
        'close': close,
        'rvol': rvol,
    }


def top_movers(price_cache, meta, n=15):
    """Returns {'gainers': [...], 'losers': [...]} sorted by today's % move."""
    if not price_cache:
        return {'gainers': [], 'losers': []}

    valid_rows = []
    for ticker, df in price_cache.items():
        if df is None or len(df) == 0:
            continue
        # ponytail: drop low-turnover noise (turnover_60d < 1e7 = Rs 1 cr/day)
        if 'turnover_60d' in df.columns:
            t_val = df['turnover_60d'].iloc[-1]
            if pd.notna(t_val) and t_val < 1e7:
                continue
        row = _extract_row(ticker, df, meta)
        if row:
            valid_rows.append(row)

    gainers = sorted([r for r in valid_rows if r['pct'] > 0], key=lambda x: x['pct'], reverse=True)[:n]
    losers = sorted([r for r in valid_rows if r['pct'] < 0], key=lambda x: x['pct'])[:n]
    return {'gainers': gainers, 'losers': losers}


def most_active(price_cache, meta, n=15):
    """Returns list of rows sorted by today's rvol (relative volume) descending."""
    if not price_cache:
        return []
    valid_rows = []
    for ticker, df in price_cache.items():
        if df is None or len(df) == 0:
            continue
        # ponytail: drop low-turnover noise (turnover_60d < 1e7)
        if 'turnover_60d' in df.columns:
            t_val = df['turnover_60d'].iloc[-1]
            if pd.notna(t_val) and t_val < 1e7:
                continue
        row = _extract_row(ticker, df, meta)
        if row:
            valid_rows.append(row)
    return sorted(valid_rows, key=lambda x: x['rvol'], reverse=True)[:n]


def advance_decline(price_cache):
    """Counts advancing, declining, and unchanged stocks across price_cache."""
    adv, dec, unc = 0, 0, 0
    if not price_cache:
        return {'advancers': 0, 'decliners': 0, 'unchanged': 0}
    for ticker, df in price_cache.items():
        if df is None or len(df) == 0:
            continue
        pct = today_pct(df)
        if pct > 0.0001:
            adv += 1
        elif pct < -0.0001:
            dec += 1
        else:
            unc += 1
    return {'advancers': adv, 'decliners': dec, 'unchanged': unc}


def near_52w(price_cache, meta, n=10):
    """Returns {'near_high': [...], 'near_low': [...]} within ~2% of 252-day high/low."""
    near_high, near_low = [], []
    if not price_cache:
        return {'near_high': [], 'near_low': []}
    for ticker, df in price_cache.items():
        if df is None or len(df) == 0:
            continue
        row = _extract_row(ticker, df, meta)
        if not row:
            continue
        close = row['close']
        if close <= 0:
            continue

        # Distance from 252-day high: (close / max_252) - 1
        if 'dist_from_high_252' in df.columns and pd.notna(df['dist_from_high_252'].iloc[-1]):
            dist_high = float(df['dist_from_high_252'].iloc[-1])
        elif 'close' in df.columns:
            high_252 = df['close'].tail(252).max()
            dist_high = (close / high_252) - 1 if high_252 > 0 else -1.0
        else:
            dist_high = -1.0

        # Distance from 252-day low: (close - min_252) / min_252
        if 'close' in df.columns:
            low_252 = df['close'].tail(252).min()
            dist_low = (close - low_252) / low_252 if low_252 > 0 else 1.0
        else:
            dist_low = 1.0

        # Within ~2% of 252-day high: dist_from_high_252 >= -0.02
        if dist_high >= -0.02:
            r_high = dict(row)
            r_high['dist_pct'] = dist_high * 100.0
            near_high.append(r_high)

        # Within ~2% of 252-day low: dist_low <= 0.02
        if 0 <= dist_low <= 0.02:
            r_low = dict(row)
            r_low['dist_pct'] = dist_low * 100.0
            near_low.append(r_low)

    near_high = sorted(near_high, key=lambda x: x.get('dist_pct', -100), reverse=True)[:n]
    near_low = sorted(near_low, key=lambda x: x.get('dist_pct', 100))[:n]
    return {'near_high': near_high, 'near_low': near_low}


def sector_heatmap(price_cache, meta):
    """Groups tickers by Industry, averages today's pct per sector, sorts descending."""
    if not price_cache:
        return []
    sector_data = {}
    for ticker, df in price_cache.items():
        if df is None or len(df) == 0:
            continue
        m = meta.get(ticker, {}) if meta else {}
        sector = m.get('sector', 'Unknown')
        pct = today_pct(df)
        sector_data.setdefault(sector, []).append(pct)

    out = []
    for sector, pcts in sector_data.items():
        if not pcts:
            continue
        avg_p = sum(pcts) / len(pcts)
        out.append({'sector': sector, 'avg_pct': round(avg_p, 2), 'n': len(pcts)})
    return sorted(out, key=lambda x: x['avg_pct'], reverse=True)


def demo():
    fake_meta = {
        'AAA.NS': {'company': 'Company AAA', 'sector': 'Technology', 'cap_bucket': 'Large'},
        'BBB.NS': {'company': 'Company BBB', 'sector': 'Finance', 'cap_bucket': 'Mid'},
        'CCC.NS': {'company': 'Company CCC', 'sector': 'Technology', 'cap_bucket': 'Small'},
    }
    fake_cache = {
        'AAA.NS': pd.DataFrame({
            'close': [100.0, 105.0],
            'price_change': [0.0, 0.05],
            'rvol': [1.0, 2.5],
            'turnover_60d': [2e7, 2e7],
            'dist_from_high_252': [-0.05, -0.01],
        }),
        'BBB.NS': pd.DataFrame({
            'close': [200.0, 190.0],
            'price_change': [0.0, -0.05],
            'rvol': [1.0, 1.2],
            'turnover_60d': [3e7, 3e7],
            'dist_from_high_252': [-0.10, -0.10],
        }),
        'CCC.NS': pd.DataFrame({
            'close': [50.0, 50.0],
            'price_change': [0.0, 0.0],
            'rvol': [1.0, 0.8],
            'turnover_60d': [1.5e7, 1.5e7],
            'dist_from_high_252': [-0.20, -0.20],
        }),
    }

    movers = top_movers(fake_cache, fake_meta)
    assert len(movers['gainers']) == 1 and movers['gainers'][0]['ticker'] == 'AAA.NS'
    assert len(movers['losers']) == 1 and movers['losers'][0]['ticker'] == 'BBB.NS'

    ad = advance_decline(fake_cache)
    assert ad['advancers'] == 1 and ad['decliners'] == 1 and ad['unchanged'] == 1

    active = most_active(fake_cache, fake_meta)
    assert active[0]['ticker'] == 'AAA.NS'

    n52 = near_52w(fake_cache, fake_meta)
    assert len(n52['near_high']) == 1 and n52['near_high'][0]['ticker'] == 'AAA.NS'

    heat = sector_heatmap(fake_cache, fake_meta)
    assert heat[0]['sector'] == 'Technology' and heat[0]['avg_pct'] == 2.5 and heat[0]['n'] == 2

    print("market_recap self-check OK")


if __name__ == "__main__":
    demo()
