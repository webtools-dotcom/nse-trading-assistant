import yfinance as yf
import pandas as pd
import numpy as np
from features import add_long_features


def download_watchlist_history(tickers, period="5y"):
    print(f"Downloading {len(tickers)} stocks (batched)...")
    raw = yf.download(tickers, period=period, interval="1d", progress=True, auto_adjust=True, group_by='ticker')

    all_data = []
    for ticker in tickers:
        try:
            stock_df = raw[ticker].copy() if len(tickers) > 1 else raw.copy()
            stock_df = stock_df.reset_index()
            stock_df.columns = [str(c).lower() for c in stock_df.columns]
            stock_df = stock_df.dropna(subset=['close'])
            if len(stock_df) < 260:  # need enough history for 252-day high lookback
                continue
            stock_df['ticker'] = ticker
            all_data.append(stock_df)
        except Exception as e:
            print(f"  Skipped {ticker}: {e}")

    return pd.concat(all_data, ignore_index=True)


def add_features(stock_df, horizon=20):
    """Long-term feature set - validated for 1-2 month horizons via backtest_longterm.py"""
    stock_df = add_long_features(stock_df)
    stock_df['future_close'] = stock_df['close'].shift(-horizon)
    stock_df['target_pct'] = ((stock_df['future_close'] - stock_df['close']) / stock_df['close']) * 100
    return stock_df


def build_training_dataset(tickers, period="5y", horizon=20):
    combined_df = download_watchlist_history(tickers, period)

    feature_dfs = []
    for ticker in combined_df['ticker'].unique():
        stock_df = combined_df[combined_df['ticker'] == ticker].copy()
        stock_df = add_features(stock_df, horizon)
        feature_dfs.append(stock_df)

    full_df = pd.concat(feature_dfs, ignore_index=True)
    full_df = full_df.replace([np.inf, -np.inf], np.nan)
    full_df_clean = full_df.dropna()

    lower_cap = full_df_clean['target_pct'].quantile(0.01)
    upper_cap = full_df_clean['target_pct'].quantile(0.99)
    full_df_clean = full_df_clean.copy()
    full_df_clean['target_pct_capped'] = full_df_clean['target_pct'].clip(lower_cap, upper_cap)

    return full_df_clean


def _row(df, *names):
    """First matching row of a yfinance statement DataFrame as a Series (newest col first), else None."""
    if df is None or getattr(df, 'empty', True):
        return None
    for n in names:
        if n in df.index:
            return df.loc[n].dropna()
    return None


def _statement_fundamentals(stock):
    """ROCE, cash-conversion, and multi-year revenue/PAT trend from the annual statements.
    All best-effort: any missing line item -> None, never raises. yfinance statement columns
    are newest-first. NOTE: these are today's (possibly restated) filings, not point-in-time."""
    out = {'roce_pct': None, 'cash_conversion': None, 'rev_trend': None, 'pat_trend': None,
           'interest_cover': None}
    try:
        inc, bal, cf = stock.income_stmt, stock.balance_sheet, stock.cashflow
    except Exception:
        return out

    ebit = _row(inc, 'EBIT', 'Operating Income')
    assets = _row(bal, 'Total Assets')
    cur_liab = _row(bal, 'Current Liabilities', 'Total Current Liabilities')
    if ebit is not None and assets is not None and cur_liab is not None:
        cap_employed = assets.iloc[0] - cur_liab.iloc[0]
        if cap_employed and cap_employed > 0:
            out['roce_pct'] = round(ebit.iloc[0] / cap_employed * 100, 1)

    # Interest cover, not just D/E: a company can carry heavy debt and service it comfortably,
    # or carry little and still choke on it. This is the number that separates the two.
    interest = _row(inc, 'Interest Expense', 'Interest Expense Non Operating')
    if ebit is not None and interest is not None and interest.iloc[0]:
        out['interest_cover'] = round(ebit.iloc[0] / abs(interest.iloc[0]), 1)

    ocf = _row(cf, 'Operating Cash Flow', 'Total Cash From Operating Activities')
    ni = _row(inc, 'Net Income', 'Net Income Common Stockholders')
    if ocf is not None and ni is not None and ni.iloc[0]:
        out['cash_conversion'] = round(ocf.iloc[0] / ni.iloc[0], 2)

    rev = _row(inc, 'Total Revenue')
    if rev is not None and len(rev) >= 2:
        out['rev_trend'] = [(d.year, float(v)) for d, v in rev.items()]
    if ni is not None and len(ni) >= 2:
        out['pat_trend'] = [(d.year, float(v)) for d, v in ni.items()]
    return out


def get_fundamentals(ticker):
    """Fetches fundamental data via yfinance - free, no separate API needed."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        result = {
            'trailing_pe': info.get('trailingPE'),
            'price_to_book': info.get('priceToBook'),
            'market_cap': info.get('marketCap'),
            'sector': info.get('sector'),
            'industry': info.get('industry'),
            'business_summary': info.get('longBusinessSummary'),
            'profit_margin_pct': round(info.get('profitMargins', 0) * 100, 1) if info.get('profitMargins') else None,
            'revenue_growth_pct': round(info.get('revenueGrowth', 0) * 100, 1) if info.get('revenueGrowth') else None,
            'earnings_growth_pct': round(info.get('earningsGrowth', 0) * 100, 1) if info.get('earningsGrowth') else None,
            'roe_pct': round(info.get('returnOnEquity', 0) * 100, 1) if info.get('returnOnEquity') else None,
            'debt_to_equity': info.get('debtToEquity'),  # yfinance reports this as a PERCENT (82 = 0.82x)
        }
        result.update(_statement_fundamentals(stock))
        return result
    except Exception as e:
        return {'error': str(e)}