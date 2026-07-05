import json
import pickle
import pandas as pd
import yfinance as yf
from cache_manager import load_sector_rs_cache
from datetime import datetime
from cache_manager import load_market_breadth_cache
from cache_manager import (
    load_price_cache_short, load_price_cache_long, load_delivery_cache, load_bulk_deals_cache,
    get_cache_age, load_delivery_history, load_upcoming_results, load_nifty_cache
)
from data_fetcher_long import get_fundamentals
from config import (
    WATCHLIST, SHORT_FEATURE_COLUMNS, SHORT_MODEL_PATH, SHORT_HORIZON_DAYS,
    LONG_FEATURE_COLUMNS, LONG_MODEL_PATH, LONG_HORIZON_DAYS, LONG_STOP_PCT, LONG_TARGET_PCT
)


def load_model(path):
    with open(path, 'rb') as f:
        return pickle.load(f)

MODEL_SHORT = load_model(SHORT_MODEL_PATH)
MODEL_LONG = load_model(LONG_MODEL_PATH)


def cache_status_note():
    age = get_cache_age()
    if age is None:
        return "WARNING: No cache found - run refresh_cache.py first.\n"
    hours = age.total_seconds() / 3600
    if hours > 20:
        return f"NOTE: Cache is {hours:.1f} hours old - consider running refresh_cache.py for fresher data.\n"
    return ""


def get_news(ticker, max_headlines=3):
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        headlines = []
        for item in news[:max_headlines]:
            title = item.get('content', {}).get('title', 'No title')
            headlines.append(title)
        return headlines
    except Exception as e:
        return [f"News fetch failed: {e}"]


# ============= SHORT-TERM (4-6 day) =============

def get_swing_levels_short(ticker):
    price_cache = load_price_cache_short()
    if ticker not in price_cache:
        raise ValueError(f"{ticker} not found in short-term cache - run refresh_cache.py")

    stock_df = price_cache[ticker].dropna(subset=SHORT_FEATURE_COLUMNS)
    if len(stock_df) == 0:
        raise ValueError(f"{ticker} has no valid rows")

    latest = stock_df.iloc[-1]
    current_price = latest['close']
    atr = latest['atr']

    support = stock_df['low'].tail(20).min()
    resistance = stock_df['high'].tail(20).max()

    stop_loss = current_price - (2 * atr)
    target_1 = current_price + (2 * atr)
    target_2 = current_price + (3.5 * atr)

    X_live = stock_df[SHORT_FEATURE_COLUMNS].iloc[[-1]]
    predicted_move = MODEL_SHORT.predict(X_live)[0]
    volume_spike = latest.get('volume_change', 0) > 0.5

    return {
        'ticker': ticker, 'current_price': round(current_price, 2),
        'atr': round(atr, 2), 'atr_pct': round(latest['atr_pct'], 2),
        'stop_loss': round(stop_loss, 2), 'target': round(target_1, 2),
        'target_2': round(target_2, 2),
        'support_20d': round(support, 2), 'resistance_20d': round(resistance, 2),
        'rsi': round(latest['rsi'], 1), 'volume_spike': bool(volume_spike),
        'model_signal_pct': round(predicted_move, 2),
    }


def get_snapshot_text_short(ticker):
    try:
        levels = get_swing_levels_short(ticker)
        news = get_news(ticker)
        text = cache_status_note()
        text += f"{ticker} Snapshot (4-6 day horizon):\n"
        text += f"Current Price: ₹{levels['current_price']}\n"
        text += f"RSI: {levels['rsi']}\n"
        text += f"Volume spike: {'YES' if levels['volume_spike'] else 'No'}\n"
        text += f"Model signal (weak): {levels['model_signal_pct']}%\n"
        text += f"Stop Loss: ₹{levels['stop_loss']}\n"
        text += f"Target 1: ₹{levels['target']}\n"
        text += f"Target 2: ₹{levels['target_2']}\n"
        text += f"Support: ₹{levels['support_20d']}\n"
        text += f"Resistance: ₹{levels['resistance_20d']}\n"
        text += f"Recent news: {'; '.join(news)}\n"
        return text
    except Exception as e:
        return f"Error fetching data for {ticker}: {e}"


def scan_watchlist_text_short(limit=30, rsi_threshold=30, filter_earnings_decline=True):
    price_cache = load_price_cache_short()
    snapshot_rows = []
    for ticker in price_cache.keys():
        try:
            levels = get_swing_levels_short(ticker)
            if levels['rsi'] < rsi_threshold:
                if filter_earnings_decline:
                    fund = get_fundamentals(ticker)
                    earnings_growth = fund.get('earnings_growth_pct')
                    if earnings_growth is not None and earnings_growth < -20:
                        continue  # skip likely "falling knife" stocks - unvalidated filter, added post-CMSINFO
                snapshot_rows.append(levels)
        except Exception:
            continue

    if len(snapshot_rows) == 0:
        return f"No stocks currently qualify (RSI < {rsi_threshold}, no severe earnings decline). This can happen - not every day has a good setup."

    df = pd.DataFrame(snapshot_rows).sort_values('rsi')
    text = cache_status_note()
    text += f"Short-term scan - RSI < {rsi_threshold} (backtested signal, z-score 8.08), showing up to {limit}:\n\n"
    for _, row in df.head(limit).iterrows():
        spike_flag = " [VOLUME SPIKE]" if row['volume_spike'] else ""
        text += f"{row['ticker']}: Price ₹{row['current_price']}, RSI {row['rsi']}, Model signal {row['model_signal_pct']}%, Stop ₹{row['stop_loss']}, Target ₹{row['target']}{spike_flag}\n"
    return text


# ============= LONG-TERM (1 month) =============

def get_swing_levels_long(ticker):
    price_cache = load_price_cache_long()
    if ticker not in price_cache:
        raise ValueError(f"{ticker} not found in long-term cache - run refresh_cache.py")

    stock_df = price_cache[ticker].dropna(subset=LONG_FEATURE_COLUMNS)
    if len(stock_df) == 0:
        raise ValueError(f"{ticker} has no valid rows")

    latest = stock_df.iloc[-1]
    current_price = latest['close']

    stop_loss = current_price * (1 - LONG_STOP_PCT)
    target = current_price * (1 + LONG_TARGET_PCT)
    support = stock_df['low'].tail(60).min()
    resistance = stock_df['high'].tail(60).max()

    X_live = stock_df[LONG_FEATURE_COLUMNS].iloc[[-1]]
    predicted_move = MODEL_LONG.predict(X_live)[0]

    near_high = latest['dist_from_high_252'] > -0.10
    in_uptrend = current_price > latest['sma_50'] > latest['sma_200']
    extreme_momentum = latest['momentum_60d'] > 60
    
    nifty_df = load_nifty_cache()
    nifty_momentum = nifty_df['momentum_60d'].iloc[-1]
    stock_momentum = latest['momentum_60d']
    relative_strength = stock_momentum - nifty_momentum
    outperforming_market = relative_strength > 0
    try:
        sector_data = load_sector_rs_cache().get(ticker, {})
    except Exception:
        sector_data = {}

    return {
        'ticker': ticker, 'current_price': round(current_price, 2),
        'stop_loss': round(stop_loss, 2), 'target': round(target, 2),
        'support_60d': round(support, 2), 'resistance_60d': round(resistance, 2),
        'rsi': round(latest['rsi'], 1),
        'dist_from_52w_high_pct': round(latest['dist_from_high_252'] * 100, 1),
        'momentum_60d_pct': round(latest['momentum_60d'], 1),
        'near_52w_high': bool(near_high), 'in_uptrend': bool(in_uptrend),
        'validated_setup': bool(near_high and in_uptrend and outperforming_market),
        'extreme_momentum': bool(extreme_momentum),
        'model_signal_pct': round(predicted_move, 2),
        'nifty_momentum_60d_pct': round(nifty_momentum, 1),
        'relative_strength_pct': round(relative_strength, 1),
        'outperforming_market': bool(outperforming_market),
        'industry': sector_data.get('industry', 'Unknown'),
        'sector_avg_momentum_60d': sector_data.get('sector_avg_momentum_60d'),
        'sector_relative_strength': sector_data.get('sector_relative_strength'),
        'outperforming_sector': sector_data.get('outperforming_sector'),
    }


def get_snapshot_text_long(ticker):
    try:
        levels = get_swing_levels_long(ticker)
        news = get_news(ticker)
        text = cache_status_note()
        text += f"{ticker} Snapshot ({LONG_HORIZON_DAYS}-day horizon):\n"
        text += f"Current Price: ₹{levels['current_price']}\n"
        text += f"RSI: {levels['rsi']}\n"
        text += f"CAUTION - Extreme/parabolic move: {'YES - verify with fundamentals' if levels['extreme_momentum'] else 'No'}\n"
        text += f"Distance from 52-week high: {levels['dist_from_52w_high_pct']}%\n"
        text += f"60-day momentum: {levels['momentum_60d_pct']}%\n"
        text += f"Validated setup (near high + uptrend, z-score 9.69): {'YES' if levels['validated_setup'] else 'No'}\n"
        text += f"Model signal (weak): {levels['model_signal_pct']}%\n"
        text += f"Stop Loss (-{LONG_STOP_PCT*100:.0f}%): ₹{levels['stop_loss']}\n"
        text += f"Target (+{LONG_TARGET_PCT*100:.0f}%): ₹{levels['target']}\n"
        text += f"60-day Support: ₹{levels['support_60d']}\n"
        text += f"60-day Resistance: ₹{levels['resistance_60d']}\n"
        text += f"Recent news: {'; '.join(news)}\n"
        text += f"Relative Strength vs Nifty: {levels['relative_strength_pct']}% ({'outperforming' if levels['outperforming_market'] else 'underperforming'} the broader market)\n"
        text += f"Industry: {levels.get('industry', 'Unknown')} | Sector avg 60d momentum: {levels.get('sector_avg_momentum_60d')}% | This stock vs sector: {levels.get('sector_relative_strength')}% ({'outperforming peers' if levels.get('outperforming_sector') else 'in line with or behind peers'})\n"
        return text
    except Exception as e:
        return f"Error fetching data for {ticker}: {e}"

def scan_watchlist_text_long(limit=30, validated_only=True):
    price_cache = load_price_cache_long()
    snapshot_rows = []
    for ticker in price_cache.keys():
        try:
            levels = get_swing_levels_long(ticker)
            if not validated_only or levels['validated_setup']:
                snapshot_rows.append(levels)
        except Exception:
            continue

    if len(snapshot_rows) == 0:
        return "No stocks currently match the validated long-term setup. Try validated_only=false."

    df = pd.DataFrame(snapshot_rows).sort_values('momentum_60d_pct', ascending=False)
    text = cache_status_note()
    text += f"Long-term scan - validated setups (near 52w high + uptrend), showing up to {limit}:\n\n"
    for _, row in df.head(limit).iterrows():
        text += f"{row['ticker']}: Price ₹{row['current_price']}, momentum {row['momentum_60d_pct']}%, Stop ₹{row['stop_loss']}, Target ₹{row['target']}\n"
    return text


def label_debt_to_equity(value):
    if value is None:
        return "N/A"
    if value < 30:
        return "Low"
    elif value < 100:
        return "Moderate"
    else:
        return "High"


def label_roe(value):
    if value is None:
        return "N/A"
    if value > 20:
        return "Strong"
    elif value > 10:
        return "Moderate"
    else:
        return "Weak"


def label_profit_margin(value):
    if value is None:
        return "N/A"
    if value > 20:
        return "Strong"
    elif value > 10:
        return "Moderate"
    else:
        return "Thin"


def get_fundamentals_text(ticker):
    fund = get_fundamentals(ticker)
    if 'error' in fund:
        return f"Fundamentals unavailable for {ticker}: {fund['error']}"
    text = f"{ticker} Fundamentals:\n"
    text += f"Sector: {fund['sector']}, Industry: {fund['industry']}\n"
    if fund.get('business_summary'):
        text += f"Business Description (verified, from company filings): {fund['business_summary']}\n"
    else:
        text += "Business Description: Not available - do not guess or invent what this company does.\n"
    text += f"P/E Ratio: {fund['trailing_pe']}\n" if fund['trailing_pe'] else "P/E Ratio: N/A\n"
    text += f"Revenue Growth (YoY): {fund['revenue_growth_pct']}%\n" if fund['revenue_growth_pct'] is not None else ""
    text += f"Earnings Growth (YoY): {fund['earnings_growth_pct']}%\n" if fund['earnings_growth_pct'] is not None else ""
    text += f"Profit Margin: {fund['profit_margin_pct']}% ({label_profit_margin(fund['profit_margin_pct'])})\n" if fund['profit_margin_pct'] is not None else ""
    text += f"ROE: {fund['roe_pct']}% ({label_roe(fund['roe_pct'])})\n" if fund['roe_pct'] is not None else ""
    text += f"Debt-to-Equity: {fund['debt_to_equity']} ({label_debt_to_equity(fund['debt_to_equity'])} leverage)\n" if fund['debt_to_equity'] is not None else ""
    if fund['trailing_pe'] and fund['trailing_pe'] > 100:
        text += "NOTE: Very high P/E - check if growth genuinely supports this.\n"
    return text
# ============= SHARED =============

def get_institutional_activity_text(ticker):
    symbol = ticker.replace(".NS", "")
    text = cache_status_note()
    text += f"{ticker} Institutional Activity:\n\n"
    try:
        history = load_delivery_history()
        match = history[history['SYMBOL'].str.strip() == symbol].copy()
        match['DELIV_PER'] = pd.to_numeric(match['DELIV_PER'], errors='coerce')
        if len(match) > 0:
            avg_delivery = match['DELIV_PER'].mean()
            latest_delivery = match.sort_values('DATE_FETCHED').iloc[-1]['DELIV_PER']
            trend = "above average" if latest_delivery > avg_delivery else "below average"
            text += f"Delivery %: {latest_delivery:.2f}% latest, {avg_delivery:.2f}% avg over last {len(match)} trading days ({trend})\n\n"
        else:
            text += f"No delivery history found for {symbol}.\n\n"
    except Exception as e:
        text += f"Delivery data unavailable: {e}\n\n"
    try:
        bulk_df = load_bulk_deals_cache()
        matches = bulk_df[bulk_df['Symbol'].str.strip() == symbol]
        if len(matches) == 0:
            text += f"No bulk deals for {symbol} in the cached period.\n"
        else:
            text += f"Recent bulk deals ({len(matches)} found):\n"
            for _, row in matches.head(5).iterrows():
                text += f"  {row['Date']}: {row['ClientName']} {row['Buy/Sell']} {row['QuantityTraded']} shares @ ₹{row['TradePrice/Wght.Avg.Price']}\n"
    except Exception as e:
        text += f"Bulk deal data unavailable: {e}\n"
    return text

def get_market_regime_text():
    """Global market context - not stock-specific. Tells you whether the overall market backdrop currently supports new long exposure."""
    try:
        breadth = load_market_breadth_cache()
        text = f"Market Regime: {breadth['regime']}\n"
        text += f"Breadth: {breadth['breadth_pct_above_200sma']}% of watchlist stocks are above their 200-day average (checked {breadth['stocks_checked']} stocks)\n"
        text += f"Nifty above its own 200-day average: {'Yes' if breadth['nifty_above_200sma'] else 'No'}\n"
        if breadth['regime'] == "Broadly Bearish":
            text += "CAUTION: Broad market conditions are weak - momentum/breakout setups are statistically less reliable in this environment.\n"
        return text
    except Exception as e:
        return f"Market regime data unavailable: {e}"

def check_upcoming_results(ticker):
    symbol = ticker.replace(".NS", "")
    try:
        df = load_upcoming_results()
        match = df[df['symbol'].str.strip() == symbol]
        if len(match) == 0:
            return f"{ticker}: No results/board meeting currently scheduled in NSE's near-term data."
        row = match.iloc[0]
        result_date = datetime.strptime(row['date'], '%d-%b-%Y')
        days_away = (result_date - datetime.now()).days
        return f"{ticker}: Results/board meeting on {row['date']} ({days_away} days away). Purpose: {row['purpose']}.\n"
    except Exception as e:
        return f"Upcoming results data unavailable: {e}"

def parse_bool(value, default=True):
    """Handles cases where the model sends 'True'/'true'/'false' as a string instead of a real boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    return default

def calculate_position_size(ticker, total_capital, risk_pct=1.0, term="short", confirmed=False):
    levels = get_swing_levels_short(ticker) if term == "short" else get_swing_levels_long(ticker)

    if term == "long" and levels.get('extreme_momentum') and not confirmed:
        return {
            'blocked': True,
            'reason': (f"{ticker} is flagged as an extreme/parabolic move (RSI {levels['rsi']}, "
                       f"60-day momentum {levels.get('momentum_60d_pct')}%). Position sizing was NOT calculated. "
                       f"Explicitly ask the user if they want to proceed despite this caution. "
                       f"If they confirm, call this tool again with confirmed=true.")
        }

    if risk_pct > 2.0 and not confirmed:
        return {
            'blocked': True,
            'reason': (f"Requested risk_pct={risk_pct}% exceeds the standard maximum of 2% per trade "
                       f"(normal range is 0.5-2%). Position sizing was NOT calculated. "
                       f"Explicitly ask the user to confirm this risk level before proceeding. "
                       f"If they confirm, call this tool again with confirmed=true.")
        }

    entry_price = levels['current_price']
    stop_loss = levels['stop_loss']
    risk_amount = total_capital * (risk_pct / 100)
    risk_per_share = entry_price - stop_loss
    shares_by_risk = int(risk_amount / risk_per_share)
    shares_by_capital = int(total_capital / entry_price)
    shares_to_buy = min(shares_by_risk, shares_by_capital)
    position_value = shares_to_buy * entry_price
    actual_risk_amount = shares_to_buy * risk_per_share

    return {
        'ticker': ticker, 'term': term, 'entry_price': entry_price, 'stop_loss': stop_loss,
        'risk_per_share': round(risk_per_share, 2), 'total_capital': total_capital, 'risk_pct': risk_pct,
        'shares_to_buy': shares_to_buy, 'position_value': round(position_value, 2),
        'position_pct_of_capital': round((position_value / total_capital) * 100, 2),
        'actual_risk_amount': round(actual_risk_amount, 2),
        'actual_risk_pct': round((actual_risk_amount / total_capital) * 100, 2),
        'target': levels['target'],
        'potential_profit_at_target': round(shares_to_buy * (levels['target'] - entry_price), 2),
    }

def get_full_analysis(ticker, term="short"):
    """Forces the complete checklist every time - snapshot, fundamentals, institutional, results - no inconsistency possible."""
    parts = []
    if term == "long":
        parts.append(get_market_regime_text())
    parts.append(get_snapshot_text_short(ticker) if term == "short" else get_snapshot_text_long(ticker))
    parts.append(get_fundamentals_text(ticker))
    parts.append(get_institutional_activity_text(ticker))
    parts.append(check_upcoming_results(ticker))
    return "\n---\n".join(parts)

TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "get_snapshot_text_short",
        "description": "Detailed 4-6 day swing-trade snapshot for ONE stock: RSI, ATR-based stop/targets, volume spike, model signal, news.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string", "description": "NSE ticker with .NS suffix"}}, "required": ["ticker"]}
    }},
    {"type": "function", "function": {
        "name": "get_snapshot_text_long",
        "description": "Detailed ~1 month position-trade snapshot for ONE stock: momentum, trend, percentage stop/target, extreme-move flag, model signal, news.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string", "description": "NSE ticker with .NS suffix"}}, "required": ["ticker"]}
    }},
    {"type": "function", "function": {
        "name": "get_full_analysis",
        "description": "Runs the COMPLETE checklist for one stock: snapshot, fundamentals, institutional activity, and upcoming results, all at once. ALWAYS use this instead of calling individual tools separately whenever presenting any stock as a candidate or recommendation.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "term": {"type": "string", "enum": ["short", "long"]}}, "required": ["ticker"]}
    }},
    {"type": "function", "function": {
        "name": "scan_watchlist_text_short",
        "description": "Scans watchlist for 4-6 day swing setups. Default RSI<30 (backtested strongest, z-score 8.08).",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}, "rsi_threshold": {"type": "integer"}}}
    }},
    {"type": "function", "function": {
        "name": "scan_watchlist_text_long",
        "description": "Scans watchlist for ~1 month position-trade setups: near 52-week high + confirmed uptrend + outperforming Nifty (momentum strategy). Buy strength, not weakness.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "validated_only": {"type": ["boolean", "string"], "description": "If true (default), only show validated setups. If false, broader unfiltered view."}
            }
        }
    }},
    {"type": "function", "function": {
        "name": "get_fundamentals_text",
        "description": "Fundamental data for ONE stock: P/E, revenue/earnings growth, margins, ROE, debt. Use to check if price strength is backed by real business growth, especially for long-term/momentum picks.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    }},
    {"type": "function", "function": {
        "name": "get_institutional_activity_text",
        "description": "Delivery percentage trend and recent bulk/block deals for ONE stock. Shared by both strategies.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    }},
    {"type": "function", "function": {
        "name": "check_upcoming_results",
        "description": "Checks if a stock has an upcoming quarterly results/board meeting. Shared by both strategies.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    }},
    {"type": "function", "function": {
    "name": "get_market_regime_text",
    "description": "Gets overall market breadth and regime (bullish/bearish/mixed) - NOT stock-specific. Use when asked about general market conditions, or note it's automatically included in get_full_analysis for long-term picks.",
    "parameters": {"type": "object", "properties": {}}
}},
    {"type": "function", "function": {
        "name": "calculate_position_size",
        "description": "Calculates shares to buy given capital and risk %. Will BLOCK and return a warning instead of sizing if risk_pct exceeds 2%, or if the stock has an extreme/parabolic move flag (long-term only) - requires confirmed=true to override after explicitly asking the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"}, "total_capital": {"type": "number"},
                "risk_pct": {"type": "number"}, "term": {"type": "string", "enum": ["short", "long"]},
                "confirmed": {"type": ["boolean", "string"], "description": "Set to true only after the user has explicitly confirmed they want to proceed despite a warning."}
            },
            "required": ["ticker", "total_capital"]
        }
    }},
]


def execute_tool(function_name, function_args):
    if function_name == "get_snapshot_text_short":
        return get_snapshot_text_short(function_args['ticker'])
    elif function_name == "get_snapshot_text_long":
        return get_snapshot_text_long(function_args['ticker'])
    elif function_name == "get_full_analysis":
        return get_full_analysis(function_args['ticker'], function_args.get('term', 'short'))
    elif function_name == "scan_watchlist_text_short":
        return scan_watchlist_text_short(function_args.get('limit', 30), function_args.get('rsi_threshold', 30))
    elif function_name == "scan_watchlist_text_long":
        validated_only = parse_bool(function_args.get('validated_only', True))
        return scan_watchlist_text_long(function_args.get('limit', 30), validated_only)
    elif function_name == "get_fundamentals_text":
        return get_fundamentals_text(function_args['ticker'])
    elif function_name == "get_institutional_activity_text":
        return get_institutional_activity_text(function_args['ticker'])
    elif function_name == "get_market_regime_text":
        return get_market_regime_text()
    elif function_name == "check_upcoming_results":
        return check_upcoming_results(function_args['ticker'])
    elif function_name == "calculate_position_size":
        confirmed = parse_bool(function_args.get('confirmed', False), default=False)
        pos = calculate_position_size(function_args['ticker'], function_args['total_capital'],
                                        function_args.get('risk_pct', 1.0), function_args.get('term', 'short'), confirmed)
        return json.dumps(pos, indent=2)
    return "Unknown function"