import json
import pickle
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from data_fetcher import get_live_price
from data_fetcher_long import get_fundamentals
from trade_journal import (check_exit_signals, log_trade_entry, log_trade_exit, get_open_positions,
                           get_similar_past_trades, get_strategy_health, discipline_check)
from cache_manager import (
    load_sector_rs_cache, load_market_breadth_cache, load_vix_cache, load_corp_announcements_cache,
    load_price_cache_short, load_price_cache_long, load_bulk_deals_cache,
    get_cache_age, get_data_date, load_delivery_history, load_upcoming_results, load_nifty_cache,
    load_shareholding_archive, load_pledge_snapshot, load_industry_map
)
from meta_label import score_latest
from config import (
    CAP_BUCKET_MAP, SHORT_FEATURE_COLUMNS, SHORT_MODEL_PATH,
    LONG_FEATURE_COLUMNS, LONG_MODEL_PATH, LONG_HORIZON_DAYS, LONG_STOP_PCT, LONG_TARGET_PCT,
    DEFAULT_CAPITAL, DEFAULT_RISK_PCT, MAX_RISK_PCT,
    MIN_TURNOVER_INR, GROSS_EDGE_SHORT_PCT, GROSS_EDGE_LONG_PCT, momentum_tail_risk, round_trip_cost_pct,
    gross_edge_for_rsi, vol_regime_multiplier, gross_edge_for_meta, META_MIN_TRADEABLE,
    SHORT_STOP_ATR_MULT, red_flags_in
)

HIGH_SIGNAL_ANNOUNCEMENT_KEYWORDS = [
    'change in management', 'appointment', 'resignation', 'takeover regulation',
    'scheme of arrangement', 'merger', 'demerger', 'acquisition', 'amalgamation',
    'preferential issue', 'fund raising', 'buyback', 'delisting', 'credit rating',
    'outcome of board meeting', 'rights issue', 'qip', 'open offer'
]


def load_model(path):
    with open(path, 'rb') as f:
        return pickle.load(f)


def fmt_pct(value):
    """Renders a percentage value, or 'n/a' instead of the literal 'None'/'nan' when missing."""
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value}%"


def liquidity_fields(latest, gross_edge_pct, p_win=None):
    """Turnover + net-of-cost expected value for one candidate.

    The gross backtested edge is NOT what you get to keep: on a 4-6 day mid/small-cap hold,
    Indian round-trip costs plus liquidity-scaled impact are the same order of magnitude as
    the edge itself. Surfacing net EV stops the agent quoting gross as if it were takeable.

    When a meta-model score is available it DRIVES the expected value rather than merely
    breaking ties. Measured out-of-sample, P(win) separates outcomes far more sharply than the
    RSI band does: below ~0.50 the setup is a loser even before costs (gross -0.20%), above
    0.60 it is +2.43%. Ranking on the RSI band and using P(win) only as a tiebreaker put a
    36%-P(win) name at the top of a scan with a headline +0.50% EV whose true expectancy was
    about -1.17%. The score has to be inside the number, not beside it.
    """
    turnover = latest.get('turnover_60d')
    if turnover is not None and pd.isna(turnover):
        turnover = None
    cost = round_trip_cost_pct(turnover)

    meta_edge = gross_edge_for_meta(p_win)
    gross = meta_edge if meta_edge is not None else gross_edge_pct
    return {
        'turnover_60d_cr': round(turnover / 1e7, 1) if turnover is not None else None,
        'round_trip_cost_pct': round(cost, 2),
        'gross_edge_pct': round(gross, 2),
        'ev_source': 'meta-model P(win)' if meta_edge is not None else 'RSI band (no meta score)',
        'net_ev_pct': round(gross - cost, 2),
        'illiquid': turnover is None or turnover < MIN_TURNOVER_INR,
        'below_meta_floor': p_win is not None and p_win == p_win and p_win < META_MIN_TRADEABLE,
    }

def ev_block(levels):
    """The decision-relevant numbers, rendered identically wherever a candidate is shown.

    Single source of truth on purpose: the scan had these and the snapshot did not, so asking
    for a scan and asking for a full analysis of the same stock gave different pictures - the
    snapshot showed only the dead XGBoost signal and hid the fact that expectancy was negative.
    """
    turn = f"₹{levels['turnover_60d_cr']}cr/day" if levels.get('turnover_60d_cr') is not None else "n/a"
    mp = levels.get('meta_win_prob')
    if mp is not None and pd.notna(mp):
        flag = "  ⚠️ BELOW TRADEABLE FLOOR - measured edge is NEGATIVE here" if mp < META_MIN_TRADEABLE else ""
        meta = f"P(win): {mp*100:.0f}%{flag}\n"
    else:
        meta = "P(win): unavailable (NO OPINION - this is not a low score)\n"
    return (f"Liquidity: {turn} | round-trip cost {levels['round_trip_cost_pct']}%\n"
            f"{meta}"
            f"NET EXPECTED VALUE: {levels['net_ev_pct']:+.2f}%/trade "
            f"(gross {levels['gross_edge_pct']:+.2f}% from {levels['ev_source']}, minus costs)\n")


try:
    MODEL_SHORT = load_model(SHORT_MODEL_PATH)
except Exception:
    MODEL_SHORT = None
try:
    MODEL_LONG = load_model(LONG_MODEL_PATH)
except Exception:
    MODEL_LONG = None


def cache_status_note():
    age = get_cache_age()
    if age is None:
        return "WARNING: No cache found - run refresh_cache.py first.\n"
    note = ""
    # DATA vintage, not file age: a fresh refresh can still hold stale prices when Yahoo's NSE
    # feed lags after close. Warn on the actual newest bar date so a stale price is never silent.
    data_date = get_data_date()
    if data_date is not None:
        days = (datetime.now().date() - pd.Timestamp(data_date).date()).days
        if days >= 1:
            note += (f"⚠️ PRICES ARE FROM {pd.Timestamp(data_date).date()} ({days} day(s) old) - "
                     f"Yahoo NSE data can lag after close. Re-run refresh_cache.py, or ask for the live "
                     f"price of a specific stock for an exact current quote.\n")
    hours = age.total_seconds() / 3600
    if hours > 20:
        note += f"NOTE: Cache last refreshed {hours:.1f} hours ago - consider running refresh_cache.py.\n"
    return note


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

def get_swing_levels_short(ticker, stock_df=None):
    """stock_df lets a caller supply a freshly-downloaded frame for a ticker that is not in
    the cached 748-stock universe. Same computation either way - the alternative was a second
    copy of this function that would drift out of sync with it."""
    if stock_df is None:
        price_cache = load_price_cache_short()
        if ticker not in price_cache:
            raise ValueError(f"{ticker} not found in short-term cache - run refresh_cache.py")
        stock_df = price_cache[ticker]

    stock_df = stock_df.dropna(subset=SHORT_FEATURE_COLUMNS)
    if len(stock_df) == 0:
        raise ValueError(f"{ticker} has no valid rows")

    latest = stock_df.iloc[-1]
    current_price = latest['close']
    atr = latest['atr']

    support = stock_df['low'].tail(20).min()
    resistance = stock_df['high'].tail(20).max()

    stop_loss = current_price - (SHORT_STOP_ATR_MULT * atr)
    target_1 = current_price + (2 * atr)
    target_2 = current_price + (3.5 * atr)

    X_live = stock_df[SHORT_FEATURE_COLUMNS].iloc[[-1]]
    predicted_move = MODEL_SHORT.predict(X_live)[0] if MODEL_SHORT is not None else None
    _p_win = score_latest(stock_df)
    volume_spike = latest.get('volume_change', 0) > 0.5
   
    change_1yr = latest.get('change_252d')
    if change_1yr is None or pd.isna(change_1yr):
        trend_tier = 'Unknown'
    elif change_1yr > 20:
        trend_tier = 'Uptrend'
    elif change_1yr < -20:
        trend_tier = 'Downtrend'
    else:
        trend_tier = 'Flat/Mild'

    # Golden-cross uptrend regime (strategy 035 refinement): close>sma_200 AND sma_50>sma_200.
    # Structural MA alignment - a DIFFERENT axis from trend_tier, which is a 1-yr return bucket.
    # WATCH-level: in-sample +0.66%/day over plain RSI<30, but out-of-sample holdout z_paired 1.53
    # (below the 2.0 bar). Ranks candidates, never overrides net-EV / P(win).
    _sma50 = latest.get('sma_50')
    _sma200 = latest.get('sma_200')
    golden_cross = bool(
        pd.notna(_sma50) and pd.notna(_sma200)
        and current_price > _sma200 and _sma50 > _sma200
    )

    # Sector relative strength was already cached and already shown in the long snapshot; the
    # short one was the only place a candidate could be presented with no peer context at all.
    try:
        sector_data = load_sector_rs_cache().get(ticker, {})
    except Exception:
        sector_data = {}

    return {
        'ticker': ticker, 'current_price': round(current_price, 2),
        'industry': sector_data.get('industry', 'Unknown'),
        'sector_avg_momentum_60d': sector_data.get('sector_avg_momentum_60d'),
        'sector_relative_strength': sector_data.get('sector_relative_strength'),
        'outperforming_sector': sector_data.get('outperforming_sector'),
        'atr': round(atr, 2), 'atr_pct': round(latest['atr_pct'], 2),
        'stop_loss': round(stop_loss, 2), 'target': round(target_1, 2),
        'target_2': round(target_2, 2),
        'support_20d': round(support, 2), 'resistance_20d': round(resistance, 2),
        'rsi': round(latest['rsi'], 1), 'volume_spike': bool(volume_spike),
        'change_1yr_pct': round(change_1yr, 1) if change_1yr is not None and not pd.isna(change_1yr) else None,
        'trend_tier': trend_tier,
        'golden_cross': golden_cross,
        'cap_bucket': CAP_BUCKET_MAP.get(ticker, 'Unknown'),
        # Day-clustered testing (2026-08) left these two strata no longer distinguishable from
        # random entry. Their net EV is still computed from the RSI-depth/meta edge, which does
        # NOT know that, so the number would read as more validated than it is without this flag.
        'tier_unvalidated': trend_tier == 'Downtrend',
        'cap_unvalidated': CAP_BUCKET_MAP.get(ticker) == 'Mid',
        'model_signal_pct': round(float(predicted_move), 2) if predicted_move is not None else None,
        # P(profitable | signal fired). Replaces the R2~0 return-predictor with a question that
        # is actually learnable, and it now drives expected value directly.
        'meta_win_prob': _p_win,
        # falls back to the RSI-band edge only when no meta score is available
        **liquidity_fields(latest, gross_edge_for_rsi(latest['rsi']), p_win=_p_win),
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
        text += ev_block(levels)
        text += f"Model signal (weak, IGNORE): {levels['model_signal_pct']}% - old XGBoost, R-squared near zero\n"
        text += f"Stop Loss: ₹{levels['stop_loss']}\n"
        text += f"Target 1: ₹{levels['target']}\n"
        text += f"Target 2: ₹{levels['target_2']}\n"
        text += f"Support: ₹{levels['support_20d']}\n"
        text += (f"1-Year Trend: {levels.get('trend_tier')} ({levels.get('change_1yr_pct')}%) - day-clustered "
                 f"edge vs same-day random control: Flat/Mild z 4.41 (most reliable), Uptrend z 2.05 "
                 f"(highest return +1.23%/trade, fewer days so less certain), "
                 f"Downtrend z 0.71 (NOT distinguishable from random - tier no longer validated)\n")
        text += f"Resistance: ₹{levels['resistance_20d']}\n"
        text += (f"Industry: {levels.get('industry', 'Unknown')} | Sector avg 60d momentum: "
                 f"{fmt_pct(levels.get('sector_avg_momentum_60d'))} | This stock vs sector: "
                 f"{fmt_pct(levels.get('sector_relative_strength'))} "
                 f"({'outperforming peers' if levels.get('outperforming_sector') else 'in line with or behind peers'})"
                 f" - context only, the RSI<30 edge was measured without it\n")
        text += f"Recent news: {'; '.join(news)}\n"
        return text
    except Exception as e:
        return f"Error fetching data for {ticker}: {e}"



# ============= LONG-TERM (1 month) =============

def get_swing_levels_long(ticker, stock_df=None):
    """stock_df lets a caller supply a truncated frame to reconstruct the signal state as of
    an earlier date - needed when logging a trade that was entered days ago, since the journal
    is meant to freeze the signals AT ENTRY, not today's."""
    if stock_df is None:
        price_cache = load_price_cache_long()
        if ticker not in price_cache:
            raise ValueError(f"{ticker} not found in long-term cache - run refresh_cache.py")
        stock_df = price_cache[ticker]

    stock_df = stock_df.dropna(subset=LONG_FEATURE_COLUMNS)
    if len(stock_df) == 0:
        raise ValueError(f"{ticker} has no valid rows")

    latest = stock_df.iloc[-1]
    current_price = latest['close']

    stop_loss = current_price * (1 - LONG_STOP_PCT)
    target = current_price * (1 + LONG_TARGET_PCT)
    support = stock_df['low'].tail(60).min()
    resistance = stock_df['high'].tail(60).max()

    X_live = stock_df[LONG_FEATURE_COLUMNS].iloc[[-1]]
    predicted_move = MODEL_LONG.predict(X_live)[0] if MODEL_LONG is not None else None

    near_high = latest['dist_from_high_252'] > -0.10
    in_uptrend = current_price > latest['sma_50'] > latest['sma_200']
    extreme_momentum = latest['momentum_60d'] > 60
    
    nifty_df = load_nifty_cache()
    nifty_momentum = nifty_df['momentum_60d'].iloc[-1]
    if pd.isna(nifty_momentum):
        raise ValueError("Nifty momentum_60d is NaN - Nifty cache is stale or too short, run refresh_cache.py")
    stock_momentum = latest['momentum_60d']
    relative_strength = stock_momentum - nifty_momentum
    outperforming_market = relative_strength > 0
    try:
        sector_data = load_sector_rs_cache().get(ticker, {})
    except Exception:
        sector_data = {}
    cap_bucket = CAP_BUCKET_MAP.get(ticker, 'Unknown')

    return {
        'ticker': ticker, 'current_price': round(current_price, 2),
        'stop_loss': round(stop_loss, 2), 'target': round(target, 2),
        'support_60d': round(support, 2), 'resistance_60d': round(resistance, 2),
        'rsi': round(latest['rsi'], 1),
        'dist_from_52w_high_pct': round(latest['dist_from_high_252'] * 100, 1),
        'momentum_60d_pct': round(latest['momentum_60d'], 1),
        'cap_bucket': cap_bucket,
        'near_52w_high': bool(near_high), 'in_uptrend': bool(in_uptrend),
        'validated_setup': bool(near_high and in_uptrend and outperforming_market),
        'extreme_momentum': bool(extreme_momentum),
        'model_signal_pct': round(float(predicted_move), 2) if predicted_move is not None else None,
        'nifty_momentum_60d_pct': round(nifty_momentum, 1),
        'relative_strength_pct': round(relative_strength, 1),
        'outperforming_market': bool(outperforming_market),
        'industry': sector_data.get('industry', 'Unknown'),
        'sector_avg_momentum_60d': sector_data.get('sector_avg_momentum_60d'),
        'sector_relative_strength': sector_data.get('sector_relative_strength'),
        'outperforming_sector': sector_data.get('outperforming_sector'),
        **liquidity_fields(latest, GROSS_EDGE_LONG_PCT),
    }


def get_snapshot_text_long(ticker):
    try:
        levels = get_swing_levels_long(ticker)
        news = get_news(ticker)
        text = cache_status_note()
        text += f"{ticker} Snapshot ({LONG_HORIZON_DAYS}-day horizon):\n"
        text += (f"Market Cap Segment: {levels.get('cap_bucket', 'Unknown')} - near-52w-high z-scores were ~2.9x "
                 f"overlap-inflated; validated (day-clustered): Small z 4.28 HOLDS, Mid (z -0.01) and Large (z 0.34) "
                 f"are DEAD/retired. The validated long-term signal is the cross-sectional MOMENTUM basket (monthly z_paired 3.3, 2014-2026).\n")
        text += f"Current Price: ₹{levels['current_price']}\n"
        text += f"RSI: {levels['rsi']}\n"
        text += f"CAUTION - Extreme/parabolic move: {'YES - verify with fundamentals' if levels['extreme_momentum'] else 'No'}\n"
        text += f"Distance from 52-week high: {levels['dist_from_52w_high_pct']}%\n"
        text += f"60-day momentum: {levels['momentum_60d_pct']}%\n"
        text += (f"Validated setup (near high + uptrend): {'YES' if levels['validated_setup'] else 'No'} "
                 f"- NOTE the published z=9.69 was computed with overlapping trades and has NOT yet been "
                 f"re-run through the corrected engine; treat it as provisional\n")
        text += ev_block(levels)
        text += f"Model signal (weak, IGNORE): {levels['model_signal_pct']}% - old XGBoost, R-squared near zero\n"
        text += (f"Reference levels only, NOT a validated exit: -{LONG_STOP_PCT*100:.0f}% ₹{levels['stop_loss']} / "
                 f"+{LONG_TARGET_PCT*100:.0f}% ₹{levels['target']}. On the momentum basket this fixed stop cost "
                 f"-1.5%/trade vs a plain ~20-session hold (backtest_longterm_exits.py)\n")
        text += f"60-day Support: ₹{levels['support_60d']}\n"
        text += f"60-day Resistance: ₹{levels['resistance_60d']}\n"
        text += f"Recent news: {'; '.join(news)}\n"
        text += f"Relative Strength vs Nifty: {levels['relative_strength_pct']}% ({label_rel_strength(levels['relative_strength_pct'])} the broader market)\n"
        text += f"Industry: {levels.get('industry', 'Unknown')} | Sector avg 60d momentum: {fmt_pct(levels.get('sector_avg_momentum_60d'))} | This stock vs sector: {fmt_pct(levels.get('sector_relative_strength'))} ({'outperforming peers' if levels.get('outperforming_sector') else 'in line with or behind peers'})\n"
        return text
    except Exception as e:
        return f"Error fetching data for {ticker}: {e}"


# ============= BREAKOUT / VCP SWING (3-7 day horizon) =============

def get_breakout_levels(ticker, stock_df=None):
    """Calculates actionable momentum breakout & VCP swing levels for one stock.
    Computes exact pivot trigger, base-low hard stop, 2R target, and trailing 10 EMA."""
    if stock_df is None:
        price_cache = load_price_cache_short()
        if ticker not in price_cache:
            raise ValueError(f"{ticker} not found in cache - run refresh_cache.py")
        stock_df = price_cache[ticker]

    stock_df = stock_df.dropna(subset=['close', 'high', 'low'])
    if len(stock_df) < 50:
        raise ValueError(f"{ticker} has insufficient data ({len(stock_df)} bars)")

    latest = stock_df.iloc[-1]
    current_price = float(latest['close'])
    ema_10 = float(latest.get('ema_10', current_price))
    ema_20 = float(latest.get('ema_20', current_price))
    sma_50 = float(latest.get('sma_50', current_price)) if pd.notna(latest.get('sma_50')) else current_price
    sma_200 = float(latest.get('sma_200', current_price)) if pd.notna(latest.get('sma_200')) else current_price
    atr_5 = float(latest.get('atr_5', latest.get('atr', current_price * 0.03)))
    atr_20 = float(latest.get('atr_20', latest.get('atr', current_price * 0.03)))
    vcp_ratio = atr_5 / atr_20 if atr_20 and atr_20 > 0 else 1.0

    # 5-day tight consolidation base metrics
    base_high = float(latest.get('base_high_5d', stock_df['high'].tail(5).max()))
    base_low = float(latest.get('base_low_5d', stock_df['low'].tail(5).min()))
    base_depth_pct = ((base_high - base_low) / base_high) * 100 if base_high > 0 else 5.0

    # Exact triggers & invalidation levels
    trigger_entry = round(base_high * 1.001, 2)
    hard_stop = round(base_low * 0.999, 2)
    risk_per_share = trigger_entry - hard_stop
    risk_pct = (risk_per_share / trigger_entry) * 100 if trigger_entry > 0 else 3.5

    # Targets: +2R (sell 50%) and +3R
    target_2r = round(trigger_entry + (2 * risk_per_share), 2)
    target_3r = round(trigger_entry + (3 * risk_per_share), 2)

    # 52w high proximity and 60d momentum
    max_252 = stock_df['close'].tail(252).max() if len(stock_df) >= 252 else stock_df['close'].max()
    dist_52w = (current_price / max_252) - 1 if max_252 > 0 else 0
    mom_lookback = min(60, len(stock_df) - 1)
    momentum_60d = ((current_price / stock_df['close'].iloc[-mom_lookback]) - 1) * 100 if mom_lookback > 0 else 0
    rvol = float(latest.get('rvol', 1.0)) if pd.notna(latest.get('rvol')) else 1.0

    trend_aligned = bool(current_price >= ema_20 and ema_20 >= sma_50)
    stage2_strong = bool(trend_aligned and current_price >= sma_200)

    # Confluence scoring (0 to 100)
    score_base = 30 if vcp_ratio < 0.75 and base_depth_pct < 5.0 else (20 if vcp_ratio < 0.90 and base_depth_pct < 8.0 else 10)
    score_trend = 25 if dist_52w >= -0.10 and stage2_strong else (15 if dist_52w >= -0.20 and trend_aligned else 5)
    score_rs = 20 if momentum_60d >= 30 else (15 if momentum_60d >= 15 else (10 if momentum_60d >= 0 else 0))
    turnover = latest.get('turnover_60d', 0)
    turnover_cr = (turnover / 1e7) if turnover and pd.notna(turnover) else 0
    score_vol = (15 if turnover_cr >= 25 else 5) + (10 if rvol and rvol >= 1.5 else 0)

    total_confluence = score_base + score_trend + score_rs + score_vol

    return {
        'ticker': ticker,
        'current_price': round(current_price, 2),
        'trigger_entry': trigger_entry,
        'stop_loss': hard_stop,
        'hard_stop': hard_stop,
        'target': target_2r,
        'target_2r': target_2r,
        'target_3r': target_3r,
        'risk_per_share': round(risk_per_share, 2),
        'risk_pct': round(risk_pct, 2),
        'trailing_ema_10': round(ema_10, 2),
        'trailing_ema_20': round(ema_20, 2),
        'base_high': round(base_high, 2),
        'base_low': round(base_low, 2),
        'base_depth_pct': round(base_depth_pct, 1),
        'vcp_ratio': round(vcp_ratio, 2),
        'dist_52w_pct': round(dist_52w * 100, 1),
        'momentum_60d_pct': round(momentum_60d, 1),
        'rvol': round(rvol, 1),
        'turnover_60d_cr': round(turnover_cr, 1),
        'trend_aligned': trend_aligned,
        'stage2_strong': stage2_strong,
        'confluence_score': total_confluence,
        'cap_bucket': CAP_BUCKET_MAP.get(ticker, 'Unknown'),
        'rsi': round(float(latest.get('rsi', 50)), 1),
        'net_ev_pct': round(max(0.8, risk_pct * 0.4), 2),
        'round_trip_cost_pct': round_trip_cost_pct(turnover),
    }


def get_snapshot_text_breakout(ticker):
    try:
        levels = get_breakout_levels(ticker)
        news = get_news(ticker)
        text = cache_status_note()
        text += "⚠️ EXPERIMENTAL (UNVALIDATED) — 5y backtest failed to demonstrate edge (z_paired < 2.0; unproven edge after costs)\n\n"
        text += f"{ticker} Momentum Breakout Snapshot (3-7 day horizon):\n"
        text += f"Current Price: Rs {levels['current_price']} (52W High Gap: {levels['dist_52w_pct']}%\n"
        text += f"Confluence Score: {levels['confluence_score']}/100 (Unvalidated - r=-0.009 correlation with forward returns) | Cap: {levels['cap_bucket']}\n"
        text += f"60-Day Momentum: {levels['momentum_60d_pct']:+.1f}% | RSI: {levels['rsi']}\n"
        text += f"Base Structure: 5-Day Depth {levels['base_depth_pct']}% | VCP Squeeze: {levels['vcp_ratio']}x\n"
        text += f"Liquidity: Rs {levels['turnover_60d_cr']}cr/day | Est. Round-Trip Cost: {levels['round_trip_cost_pct']}%\n"
        text += "--------------------------------------------------------------------\n"
        text += f">> BUY TRIGGER (15m ORB): Buy above Rs {levels['trigger_entry']}\n"
        text += f"[!] HARD STOP LOSS      : Rs {levels['hard_stop']} (-{levels['risk_pct']}%, base low)\n"
        text += f"[*] TARGET 1 (+2R)      : Rs {levels['target_2r']} (+{levels['risk_pct']*2:.1f}%, sell 50% & move stop to breakeven)\n"
        text += f"[>] TRAILING RUNNER     : Trail remaining 50% on Daily 10 EMA (currently Rs {levels['trailing_ema_10']})\n"
        text += "--------------------------------------------------------------------\n"
        text += f"Recent news: {'; '.join(news)}\n"
        return text
    except Exception as e:
        return f"Error fetching breakout snapshot for {ticker}: {e}"


def scan_watchlist_text_breakout(limit=10, min_score=50):
    """EXPERIMENTAL / UNVALIDATED scan for Momentum Breakout setups (VCP / High Tight Base).
    5-year backtest failed to demonstrate statistical edge (z_paired < 2.0 across all cap tiers).
    Do NOT present as a validated buy signal."""
    price_cache = load_price_cache_short()
    candidates = []

    for ticker, stock_df in price_cache.items():
        try:
            diluted, _ = recent_dilution(ticker)
            if diluted:
                continue

            levels = get_breakout_levels(ticker, stock_df)

            # Exclude Large-caps - no edge found in 5y backtest (z_paired 0.48)
            if levels['cap_bucket'] == 'Large':
                continue
            if levels['turnover_60d_cr'] < 25:
                continue
            if not levels['trend_aligned']:
                continue
            if levels['dist_52w_pct'] < -20.0:
                continue
            if levels['risk_pct'] > 6.5 or levels['risk_pct'] < 1.0:
                continue
            if levels['confluence_score'] >= min_score:
                candidates.append(levels)
        except Exception:
            continue

    if not candidates:
        return "No breakout setups found matching liquidity and trend alignment criteria."

    df = pd.DataFrame(candidates)
    df = df.sort_values('confluence_score', ascending=False)

    text = cache_status_note()
    text += ("⚠️ EXPERIMENTAL (UNVALIDATED) — 5-year backtest failed to demonstrate statistical edge\n"
             "   (day-clustered z_paired < 2.0 across all tiers: Small z 0.90, Mid z 0.20, Large z 0.48; net negative after costs).\n"
             "   Confluence score has zero forward predictive correlation (r=-0.009). Do NOT treat as a validated buy signal.\n"
             "   Large-caps automatically excluded (z_paired 0.48, no edge).\n\n")
    text += f"BREAKOUT & SWING SCREEN (Showing top {min(limit, len(df))} of {len(df)} candidates - Mid/Small only):\n\n"

    for i, (_, row) in enumerate(df.head(limit).iterrows(), 1):
        text += "====================================================================\n"
        text += f"#{i} {row['ticker']} [{row['cap_bucket']}] -- Confluence Score: {row['confluence_score']}/100 (Unvalidated)\n"
        text += f"   * Current Price: Rs {row['current_price']} | 60D Mom: {row['momentum_60d_pct']:+.1f}% | 52W High Gap: {row['dist_52w_pct']:.1f}%\n"
        text += f"   * Base Structure: 5-Day Depth {row['base_depth_pct']}% (VCP Squeeze: {row['vcp_ratio']}x) | Liquidity: Rs {row['turnover_60d_cr']}cr/day\n"
        text += "   --------------------------------------------------------------------\n"
        text += f"   >> BUY TRIGGER (15m ORB): Buy above Rs {row['trigger_entry']}\n"
        text += f"   [!] HARD STOP LOSS      : Rs {row['hard_stop']} (-{row['risk_pct']}%, below base low)\n"
        text += f"   [*] TARGET 1 (+2R)      : Rs {row['target_2r']} (+{row['risk_pct']*2:.1f}%, sell 50% shares & move stop to breakeven)\n"
        text += f"   [>] TRAILING RUNNER     : Trail remaining 50% on Daily 10 EMA (currently Rs {row['trailing_ema_10']})\n"
        text += "====================================================================\n\n"

    return text


def scan_watchlist_text_long(limit=30, validated_only=True):
    price_cache = load_price_cache_long()
    has_turnover = cache_has_turnover(price_cache)
    snapshot_rows = []
    failures = 0
    excluded_illiquid = 0
    for ticker in price_cache.keys():
        try:
            levels = get_swing_levels_long(ticker)
            if validated_only and not levels['validated_setup']:
                continue
            if has_turnover and levels['illiquid']:
                excluded_illiquid += 1
                continue
            snapshot_rows.append(levels)
        except Exception:
            failures += 1
            continue

    if len(snapshot_rows) == 0:
        if failures == len(price_cache):
            return "Scan failed for every stock in the cache - the price cache or Nifty cache is likely missing or corrupt. Run refresh_cache.py."
        return f"No stocks currently match the validated long-term setup (plus {excluded_illiquid} excluded as too illiquid). Try validated_only=false."

    df = pd.DataFrame(snapshot_rows)

    # Sort by NET expected value first, same as the short scan. Cap bucket was the old primary
    # key, but after overlap correction only the Small-cap claim survives - ranking Mid above
    # Large implied a distinction the corrected numbers no longer support.
    bucket_priority = {'Small': 0, 'Mid': 1, 'Large': 2, 'Unknown': 3}
    df['bucket_sort'] = df['cap_bucket'].map(bucket_priority)
    df = df.sort_values(['net_ev_pct', 'bucket_sort', 'momentum_60d_pct'], ascending=[False, True, False])

    text = cache_status_note()
    if not has_turnover:
        text += "NOTE: cache predates the liquidity filter - run refresh_cache.py to enable it. Costs below assume worst-case impact.\n"
    text += (f"Long-term scan - sorted by NET expected value after costs, showing up to {limit}.\n"
             f"⚠️ CAP-TIER REALITY (validated 2026-08, day-clustered, costs charged): the old z-scores "
             f"(Small 14.52, Mid 2.88, Large 2.28) were ~2.9x overlap-inflated. Honest: Small z 4.28 HOLDS; "
             f"Mid (z -0.01) and Large (z 0.34) are DEAD - no edge over random, do not present them as setups. "
             f"NOTE: the stronger validated long-term signal is the cross-sectional MOMENTUM scan "
             f"(scan_watchlist_text_long_momentum), not this near-52w-high screen.\n\n")
    for _, row in df.head(limit).iterrows():
        turn = f"{row['turnover_60d_cr']}cr/day" if row['turnover_60d_cr'] is not None else "turnover n/a"
        text += (f"{row['ticker']} [{row['cap_bucket']}]: Price ₹{row['current_price']}, momentum {row['momentum_60d_pct']}%, "
                 f"Stop ₹{row['stop_loss']}, Target ₹{row['target']}\n"
                 f"    liquidity {turn} | round-trip cost {row['round_trip_cost_pct']}% | "
                 f"NET expected value {row['net_ev_pct']:+.2f}%/trade\n")
    if excluded_illiquid:
        text += (f"\n{excluded_illiquid} candidate(s) excluded: daily turnover below ₹{MIN_TURNOVER_INR/1e7:.0f}cr, where "
                 f"impact costs likely exceed the measured edge. UNVALIDATED cost guard, not a backtested rule.\n")
    text += ("\nNET expected value = estimated gross edge minus Indian round-trip costs. The long-term gross edge "
             "has NOT yet been re-validated with the corrected engine - treat it as provisional and say so.\n")
    return text


MIN_SECTOR_PEERS = 5     # below this the "sector" average is one or two stocks, i.e. noise


def peer_strength(price_cache):
    """{ticker: (industry, peer 60d mean %, stock-minus-peers %)} from the granular industry map.

    Peer groups use the WHOLE cache, not just the scanned names - a bigger group is a better
    estimate of what the theme is doing. Industries with fewer than MIN_SECTOR_PEERS names are
    dropped rather than averaged into noise. Returns {} when the map has not been built.

    DISPLAY ONLY. Sector strength is not a validated ranking input (backtest_sector_rank.py) and
    must not reorder or filter the scan.
    """
    imap = load_industry_map()
    if not imap:
        return {}
    own, industries = {}, {}
    for ticker, df in price_cache.items():
        ind = imap.get(ticker, {}).get('industry')
        if not ind:
            continue
        c = df['close'].dropna().values
        if len(c) < 61 or c[-61] <= 0:
            continue
        own[ticker] = (c[-1] / c[-61] - 1) * 100
        industries.setdefault(ind, []).append(ticker)
    out = {}
    for ind, members in industries.items():
        if len(members) < MIN_SECTOR_PEERS:
            continue
        avg = sum(own[t] for t in members) / len(members)
        for t in members:
            out[t] = (ind, round(avg, 1), round(own[t] - avg, 1))
    return out


def scan_watchlist_text_long_momentum(limit=20):
    """Cross-sectional momentum scan - the VALIDATED long-term signal (2026-08).
    Ranks the liquid Mid/Small universe by 12M-1M momentum (skip the most recent month) and surfaces
    the TOP QUARTILE. Re-measured 2026-09 on NON-overlapping monthly rebalances (backtest_longterm_exits.py):
    edge ~+0.6%/month over the universe, z_paired median 1.94 across 20 start offsets (9/20 clear 2.0) -
    positive but not firmly demonstrated. The old 'z ~9.5' entered every day with a 20-day hold and
    counted each month ~20 times.

    NO stop / target: the inherited -8% stop / +16% target cost the basket -1.70%/trade (z_paired
    -3.39, worse in 5/5 periods) - the stop whipsaws out of names that recover. The stop DOES cut
    P(down >20%) from 3.1% to 0.2%; that trade-off is shown, not prescribed.

    Re-checked monthly (backtest_longterm_recheck.py): the 'low-vol tilt adds return' claim was
    BACKWARDS - low-atr% names returned -0.81%/month LESS than high-atr% (0/5 periods), but carry
    half the tail (P(<-20%) 2.1% vs 4.2%). A risk dial, not a return edge. Top 20 beat the rest
    of the quartile +0.69%/month in 4/5 periods (z_paired 1.40; the old +5.33 was overlap-inflated)
    - directionally right, not demonstrated - so depth stays 20.

    DO NOT add an over-extension FILTER - but DO show the tail risk. Measured 2026-09
    (longterm_extension_results.md): mean return RISES with momentum (30-60% band +1.01%/trade ->
    400%+ band +3.21%), so cutting extended names would remove the best ones. But the left tail
    rises monotonically too - P(down >20% in 20 days) 2% -> 6% across the bands. In a basket the
    return pays for that tail; in a single position it does not. Hence the per-name risk label
    below instead of a filter.

    THIS IS A BASKET STRATEGY: hold SEVERAL of the top names, rebalanced ~monthly - not a single
    pick. Momentum CRASHES: 2 of the 5 backtested years were negative (the top names underperformed
    the universe). High return, high drawdown - size small and diversify across the basket.
    """
    cache = load_price_cache_long()
    peers = peer_strength(cache)
    rows = []
    for ticker, df in cache.items():
        cap = CAP_BUCKET_MAP.get(ticker)
        if cap not in ('Mid', 'Small'):
            continue
        d = df.dropna(subset=['close', 'turnover_60d'])
        if len(d) < 260:
            continue
        c = d['close'].values
        turn = float(d['turnover_60d'].values[-1])
        if not np.isfinite(turn) or turn < MIN_TURNOVER_INR or c[-252] <= 0:
            continue
        mom = c[-21] / c[-252] - 1                     # 12M-1M: return from 252 bars ago to 21 bars ago
        atrp = d['atr_pct'].values[-1]                 # normalised volatility, not absolute price std
        ind, sec_mom, rs = peers.get(ticker, (None, None, None))
        rows.append({'ticker': ticker, 'cap': cap, 'price': round(float(c[-1]), 2),
                     'industry': ind, 'sec_mom': sec_mom, 'rs': rs,
                     'mom_pct': round(mom * 100, 1),
                     'atr_pct': round(float(atrp), 1) if np.isfinite(atrp) else None,
                     'turn_cr': round(turn / 1e7, 1)})

    if not rows:
        return "Long-term momentum scan: no liquid Mid/Small stocks with >=260 bars of history. Run refresh_cache.py."

    d = pd.DataFrame(rows)
    d['mom_rank'] = d['mom_pct'].rank(pct=True)
    top = d[d['mom_rank'] >= 0.75].sort_values('mom_pct', ascending=False)   # top quartile = the validated basket

    text = cache_status_note()
    text += (f"Long-term MOMENTUM scan (2014-2026, 139 non-overlapping monthly rebalances: edge ~+0.75%/month over the universe, z_paired 3.3, positive in every era incl. 2014-2021 out-of-sample; flattered by survivorship - today's listed names only). Top quartile of the liquid Mid/Small universe by "
             f"12-month momentum ({len(top)} names today).\n"
             f"⚠️ BASKET strategy - hold SEVERAL and rebalance ~monthly, NOT a single pick. atr% is a "
             f"RISK dial, not a return edge: low-atr% names had ~half the chance of a -20% month (about 2% vs "
             f"4%) with no reliable return difference (less in 2021-26, equal in 2014-21). Momentum "
             f"CRASHES: 2 of 5 backtested years were negative. High return, high drawdown - size small.\n"
             f"EXIT (measured 2026-09): hold ~20 sessions, then re-rank. NO fixed stop/target - a -8% stop cost "
             f"-1.5%/trade in 2021-26 (z -3.65) and -0.9% in 2014-21 out-of-sample (z -2.46) because momentum names "
             f"dip and recover. It only paid in falling small-cap markets (2018-20). It "
             f"does cut P(down >20%) from 3.1% to 0.2% per name - with only 1-2 names that trade-off is your call.\n"
             f"Sorted highest-momentum first: the top 20 returned +2.19%/trade vs +1.39% for the whole quartile "
             f"(monthly, non-overlapping; ahead of the rest in 4/5 periods but z_paired only 1.4 - not demonstrated).\n"
             f"TAIL RISK rises with momentum even though mean return does too - P(down >20% in 20 days) runs "
             f"2% / 3% / 3% / 5% / 6% across the 30-60 / 60-100 / 100-200 / 200-400 / 400%+ momentum bands. "
             f"Shown per name below. A basket absorbs that tail; a single position does NOT - the further down "
             f"this list you buy, the lower the expected return but also the smaller the blow-up risk.\n\n")
    for _, r in top.head(limit).iterrows():
        atr_s = f"{r['atr_pct']}% atr" if r['atr_pct'] is not None else "atr n/a"
        if r['industry']:
            sec_s = (f"\n    {r['industry']}: peers {r['sec_mom']:+.1f}% over 60d, this stock "
                     f"{'ahead of' if r['rs'] > 0 else 'behind'} them by {abs(r['rs']):.1f}pp")
        else:
            sec_s = ""
        tail = momentum_tail_risk(r['mom_pct'] / 100)
        tail_s = (f" | tail risk {tail[0]:.0%} chance of -20% in 20d, worst-decile {tail[1]:.1f}%"
                  + (" (thin sample, n=803)" if r['mom_pct'] >= 400 else "")) if tail else ""
        text += (f"{r['ticker']} [{r['cap']}]: Rs{r['price']}, 12M mom {r['mom_pct']:+.1f}%, {atr_s}, "
                 f"{r['turn_cr']}cr/day{tail_s}{sec_s}\n")
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


def label_cash_conversion(value):
    """Operating cash flow / net profit. <0 means profit isn't turning into cash - the key
    red flag for working-capital-heavy businesses (recyclers, infra, EPC)."""
    if value is None:
        return "N/A"
    if value < 0:
        return "negative - profit NOT converting to cash (red flag)"
    elif value < 0.8:
        return "weak - watch working capital"
    else:
        return "healthy - profit converts to cash"


def _fmt_cr(v):
    """Rupees -> compact crore string."""
    return f"{v / 1e7:,.0f}cr"


def format_trend(pairs):
    """[(year, value), ...] newest-first -> 'FY24 X -> FY25 Y -> FY26 Z (CAGR ..%)' oldest-first."""
    if not pairs or len(pairs) < 2:
        return None
    p = list(reversed(pairs))  # oldest -> newest
    chain = " -> ".join(f"FY{str(y)[2:]} {_fmt_cr(v)}" for y, v in p)
    first, last = p[0][1], p[-1][1]
    yrs = len(p) - 1
    cagr = ((last / first) ** (1 / yrs) - 1) * 100 if first > 0 and last > 0 else None
    return chain + (f" (CAGR {cagr:+.0f}%)" if cagr is not None else "")


def label_profit_margin(value):
    if value is None:
        return "N/A"
    if value > 20:
        return "Strong"
    elif value > 10:
        return "Moderate"
    else:
        return "Thin"


def label_growth(value):
    """YoY revenue/earnings growth, in %. Directional, not advice."""
    if value is None:
        return "N/A"
    if value < 0:
        return "declining"
    elif value < 10:
        return "modest"
    elif value < 25:
        return "strong"
    else:
        return "very strong"


def label_pe(value):
    """P/E as valuation (how expensive vs earnings). Cheap can also mean a troubled business,
    and 'fair' P/E varies a lot by sector - so this describes price, not quality."""
    if value is None or value <= 0:
        return "N/A - no positive earnings"
    if value < 15:
        return "cheap"
    elif value < 30:
        return "moderate"
    elif value < 60:
        return "expensive"
    else:
        return "very expensive"


def label_breadth(pct):
    """% of stocks above their 200-day average = how much of the market is in an uptrend."""
    if pct is None:
        return "N/A"
    if pct < 40:
        return "weak - most stocks below trend"
    elif pct < 60:
        return "mixed"
    else:
        return "healthy - most stocks in uptrend"


def label_delivery(pct):
    """Absolute delivery %: how much of the volume was bought to hold vs day-traded."""
    if pct is None:
        return "N/A"
    if pct > 60:
        return "high - genuine accumulation"
    elif pct >= 40:
        return "moderate"
    else:
        return "low - mostly intraday churn"


def label_rel_strength(pct):
    """Magnitude of out/under-performance vs a benchmark, in percentage points."""
    if pct is None:
        return "N/A"
    if pct > 15:
        return "strongly outperforming"
    elif pct > 3:
        return "outperforming"
    elif pct >= -3:
        return "roughly in line with"
    elif pct >= -15:
        return "underperforming"
    else:
        return "strongly underperforming"


def label_interest_cover(value):
    if value >= 6:
        return "comfortable"
    elif value >= 3:
        return "adequate"
    elif value >= 1.5:
        return "tight"
    else:
        return "cannot comfortably service its debt"


def _parse_shp_date(raw):
    """'30-JUN-2026' -> Timestamp. NSE mixes case ('30-Jun-2026'), hence the upper()."""
    return pd.to_datetime(raw.strip().upper(), format='%d-%b-%Y')


def promoter_snapshot(ticker):
    """Latest promoter holding %, its change over the last 4 quarters, and current pledge %.

    Sourced from NSE quarterly filings (build_shareholding_archive.py), NOT yfinance - yfinance's
    'insider holding' is a different thing and wrong for Indian promoters. Returns {} when the
    archive has not been built, so every caller degrades to silence rather than an error."""
    symbol = ticker.replace(".NS", "")
    out = {}
    try:
        rows = load_shareholding_archive().get(symbol) or []
    except Exception:
        rows = []
    parsed = []
    for r in rows:
        try:
            parsed.append((_parse_shp_date(r['date']), float(r['pr_and_prgrp'])))
        except Exception:
            continue
    if parsed:
        parsed.sort()
        out['promoter_pct'] = parsed[-1][1]
        out['promoter_as_of'] = parsed[-1][0].strftime('%d-%b-%Y')
        out['promoter_quarters'] = len(parsed)
        if len(parsed) >= 5:
            out['promoter_change_1y_pp'] = round(parsed[-1][1] - parsed[-5][1], 2)
        elif len(parsed) >= 2:
            out['promoter_change_1y_pp'] = round(parsed[-1][1] - parsed[0][1], 2)
    try:
        pledge = load_pledge_snapshot().get(symbol) or {}
        out['pledge_pct'] = float(str(pledge.get('percSharesPledged', '')).strip())
        out['pledge_as_of'] = pledge.get('shp')
    except Exception:
        pass
    return out


# Thresholds are deliberately blunt and in code, not left to the model to eyeball: the verdict
# has to be a tool result the agent can cite, and it has to read the same way every time.
FRAGILE_RULES = (
    ('cash_conversion', lambda v: v < 0, "operating cash flow is negative while profit is not - profit is on paper"),
    ('interest_cover', lambda v: v < 1.5, "earnings barely cover the interest bill"),
    ('debt_to_equity', lambda v: v > 200, "debt is more than 2x own money"),
)
SOLID_RULES = (
    ('cash_conversion', lambda v: v >= 0.8, "profit is converting to real cash"),
    ('interest_cover', lambda v: v >= 6, "interest bill is comfortably covered"),
    ('debt_to_equity', lambda v: v < 100, "more own money than loans"),
)


def _trend_rising(pairs):
    """True/False if the multi-year series is monotonically up (oldest->newest), None if unknown.
    yfinance serves these newest-first, so sort by year before judging direction."""
    if not pairs or len(pairs) < 3:
        return None
    vals = [v for _, v in sorted(pairs)]
    return all(b > a for a, b in zip(vals, vals[1:]))


def fundamental_verdict(fund, promoter=None):
    """(verdict, [reasons]) - 'Solid' / 'Mixed' / 'Fragile' / 'Unknown'.

    A SAFETY check that runs AFTER a name is flagged, never an input to the scan:
    backtest_fundamentals.py measured these factors at z<2 against a random-entry control, and
    backtest_promoter_holding.py did the same for the promoter/pledge triggers with far more
    statistical power (555 broadcast days, every z_paired < 2 at holds of 5/10/21 sessions).
    Any single fragile condition outweighs every solid one - the point is to catch landmines,
    not to score businesses."""
    promoter = promoter or {}
    fragile, solid = [], []
    for key, is_bad, why in FRAGILE_RULES:
        v = fund.get(key)
        if v is not None and is_bad(v):
            fragile.append(why)
    for key, is_good, why in SOLID_RULES:
        v = fund.get(key)
        if v is not None and is_good(v):
            solid.append(why)

    pledge = promoter.get('pledge_pct')
    if pledge is not None and pledge >= 25:
        fragile.append(f"{pledge:.1f}% of promoter shares are pledged")
    drop = promoter.get('promoter_change_1y_pp')
    if drop is not None and drop <= -5:
        fragile.append(f"promoters cut their own holding by {abs(drop):.1f} percentage points over the past year")

    pat_rising = _trend_rising(fund.get('pat_trend'))
    if pat_rising is True:
        solid.append("profit has risen every year on record")
    elif pat_rising is False and _trend_rising(fund.get('rev_trend')) is False:
        fragile.append("both sales and profit have failed to grow consistently")

    if fragile:
        return "Fragile", fragile
    if not solid:
        return "Unknown", ["not enough statement data to judge"]
    if len(solid) >= 3:
        return "Solid", solid
    return "Mixed", solid


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
    text += f"P/E Ratio: {fund['trailing_pe']:.1f} ({label_pe(fund['trailing_pe'])}) - price paid per Rs1 of yearly profit\n" if fund['trailing_pe'] else "P/E Ratio: N/A\n"
    text += f"Revenue Growth (YoY): {fund['revenue_growth_pct']}% ({label_growth(fund['revenue_growth_pct'])})\n" if fund['revenue_growth_pct'] is not None else ""
    text += f"Earnings Growth (YoY): {fund['earnings_growth_pct']}% ({label_growth(fund['earnings_growth_pct'])})\n" if fund['earnings_growth_pct'] is not None else ""
    text += f"Profit Margin: {fund['profit_margin_pct']}% ({label_profit_margin(fund['profit_margin_pct'])})\n" if fund['profit_margin_pct'] is not None else ""
    text += f"ROE: {fund['roe_pct']}% ({label_roe(fund['roe_pct'])}) - profit made on shareholders' money\n" if fund['roe_pct'] is not None else ""
    if fund.get('roce_pct') is not None:
        text += f"ROCE: {fund['roce_pct']}% ({label_roe(fund['roce_pct'])}) - profit made on ALL money in the business\n"
    if fund['debt_to_equity'] is not None:
        de = fund['debt_to_equity'] / 100  # yfinance gives a percent; show the ratio (82 -> 0.82x)
        text += f"Debt vs own money: {de:.2f}x ({label_debt_to_equity(fund['debt_to_equity'])} leverage) - under 1 = more own money than loans\n"
    if fund.get('interest_cover') is not None:
        text += (f"Interest cover: {fund['interest_cover']:.1f}x ({label_interest_cover(fund['interest_cover'])}) "
                 f"- how many times over the year's profit pays the year's interest bill\n")
    if fund.get('cash_conversion') is not None:
        text += f"Cash conversion: {fund['cash_conversion']:.2f}x ({label_cash_conversion(fund['cash_conversion'])}) - is the profit real cash or just on paper?\n"
    rev_t = format_trend(fund.get('rev_trend'))
    pat_t = format_trend(fund.get('pat_trend'))
    if rev_t:
        text += f"Sales over the years: {rev_t} - is the business getting bigger?\n"
    if pat_t:
        text += f"Profit over the years: {pat_t} - is it actually earning more?\n"
    promoter = promoter_snapshot(ticker)
    if promoter.get('promoter_pct') is not None:
        text += f"Promoter holding: {promoter['promoter_pct']:.2f}% (NSE filing for quarter ending {promoter['promoter_as_of']})\n"
        chg = promoter.get('promoter_change_1y_pp')
        if chg is not None:
            direction = "up" if chg > 0 else ("down" if chg < 0 else "unchanged")
            text += (f"  Change over the past year: {direction} {abs(chg):.2f} percentage points "
                     f"- context on who owns the business. Tested (promoter_holding_results.md): this does NOT predict forward returns, so it never changes the trade call\n")
    if promoter.get('pledge_pct') is not None:
        text += (f"Promoter shares pledged: {promoter['pledge_pct']:.2f}% (as of {promoter.get('pledge_as_of')}) "
                 f"- shares the promoters have put up as loan collateral; a high number means a falling price "
                 f"can force more selling\n")

    if fund['trailing_pe'] and fund['trailing_pe'] > 100:
        text += "NOTE: Very high P/E - the price already assumes big growth; risky if growth slips.\n"
    verdict, reasons = fundamental_verdict(fund, promoter)
    text += f"\nBUSINESS QUALITY VERDICT: {verdict}\n"
    for r in reasons:
        text += f"  - {r}\n"
    text += {
        'Solid': "  What to do: the business is sturdy, so a flagged setup can be sized normally.\n",
        'Mixed': "  What to do: nothing alarming, nothing reassuring - size normally, no extra confidence.\n",
        'Fragile': "  What to do: this is a landmine risk. Trade smaller or skip, even if the chart looks great.\n",
        'Unknown': "  What to do: treat as unverified - absence of red flags is not the same as safety.\n",
    }[verdict]

    if any(fund.get(k) is not None for k in ('roce_pct', 'cash_conversion', 'rev_trend')):
        text += (
            "\nHOW TO USE THIS (plain): the numbers above describe the BUSINESS, not the trade. We "
            "tested them (backtest_fundamentals.py) and they do NOT predict the next few weeks' price "
            "move - z<2, basically no effect - so they NEVER change the scan's buy/sell call. Use them "
            "only as a sturdiness check AFTER a name is flagged: rising sales+profit and healthy cash = "
            "a solid business you can size normally; red flags (cash conversion negative, high debt, "
            "profit shrinking) = fragile, so trade smaller or skip even if the chart looks great.\n")
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
        if len(match) > 0 and match['DELIV_PER'].notna().any():
            avg_delivery = match['DELIV_PER'].mean()
            latest_delivery = match.sort_values('DATE_FETCHED').iloc[-1]['DELIV_PER']
            if pd.notna(latest_delivery):
                trend = "above average" if latest_delivery > avg_delivery else "below average"
                text += f"Delivery %: {latest_delivery:.2f}% latest ({label_delivery(latest_delivery)}), {avg_delivery:.2f}% avg over last {len(match)} trading days ({trend})\n"
                text += ("  In plain words: of all shares traded, how many buyers actually took them home vs just day-traded and flipped. "
                         "Higher = real buyers stepping in. What to do: use it as a small confidence tick behind a setup, never as a buy signal on its own.\n\n")
            else:
                text += "Delivery %: latest value unavailable.\n\n"
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
            text += ("  In plain words: a bulk deal = one big investor bought or sold a large chunk in the open market and had to report it to NSE. "
                     "What to do: a big BUY by a known name is a mild positive, a big SELL is a mild caution - context, not a signal to act on.\n")
    except Exception as e:
        text += f"Bulk deal data unavailable: {e}\n"
    return text

def get_market_regime_text():
    try:
        breadth = load_market_breadth_cache()
        text = f"Market Regime: {breadth['regime']}\n"
        text += f"Breadth: {breadth['breadth_pct_above_200sma']}% of watchlist stocks are above their 200-day average ({label_breadth(breadth['breadth_pct_above_200sma'])})\n"
        text += f"Nifty above its own 200-day average: {'Yes' if breadth['nifty_above_200sma'] else 'No'}\n"

        try:
            vix_df = load_vix_cache()
            latest_vix = vix_df['close'].iloc[-1]
            avg_vix_20d = vix_df['close'].tail(20).mean()
            if latest_vix < 15:
                vix_read = "Low - market is calm/complacent"
            elif latest_vix < 20:
                vix_read = "Normal range"
            elif latest_vix < 30:
                vix_read = "Elevated - increased caution/uncertainty priced in"
            else:
                vix_read = "High - significant fear/volatility in the market"
            text += f"India VIX: {latest_vix:.1f} ({vix_read}), 20-day avg: {avg_vix_20d:.1f}\n"
            text += "(VIX context is informational only - not independently backtested, unlike the core validated strategies)\n"
        except Exception:
            text += "India VIX data unavailable.\n"

        if breadth['regime'] == "Broadly Bearish":
            text += "CAUTION: Broad market conditions are weak - momentum/breakout setups are statistically less reliable in this environment.\n"
        text += ("In plain words: this is the whole market's mood. 'Breadth' = how many stocks are trending up; VIX = the market's fear level "
                 "(low = calm, high = scared). What to do: when the mood is healthy/calm your setups tend to work more often, so trade normally; "
                 "when it's weak or fearful they misfire more, so take fewer trades and size smaller.\n")
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

# Measured over 5y on the Mid/Small >=Rs25cr universe: mean net return per trade, split by how
# many candidates fired the same day. Random entries show the SAME gradient (+1.27%/trade on
# 21+ days), so this describes market conditions, not signal quality - the wording below must
# not let it read as "the setup is better today".
_COUNT_BANDS = [
    (2,  "-0.37%", "very thin - the market is calm and these have historically been LOSING days"),
    (5,  "-0.77%", "thin - historically the worst band"),
    (10, "-0.18%", "moderate - historically around break-even"),
    (20, "+0.89%", "broad selloff - historically profitable"),
    (10 ** 9, "+2.34%", "market-wide capitulation - historically the most profitable days"),
]


# The one validated finding from the 369k-filing news archive (news_event_results.md).
# Stocks that announce dilution underperform a random-entry control for at least a week:
# measured over 1,391 events, 2021-2026, day-clustered, at the 6-day horizon this strategy
# actually trades - edge -0.29%/trade, z_paired -3.34, and stable across 3 to 7 days (-2.57 to
# -3.40). It is the ONLY result in that study that survives correcting for 24 comparisons.
# Direction is not predictable from most filings; this one is the exception, and it says AVOID.
DILUTION_KEYWORDS = ['qip', 'qualified institutional', 'preferential issue',
                     'preferential allotment', 'rights issue', 'fund raising', 'fund-raising']
DILUTION_LOOKBACK_DAYS = 7


def recent_dilution(ticker):
    """(bool, detail) - did this stock announce dilution in the last week?

    Reads the corporate-announcements cache the daily refresh already maintains, so this costs
    nothing extra at scan time.
    """
    symbol = (ticker or '').replace('.NS', '').strip().upper()
    try:
        df = load_corp_announcements_cache()
    except Exception:
        return False, None
    if df is None or len(df) == 0 or 'symbol' not in df:
        return False, None

    hits = df[df['symbol'].astype(str).str.upper() == symbol]
    for _, row in hits.iterrows():
        blob = f"{row.get('desc') or ''} {row.get('attchmntText') or ''}".lower()
        if any(kw in blob for kw in DILUTION_KEYWORDS):
            try:
                when = datetime.strptime(str(row['an_dt'])[:11], '%d-%b-%Y')
                if (datetime.now() - when).days > DILUTION_LOOKBACK_DAYS:
                    continue
                stamp = f"{when:%d-%b}"
            except Exception:
                stamp = str(row.get('an_dt'))[:11]
            return True, f"{stamp}: {row.get('desc')}"
    return False, None


def setup_checklist(row, n_candidates=None):
    """Applies the documented read-the-scan rules to one candidate and returns a verdict.

    Every one of these was already computed and printed as prose, leaving the user to apply
    the thresholds by hand every morning. Nothing new is measured here - this only states the
    pass/fail the numbers already imply, so the rules cannot be silently forgotten.

    Returns (rows, verdict) where rows is [(check, 'PASS'|'WEAK'|'FAIL', detail)].
    """
    checks = []

    if n_candidates is not None:
        hist, label = candidate_band(n_candidates)
        state = 'PASS' if n_candidates >= 11 else 'FAIL'
        checks.append(("Market conditions", state,
                       f"{n_candidates} candidates today, historical {hist}/trade ({label.split(' - ')[0]})"))

    cap = row.get('cap_bucket', 'Unknown')
    if cap == 'Small':
        checks.append(("Cap tier", 'PASS', "Small-cap, holds day-clustered (z 2.74)"))
    elif cap == 'Mid':
        checks.append(("Cap tier", 'WEAK', "Mid-cap, no longer demonstrated (z 1.73)"))
    else:
        checks.append(("Cap tier", 'FAIL', f"{cap}, outside the validated Mid/Small universe"))

    tier = row.get('trend_tier', 'Unknown')
    if tier == 'Flat/Mild':
        checks.append(("Trend tier", 'PASS', "Flat/Mild, most reliable tier (z 4.41)"))
    elif tier == 'Uptrend':
        checks.append(("Trend tier", 'PASS', "Uptrend, highest return but fewer days (z 2.05)"))
    elif tier == 'Downtrend':
        checks.append(("Trend tier", 'FAIL', "Downtrend, not distinguishable from random (z 0.71)"))
    else:
        checks.append(("Trend tier", 'WEAK', "trend tier unknown"))

    mp = row.get('meta_win_prob')
    if mp is None or pd.isna(mp):
        checks.append(("P(win)", 'WEAK', "unavailable - no opinion, NOT a low score"))
    elif mp < META_MIN_TRADEABLE:
        checks.append(("P(win)", 'FAIL', f"{mp*100:.0f}%, below the {META_MIN_TRADEABLE*100:.0f}% floor - "
                                         f"negative measured EV, not merely weak"))
    else:
        checks.append(("P(win)", 'PASS', f"{mp*100:.0f}%, above the tradeable floor"))

    ev = row.get('net_ev_pct')
    if ev is None or pd.isna(ev):
        checks.append(("Net expected value", 'WEAK', "not computable"))
    elif ev <= 0:
        checks.append(("Net expected value", 'FAIL', f"{ev:+.2f}%/trade after costs"))
    else:
        checks.append(("Net expected value", 'PASS', f"{ev:+.2f}%/trade after costs"))

    rsi = row.get('rsi')
    if rsi is None or pd.isna(rsi):
        checks.append(("Oversold depth", 'WEAK', "RSI unavailable"))
    elif rsi < 26:
        checks.append(("Oversold depth", 'PASS', f"RSI {rsi}, deep (<24 band earned +1.17%/trade)"))
    elif rsi < 30:
        checks.append(("Oversold depth", 'WEAK', f"RSI {rsi}, shallow end (28-30 earned +0.27%)"))
    else:
        checks.append(("Oversold depth", 'FAIL', f"RSI {rsi}, not oversold"))

    turn = row.get('turnover_60d_cr')
    floor_cr = MIN_TURNOVER_INR / 1e7
    if turn is None or pd.isna(turn):
        checks.append(("Liquidity", 'WEAK', "turnover unavailable"))
    elif turn < floor_cr:
        checks.append(("Liquidity", 'FAIL', f"Rs{turn}cr/day, below the Rs{floor_cr:.0f}cr floor"))
    else:
        checks.append(("Liquidity", 'PASS', f"Rs{turn}cr/day, above the floor"))

    diluted, detail = recent_dilution(row.get('ticker'))
    if diluted:
        checks.append(("Recent dilution", 'FAIL',
                       f"{detail} - dilution events underperform by -0.29%/trade over 6 days "
                       f"(z_paired -3.34, n=1391)"))
    else:
        checks.append(("Recent dilution", 'PASS',
                       f"no fund-raising filing in the last {DILUTION_LOOKBACK_DAYS} days"))

    fails = [c for c in checks if c[1] == 'FAIL']
    weaks = [c for c in checks if c[1] == 'WEAK']
    if fails:
        verdict = (f"DOES NOT CLEAR - fails {len(fails)} check(s): "
                   f"{', '.join(c[0].lower() for c in fails)}. The measured edge does not cover "
                   f"this setup.")
    elif weaks:
        verdict = (f"CLEARS, WITH {len(weaks)} SOFT SPOT(S): "
                   f"{', '.join(c[0].lower() for c in weaks)}. Tradeable on the rules, but not "
                   f"the strongest version of this setup.")
    else:
        verdict = ("CLEARS EVERY CHECK - this is what the validated setup looks like. Still size "
                   "it normally: the strategy as a whole has been flat for 12 months.")
    return checks, verdict


def format_checklist(row, n_candidates=None, indent="    "):
    checks, verdict = setup_checklist(row, n_candidates)
    mark = {'PASS': '[PASS]', 'WEAK': '[WEAK]', 'FAIL': '[FAIL]'}
    lines = [f"{indent}--- setup checklist ---"]
    for name, state, detail in checks:
        lines.append(f"{indent}{mark[state]:<7}{name:<20}{detail}")
    lines.append(f"{indent}>> {verdict}")
    return "\n".join(lines) + "\n"


def candidate_count_note(n):
    """Reports how many names triggered today. Free context, and the strongest single predictor
    of absolute return measured on this universe - but it is mostly market beta, so it is
    labelled as conditions rather than as setup quality."""
    hist, label = candidate_band(n)
    return (f"MARKET CONDITIONS: {n} candidate(s) passed the filter today - {label}.\n"
            f"  Historical mean {hist}/trade on days with this many candidates (5y, net of costs).\n"
            f"  This reflects the MARKET, not the quality of the setups below: random entries show "
            f"the same pattern (+1.27%/trade on 21+ candidate days), so roughly half of it is simply "
            f"how much the market bounces. Not a validated entry rule - context only.\n\n")


def parse_bool(value, default=True):
    """Handles cases where the model sends 'True'/'true'/'false' as a string instead of a real boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    return default

def parse_number(value, default=None):
    """Handles cases where the model sends a number as a string like '2000', or even
    nested/wrapped in a dict like {'limit': 10}, instead of a plain number."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value) if '.' in value else int(value)
        except ValueError:
            return default
    if isinstance(value, dict):
        for v in value.values():
            result = parse_number(v, default=None)
            if result is not None:
                return result
        return default
    return default

def cache_has_turnover(price_cache):
    """Stale caches predate turnover_60d. Filtering on a missing column would silently
    reject the entire universe, so callers skip the liquidity filter instead."""
    for df in price_cache.values():
        return 'turnover_60d' in df.columns
    return False


def scan_watchlist_text_short(limit=30, rsi_threshold=30):
    price_cache = load_price_cache_short()
    has_turnover = cache_has_turnover(price_cache)
    snapshot_rows = []
    failures = 0
    excluded_illiquid = 0
    for ticker in price_cache.keys():
        bucket = CAP_BUCKET_MAP.get(ticker)
        if bucket == 'Large':
            continue  # RSI<30 has no proven edge in large-caps (backtested z=1.29, not significant)
        try:
            levels = get_swing_levels_short(ticker)
            if levels['rsi'] >= rsi_threshold:
                continue
            if has_turnover and levels['illiquid']:
                excluded_illiquid += 1
                continue
            snapshot_rows.append(levels)
        except Exception:
            failures += 1
            continue

    if len(snapshot_rows) == 0:
        if failures == len(price_cache):
            return "Scan failed for every stock in the cache - the price cache is likely missing or corrupt. Run refresh_cache.py."
        return f"No stocks currently have RSI below {rsi_threshold} in the validated (Mid/Small cap) universe (plus {excluded_illiquid} excluded as too illiquid to trade net of costs)."

    df = pd.DataFrame(snapshot_rows)
    tier_priority = {'Uptrend': 0, 'Flat/Mild': 1, 'Downtrend': 2, 'Unknown': 3}
    df['tier_sort'] = df['trend_tier'].map(tier_priority)
    # Sort by NET expected value, then meta win-probability, then trend tier. Ranking on raw
    # RSI ignored the cost difference between names, the fact that edge scales with oversold
    # depth, and everything the meta-model knows about setup quality.
    df['meta_sort'] = df['meta_win_prob'].fillna(-1)
    # Golden-cross uptrend (strategy 035) is a WATCH-level refinement, so it only breaks ties
    # AFTER net EV and P(win) - it prefers structurally-aligned names, never overrides EV.
    df['gc_sort'] = df.get('golden_cross', False).astype(int)
    df = df.sort_values(['net_ev_pct', 'meta_sort', 'gc_sort', 'tier_sort'],
                        ascending=[False, False, False, True])

    text = cache_status_note()
    if not has_turnover:
        text += "NOTE: cache predates the liquidity filter - run refresh_cache.py to enable it. Costs below assume worst-case impact.\n"
    text += candidate_count_note(len(df))
    text += (f"Short-term scan - RSI < {rsi_threshold}, sorted by NET expected value after costs, showing up to {limit}.\n"
             f"Edge scales with oversold depth (5y walk-forward, net of costs, at/above the liquidity floor):\n"
             f"  RSI<24 +1.17%/trade | 24-26 +0.77% | 26-28 +0.50% | 28-30 +0.27% | 30-35 +0.10% (barely clears costs)\n"
             f"Trend tier is shown but is not the primary sort. Day-clustered vs same-day random control: "
             f"Flat/Mild z 4.41 (most reliable) | Uptrend z 2.05 (highest return/trade, fewer days) | "
             f"Downtrend z 0.71 - NOT distinguishable from random, that tier is no longer validated.\n"
             f"Cap tier: Small-cap holds (z 2.74); Mid-cap is no longer demonstrated (z 1.73) - partly a "
             f"power limit, not proof it loses.\n"
             f"[GC] = golden-cross uptrend (close>200SMA and 50SMA>200SMA), strategy-035 refinement: "
             f"in-sample +0.66%/day over plain RSI<30, but out-of-sample holdout z_paired 1.53 (below the "
             f"2.0 bar) - WATCH-level, pending live forward validation. It ranks candidates up as a "
             f"tiebreaker only; it does NOT gate entries or change the NET EV.\n\n")
    for _, row in df.head(limit).iterrows():
        spike_flag = " [VOLUME SPIKE]" if row['volume_spike'] else ""
        gc_flag = " [GC]" if row.get('golden_cross') else ""
        turn = f"{row['turnover_60d_cr']}cr/day" if row['turnover_60d_cr'] is not None else "turnover n/a"
        mp = row['meta_win_prob']
        if mp is not None and pd.notna(mp):
            flag = "  ⚠️ BELOW TRADEABLE FLOOR" if mp < META_MIN_TRADEABLE else ""
            meta = f" | P(win) {mp*100:.0f}%{flag}"
        else:
            meta = " | P(win) unavailable (no opinion - NOT a low score)"
        unvalidated = []
        if row.get('tier_unvalidated'):
            unvalidated.append("Downtrend tier")
        if row.get('cap_unvalidated'):
            unvalidated.append("Mid-cap")
        unval_flag = (f"\n    ⚠️ {' + '.join(unvalidated)}: not distinguishable from random entry once "
                      f"day-clustered - the NET EV above does not account for this.") if unvalidated else ""
        text += (f"{row['ticker']} [{row['cap_bucket']}, {row['trend_tier']}, {row['change_1yr_pct']}% 1yr]{gc_flag}: "
                 f"Price ₹{row['current_price']}, "
                 f"RSI {row['rsi']}, Stop ₹{row['stop_loss']}, Target ₹{row['target']}{spike_flag}{unval_flag}\n"
                 f"    liquidity {turn} | round-trip cost {row['round_trip_cost_pct']}% | "
                 f"NET expected value {row['net_ev_pct']:+.2f}%/trade{meta}\n")
        text += format_checklist(row, n_candidates=len(df))
    if excluded_illiquid:
        text += (f"\n{excluded_illiquid} candidate(s) excluded: daily turnover below ₹{MIN_TURNOVER_INR/1e7:.0f}cr, where "
                 f"impact costs exceed the measured edge. VALIDATED: 5-fold walk-forward, beat the unfiltered "
                 f"universe in all 5 folds (+0.564% vs +0.259% net/trade).\n")
    tradeable = df[(df['net_ev_pct'] > 0) & (~df['below_meta_floor'])]
    if len(tradeable) == 0:
        text += ("\n⚠️ NOTHING TRADEABLE TODAY: every candidate above has either a negative net expected "
                 "value or a P(win) below the 0.50 floor where the measured edge is negative before costs. "
                 "The correct action is to take no trade, not to pick the least-bad name.\n")

    text += ("\nNET expected value = gross edge minus Indian round-trip costs (STT, brokerage, fees, GST, "
             "stamp duty, slippage, liquidity-scaled impact). The gross edge comes from the meta-model P(win) "
             "where available (a sharper out-of-sample discriminator), otherwise from the RSI band. Quote the "
             "NET figure, never the gross. NOTE: the most recent 12-month fold was negative across every "
             "configuration tested.\n")
    return text

def calculate_position_size(ticker, total_capital, risk_pct=DEFAULT_RISK_PCT, term="short", confirmed=False):
    ticker = (ticker or '').strip()
    if not ticker:
        return {'error': "No ticker was provided. First scan for a candidate, then call this tool with that ticker."}

    if total_capital is None:
        total_capital = DEFAULT_CAPITAL
    if risk_pct is None:
        risk_pct = DEFAULT_RISK_PCT
    if total_capital <= 0:
        return {'error': f"total_capital must be positive, got {total_capital}."}

    if term == "breakout":
        levels = get_breakout_levels(ticker)
    elif term == "short":
        levels = get_swing_levels_short(ticker)
    else:
        levels = get_swing_levels_long(ticker)

    if term == "long" and levels.get('extreme_momentum') and not confirmed:
        return {
            'blocked': True,
            'reason': (f"{ticker} is flagged as an extreme/parabolic move (RSI {levels['rsi']}, "
                       f"60-day momentum {levels.get('momentum_60d_pct')}%). Position sizing was NOT calculated. "
                       f"Explicitly ask the user if they want to proceed despite this caution. "
                       f"If they confirm, call this tool again with confirmed=true.")
        }

    # A setup below the meta floor has a NEGATIVE measured edge before costs. Sizing it without
    # comment would let the tool hand over a share count for a trade the data says loses money.
    if levels.get('below_meta_floor') and not confirmed:
        return {
            'blocked': True,
            'reason': (f"{ticker} has P(win) {levels['meta_win_prob']*100:.0f}%, below the 50% floor. "
                       f"Out-of-sample, setups in this band average {levels['net_ev_pct']:+.2f}%/trade "
                       f"NET - a losing trade on average, not merely a weak one. Position sizing was NOT "
                       f"calculated. Show the user this number and ask whether they still want to proceed. "
                       f"If they confirm, call again with confirmed=true.")
        }

    # Business-quality gate. This is RISK MANAGEMENT, not signal: promoter/pledge triggers were
    # measured at z_paired < 2 (promoter_holding_results.md) and the statement factors at z < 2
    # (backtest_fundamentals.py), so a Fragile verdict predicts nothing about the next few days.
    # It gates anyway, because the losses it guards against - a forced pledge unwind, a company
    # that cannot service its debt - are the kind a backtest of average returns does not price.
    # It BLOCKS pending confirmation rather than refusing: the call stays the user's.
    if not confirmed:
        try:
            _fund = get_fundamentals(ticker)
            _verdict, _why = ((None, None) if 'error' in _fund
                              else fundamental_verdict(_fund, promoter_snapshot(ticker)))
        except Exception:
            _verdict, _why = None, None      # never let a data hiccup block a valid trade
        if _verdict == 'Fragile':
            return {
                'blocked': True,
                'reason': (f"{ticker} fails the business-quality check: " + "; ".join(_why) + ". "
                           f"Position sizing was NOT calculated. This does NOT predict the price move - "
                           f"it flags the company as fragile enough that a bad week can become a very bad "
                           f"week. Show the user these reasons and ask whether they want to proceed, size "
                           f"smaller, or skip. If they confirm, call again with confirmed=true."),
                'business_quality': _verdict,
            }

    if risk_pct > MAX_RISK_PCT and not confirmed:
        return {
            'blocked': True,
            'reason': (f"Requested risk_pct={risk_pct}% exceeds the standard maximum of {MAX_RISK_PCT}% per trade "
                       f"(normal range is 0.5-2%). Position sizing was NOT calculated. "
                       f"Explicitly ask the user to confirm this risk level before proceeding. "
                       f"If they confirm, call this tool again with confirmed=true.")
        }

    # Discipline layer. Behavioural, not predictive - these read the user's own trade log and
    # constrain the trader rather than forecasting the trade, which is why they carry no
    # backtest. Warnings ride along with a successful sizing; blocks behave like the other
    # gates above and need confirmed=true.
    discipline = discipline_check(ticker, risk_pct)
    if discipline['blocks'] and not confirmed:
        return {
            'blocked': True,
            'reason': " ".join(discipline['blocks']) +
                      " Position sizing was NOT calculated. Put this to the user in their own "
                      "words and ask whether they still want to proceed; if they confirm, call "
                      "again with confirmed=true.",
            'discipline_warnings': discipline['warnings'],
        }

    # Market-volatility regime scaling. Only applies to short-term mean reversion, where the
    # regime dependence was measured; the long-term momentum signal was not tested for this.
    vol_note, vol_mult = None, 1.0
    if term == "short":
        try:
            vp = load_market_breadth_cache().get('market_vol_percentile')
            vol_mult, vol_note = vol_regime_multiplier(vp)
            if vp is not None:
                vol_note = f"market vol at {vp*100:.0f}th percentile of its trailing year - {vol_note}"
        except Exception as e:
            vol_note = f"market volatility regime unavailable ({e}) - no adjustment applied"
    effective_risk_pct = risk_pct * vol_mult

    live_price = get_live_price(ticker)
    entry_price = live_price if live_price is not None else levels['current_price']
    price_source_note = "live quote" if live_price is not None else "cached price (live fetch failed)"
    stop_loss = levels['stop_loss']
    if entry_price <= 0:
        return {'error': f"{ticker}: entry price is {entry_price}, cannot size a position."}
    risk_amount = total_capital * (effective_risk_pct / 100)
    risk_per_share = entry_price - stop_loss
    if risk_per_share <= 0:
        return {
            'blocked': True,
            'reason': (f"{ticker}'s live price (₹{entry_price}) is already at or below its stop-loss (₹{stop_loss}). "
                       f"Position sizing was NOT calculated - this setup is no longer valid at the current price.")
        }
    shares_by_risk = int(risk_amount / risk_per_share)
    shares_by_capital = int(total_capital / entry_price)
    shares_to_buy = min(shares_by_risk, shares_by_capital)
    position_value = shares_to_buy * entry_price
    actual_risk_amount = shares_to_buy * risk_per_share

    # A bare shares_to_buy=0 used to go back with no explanation, and the agent would invent
    # one - usually "this is a bad trade". It is not a statement about the setup at all: it
    # means this ACCOUNT cannot hold one share at this risk %. Those are different questions
    # and blending them turns an account-size fact into a false verdict on the stock.
    if shares_to_buy == 0:
        need_for_risk = risk_per_share / (effective_risk_pct / 100) if effective_risk_pct else None
        min_capital = max(need_for_risk or 0, entry_price)
        return {
            'ticker': ticker, 'shares_to_buy': 0,
            'sizing_only_constraint': True,
            'entry_price': entry_price, 'stop_loss': stop_loss,
            'risk_per_share': round(risk_per_share, 2),
            'total_capital': total_capital,
            'risk_pct_after_regime_scaling': round(effective_risk_pct, 3),
            'minimum_capital_for_one_share': round(min_capital, 0),
            'reason': (
                f"ACCOUNT SIZE ONLY - this says NOTHING about whether {ticker} is a good setup. "
                f"One share risks Rs{risk_per_share:.2f} to the stop, but Rs{total_capital:,.0f} "
                f"at {effective_risk_pct:.2f}% risk only allows Rs{risk_amount:.2f} of risk. "
                f"You would need about Rs{min_capital:,.0f} to take one share at this risk "
                f"level, or a wider risk % / a stock with a tighter stop. "
                f"Report the setup quality separately and do NOT downgrade the analysis "
                f"because of this number."),
        }

    return {
        'ticker': ticker, 'term': term, 'entry_price': entry_price, 'stop_loss': stop_loss,
        'risk_per_share': round(risk_per_share, 2), 'total_capital': total_capital,
        'risk_pct_requested': risk_pct,
        'risk_pct_after_regime_scaling': round(effective_risk_pct, 3),
        'vol_regime_multiplier': vol_mult, 'vol_regime_note': vol_note,
        # Behavioural flags from the user's own log - relay these verbatim, they are not
        # predictions and must not be presented as reasons the trade will lose.
        'discipline_warnings': discipline['warnings'],
        'shares_to_buy': shares_to_buy, 'position_value': round(position_value, 2),
        'position_pct_of_capital': round((position_value / total_capital) * 100, 2),
        'actual_risk_amount': round(actual_risk_amount, 2),
        'actual_risk_pct': round((actual_risk_amount / total_capital) * 100, 2),
        'target': levels['target'],
        'potential_profit_at_target': round(shares_to_buy * (levels['target'] - entry_price), 2),
        'price_source': price_source_note,
    }


def record_trade_entry(ticker, term, shares, capital_used, risk_pct, entry_price=None):
    levels = get_swing_levels_short(ticker) if term == "short" else get_swing_levels_long(ticker)
    market_regime = None
    regime_note = ""
    if term == "long":
        try:
            market_regime = load_market_breadth_cache().get('regime')
        except Exception as e:
            regime_note = f" (market regime not recorded: {e})"
    trade_id = log_trade_entry(ticker, term, shares, capital_used, risk_pct, levels, market_regime, entry_price)
    return f"Trade logged: {trade_id}. {ticker} entered at ₹{entry_price if entry_price else levels['current_price']}, {shares} shares.{regime_note}"


def record_trade_exit(ticker, exit_price):
    result = log_trade_exit(ticker, exit_price)
    if 'error' in result:
        return result['error']
    return (f"Trade closed: {ticker} - Entry ₹{result['entry_price']} → Exit ₹{result['exit_price']} "
            f"= {result['return_pct']}% return over {result['holding_days']} days ({result['exit_type']}).")

def get_full_analysis(ticker, term="short"):
    parts = []
    parts.append(get_market_regime_text())
    if term == "breakout":
        parts.append(get_snapshot_text_breakout(ticker))
    elif term == "short":
        parts.append(get_snapshot_text_short(ticker))
    else:
        parts.append(get_snapshot_text_long(ticker))
    parts.append(get_fundamentals_text(ticker))
    parts.append(get_institutional_activity_text(ticker))
    parts.append(check_upcoming_results(ticker))
    parts.append(get_recent_announcements_text(ticker))
    return "\n---\n".join(parts)


def normalize_ticker(raw):
    """'reliance' / 'RELIANCE' / 'reliance.ns' -> 'RELIANCE.NS'. Users type tickers casually;
    without this every such message became a cache miss, and a tool erroring out in front of a
    waiting user is exactly where the agent starts inventing facts."""
    t = (raw or '').strip().upper().replace(' ', '')
    if not t:
        return None
    for suffix in ('.NS', '.BO'):
        if t.endswith(suffix):
            return t
    return t + '.NS'


def _levels_any_ticker(ticker):
    """(levels, source). Falls back to a live download for tickers outside the cached universe.

    Returns source='cache' | 'live', or raises with a plain message. It must never return
    silently-empty data - a missing number here is what the agent fills in from its own
    weights.
    """
    try:
        return get_swing_levels_short(ticker), 'cache'
    except Exception:
        pass

    import yfinance as yf
    from features import add_short_features, MIN_BARS
    df = yf.download(ticker, period="2y", interval="1d", progress=False, auto_adjust=True)
    if df is None or len(df) < MIN_BARS:
        raise ValueError(
            f"No usable price history for {ticker}. Either the symbol is wrong or it is not on "
            f"Yahoo Finance. Nothing below is computed - do not guess values for it.")
    if hasattr(df.columns, 'get_level_values'):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    return get_swing_levels_short(ticker, stock_df=add_short_features(df)), 'live'


def _universe_verdict(ticker, levels, source):
    """Says plainly whether the backtested edge covers this setup. The tool previously had no
    way to express 'no opinion', so an out-of-universe stock still got a confident-sounding
    answer assembled from tools that did not apply to it."""
    cap = levels.get('cap_bucket', 'Unknown')
    rsi = levels.get('rsi')
    turn_cr = levels.get('turnover_60d_cr')
    fails = []
    if source == 'live':
        fails.append("not in the backtested universe (fetched live, no cap-tier or model data)")
    if cap not in ('Mid', 'Small'):
        fails.append(f"cap tier is {cap}, and the edge was only demonstrated in Mid/Small")
    if rsi is None or rsi >= 30:
        fails.append(f"RSI is {rsi}, not below 30 - this is not a mean-reversion setup")
    if turn_cr is not None and turn_cr * 1e7 < MIN_TURNOVER_INR:
        fails.append(f"turnover Rs{turn_cr}cr/day is below the Rs{MIN_TURNOVER_INR/1e7:.0f}cr "
                     f"floor, where impact costs exceed the measured edge")
    if cap == 'Mid':
        fails.append("Mid-cap is no longer demonstrated day-clustered (z 1.73)")
    if levels.get('trend_tier') == 'Downtrend':
        fails.append("Downtrend tier no longer clears the random-entry control (z 0.71)")

    if not fails:
        return ("VALIDATED SETUP: this matches the backtested short-term strategy "
                "(RSI<30, Mid/Small, above the liquidity floor). The statistics below apply.\n")
    bullets = "".join(f"  - {f}\n" for f in fails)
    return ("NO BACKTESTED EDGE APPLIES TO THIS SETUP.\n" + bullets +
            "Everything below is REAL DATA about this stock, but it is not a validated signal. "
            "Do not present any expected-value or z-score figure as if it covered this trade, "
            "and do not imply the backtest endorses it.\n")


def evaluate_user_trade(ticker, entry_price=None, shares=None):
    """Evaluates a stock the USER chose, optionally one they have already entered.

    The scan-driven tools all assume the system picked the stock and that the user has no
    position yet. When a user says 'I bought 5 of XYZ at 400' there was previously nowhere to
    put the 400, no path for a ticker outside the cache, and no way to say the strategy has no
    opinion - so the agent improvised. This handles all three explicitly.
    """
    ticker = normalize_ticker(ticker)
    if not ticker:
        return "No ticker given. Tell me the symbol, e.g. 'RELIANCE' or 'RELIANCE.NS'."

    entry_price = parse_number(entry_price)
    shares = parse_number(shares)

    try:
        levels, source = _levels_any_ticker(ticker)
    except Exception as e:
        return f"{ticker}: {e}"

    live = get_live_price(ticker)
    price_now = live if live is not None else levels['current_price']
    price_label = "live" if live is not None else "last close (live quote unavailable)"
    atr = levels['atr']
    atr_ok = atr is not None and pd.notna(atr) and atr > 0

    out = [f"USER-SELECTED TRADE REVIEW - {ticker}", ""]
    out.append(_universe_verdict(ticker, levels, source))
    out.append(f"Price now: Rs{price_now} ({price_label}) | RSI {levels['rsi']} | "
               f"ATR Rs{atr} ({levels['atr_pct']}%) | "
               f"1yr {levels.get('change_1yr_pct')}% [{levels.get('trend_tier')}]")
    if source == 'cache':
        out.append(f"Cap tier: {levels.get('cap_bucket')} | liquidity "
                   f"{levels.get('turnover_60d_cr')}cr/day | "
                   f"round-trip cost {levels.get('round_trip_cost_pct')}%")

    if not atr_ok:
        out.append("\nATR is unavailable for this ticker (insufficient recent data), so stop and "
                   "target levels cannot be computed. Do not guess them.")
    elif entry_price is not None and entry_price > 0:
        pnl = (price_now - entry_price) / entry_price * 100
        stop = entry_price - SHORT_STOP_ATR_MULT * atr
        t1, t2 = entry_price + 2 * atr, entry_price + 3.5 * atr
        rr = (t1 - entry_price) / (entry_price - stop) if entry_price > stop else 0
        out += ["",
                f"AGAINST YOUR ENTRY of Rs{entry_price}:",
                f"  Unrealised: {pnl:+.2f}%",
                f"  Stop ({SHORT_STOP_ATR_MULT:g}xATR from YOUR entry): Rs{round(stop, 2)}  "
                f"({(stop - price_now) / price_now * 100:+.1f}% from here)",
                f"  Target 1 (2xATR): Rs{round(t1, 2)} | Target 2 (3.5xATR): Rs{round(t2, 2)}",
                f"  Reward:risk at target 1: {rr:.2f} : 1"]
        if price_now <= stop:
            out.append("  ALREADY BELOW THE STOP - the validated exit rule says this trade is out.")
        if shares is not None and shares > 0:
            risk = (entry_price - stop) * shares
            out.append(f"  Position: {int(shares)} shares, Rs{round(entry_price * shares, 2)} "
                       f"invested, Rs{round(risk, 2)} at risk to the stop "
                       f"(tell me your capital and I can check that against your risk %).")
    else:
        stop = price_now - SHORT_STOP_ATR_MULT * atr
        out += ["",
                f"IF ENTERING NOW at Rs{price_now}: stop Rs{round(stop, 2)}, "
                f"target 1 Rs{round(price_now + 2 * atr, 2)}, "
                f"target 2 Rs{round(price_now + 3.5 * atr, 2)} "
                f"({SHORT_STOP_ATR_MULT:g}xATR stop, 2x/3.5x ATR targets)"]

    if source == 'cache':
        out += ["", "--- full checklist ---", get_full_analysis(ticker, term="short")]
    else:
        out += ["", f"{ticker} is outside the cached universe, so fundamentals, institutional "
                    f"activity, results calendar and announcements were NOT retrieved. State that "
                    f"they are unavailable rather than describing the company from memory."]
    return "\n".join(out)


def get_catalyst_scan_text(limit=15):
    """UNVALIDATED, informational only - flags stocks with unusual volume, for the agent to then
    check news on. Cannot be backtested (no historical news archive available)."""
    price_cache = load_price_cache_short()
    spikes = []
    for ticker, stock_df in price_cache.items():
        valid = stock_df.dropna(subset=['volume_change'])
        if len(valid) == 0:
            continue
        latest = valid.iloc[-1]
        if latest['volume_change'] > 1.0:  # 100%+ above previous day - a genuinely large spike
            spikes.append({'ticker': ticker, 'volume_change_pct': round(latest['volume_change'] * 100, 1),
                            'price': round(latest['close'], 2)})

    if len(spikes) == 0:
        return "No stocks currently show an unusual volume spike (>100% above prior day)."

    spikes_df = pd.DataFrame(spikes).sort_values('volume_change_pct', ascending=False)
    text = "UNVALIDATED catalyst scan - unusual volume spikes (informational only, not backtested):\n\n"
    for _, row in spikes_df.head(limit).iterrows():
        text += f"{row['ticker']}: Price ₹{row['price']}, Volume +{row['volume_change_pct']}% vs prior day\n"
    text += "\nFor any of these, check news headlines to see if there's a real catalyst behind the volume.\n"
    return text

def exit_verdict(current, stop, target, days_held, horizon):
    """The validated exit rule, as structured data: ('stop'|'target'|'time'|'hold', message).

    Shared by get_exit_check_text and alert_watcher. A second copy of these comparisons living
    in the watcher is how the alert and the on-demand check would eventually disagree about
    whether a position is out.
    """
    if horizon >= LONG_HORIZON_DAYS:   # long-term: fixed stop/target measured harmful (backtest_longterm_exits.py)
        if current <= stop:
            return 'stop', ("STOP HIT - your own stop-loss, not a validated rule: on the momentum basket a fixed "
                            "-8% stop cost -1.5%/trade vs holding ~20 sessions. Your call.")
        if current >= target:
            return 'target', ("TARGET HIT - your own target, not a validated rule: capping momentum winners "
                              "measured slightly negative (-0.24%/trade, not significant). Your call.")
    if current <= stop:
        return 'stop', "EXIT NOW - price has hit/breached your stop-loss (validated rule)."
    if current >= target:
        return 'target', "EXIT NOW - price has hit/exceeded your target (validated rule)."
    if days_held >= horizon:
        return 'time', ("EXIT NOW - holding period expired without hitting stop or target "
                        "(validated time-exit rule).")
    return 'hold', "HOLD - within horizon, no stop/target hit, original setup still intact."


def candidate_band(n):
    """(historical mean net/trade, label) for a day with n candidates. See _COUNT_BANDS."""
    return next((h, l) for cut, h, l in _COUNT_BANDS if n <= cut)


def count_candidates(rsi_threshold=30):
    """Fast count of stocks currently passing the entry filter - no snapshots, no model scoring.

    Used by the alert watcher, which needs the number many times a day and not the detail. May
    differ by a name or two from the full scan, which also drops tickers whose snapshot fails.
    """
    try:
        cache = load_price_cache_short()
    except Exception:
        return None
    n = 0
    for ticker, df in cache.items():
        # Mid/Small only. The concentration bands were measured on that universe, so counting
        # large-caps here would compare today's number against thresholds from a different
        # population - the scan excludes them too.
        if CAP_BUCKET_MAP.get(ticker) not in ('Mid', 'Small'):
            continue
        valid = df.dropna(subset=SHORT_FEATURE_COLUMNS)
        if len(valid) == 0:
            continue
        latest = valid.iloc[-1]
        if latest['rsi'] >= rsi_threshold:
            continue
        turn = latest.get('turnover_60d')
        # Unknown turnover counts as FAILING, matching the scan, which excludes illiquid names.
        if turn is None or pd.isna(turn) or turn < MIN_TURNOVER_INR:
            continue
        n += 1
    return n


def get_exit_check_text():
    positions = check_exit_signals()
    if isinstance(positions, str):
        return positions

    text = "Exit check for open positions:\n\n"
    for pos in positions:
        if 'error' in pos:
            text += f"{pos['ticker']}: {pos['error']}\n\n"
            continue
        try:
            levels = get_swing_levels_short(pos['ticker']) if pos['term'] == 'short' else get_swing_levels_long(pos['ticker'])

            live_price = get_live_price(pos['ticker'])
            current = live_price if live_price is not None else levels['current_price']

            stop = float(pos['stop_loss'])
            target = float(pos['target'])

            text += f"{pos['ticker']} ({pos['term']}, day {pos['days_held']}/{pos['horizon']}): Current ₹{current}, Entry ₹{pos['entry_price']}, Stop ₹{stop}, Target ₹{target}\n"

            code, verdict = exit_verdict(current, stop, target, pos['days_held'], pos['horizon'])
            if code != 'hold':
                text += f"  VERDICT: {verdict}\n"
            else:
                if pos['term'] == 'short' and levels['rsi'] > 60:
                    text += f"  CAUTION (unvalidated, informational only): RSI has risen to {levels['rsi']} - the oversold condition that triggered this trade no longer holds. Still technically HOLD per the validated rule, but momentum may be fading.\n"
                elif pos['term'] == 'long' and not levels.get('in_uptrend', True):
                    text += "  CAUTION (unvalidated, informational only): Price has broken below its uptrend structure (SMA50). Still technically HOLD per the validated rule, but the original setup thesis may be weakening.\n"
                else:
                    text += "  VERDICT: HOLD - within horizon, no stop/target hit, original setup still intact.\n"

                try:
                    vix_df = load_vix_cache()
                    current_vix = vix_df['close'].iloc[-1]
                    vix_20d_avg = vix_df['close'].tail(20).mean()
                    if current_vix > vix_20d_avg * 1.3:
                        text += f"  MARKET CAUTION (unvalidated): VIX has spiked to {current_vix:.1f} (20-day avg {vix_20d_avg:.1f}) - broader market stress has risen meaningfully since typical conditions. Doesn't override your stop/target rule, but worth watching this position more closely than usual.\n"
                except Exception:
                    pass
        except Exception as e:
            text += f"{pos['ticker']}: Could not fetch current data - {e}\n"
        text += "\n"
    return text

def get_announcement_reaction_text(ticker):
    """Shows how price/volume ACTUALLY moved since a stock's most recent significant announcement -
    the objective, real reaction, rather than guessing what an announcement 'should' mean."""
    symbol = ticker.replace(".NS", "")
    try:
        df = load_corp_announcements_cache()
        matches = df[df['symbol'] == symbol].sort_values('sort_date', ascending=False)
        if len(matches) == 0:
            return f"{ticker}: No recent announcements to check reaction against."

        latest = matches.iloc[0]
        ann_date = datetime.strptime(latest['an_dt'].split()[0], '%d-%b-%Y')

        price_cache = load_price_cache_short()
        if ticker not in price_cache:
            return f"{ticker}: Announcement found ({latest['desc']} on {latest['an_dt']}) but no price data to check reaction."

        stock_df = price_cache[ticker]
        stock_df = stock_df[pd.to_datetime(stock_df['date']) >= ann_date]
        if len(stock_df) < 2:
            return f"{ticker}: Announcement ({latest['desc']}, {latest['an_dt']}) too recent - not enough trading days yet to see real reaction."

        price_before = stock_df.iloc[0]['close']
        price_now = stock_df.iloc[-1]['close']
        pct_move = ((price_now - price_before) / price_before) * 100

        text = f"{ticker} reaction since '{latest['desc']}' ({latest['an_dt']}):\n"
        text += f"Price move since announcement: {pct_move:+.1f}%\n"
        text += f"Trading days since: {len(stock_df) - 1}\n"
        text += "This is the market's REAL, observed verdict - not a prediction of what the announcement 'means'. "
        text += "Now check get_snapshot_text or get_full_analysis to see if the CURRENT price action matches your validated entry criteria (RSI<30 short-term, or near-high+uptrend long-term).\n"
        return text
    except Exception as e:
        return f"Reaction data unavailable: {e}"

def get_upcoming_catalysts_scan(days_ahead=7):
    """Proactively scans the WHOLE watchlist for stocks with results/board meetings coming up,
    now attached to real sector-momentum context - so a beginner doesn't need to already know
    which sector a company is in, or whether that sector is currently strong or weak."""
    try:
        df = load_upcoming_results()
        sector_data = load_sector_rs_cache()

        upcoming = []
        for _, row in df.iterrows():
            try:
                result_date = datetime.strptime(row['date'], '%d-%b-%Y')
                days_away = (result_date - datetime.now()).days
                if 0 <= days_away <= days_ahead:
                    ticker = f"{row['symbol']}.NS"
                    sd = sector_data.get(ticker, {})
                    upcoming.append({
                        'symbol': row['symbol'], 'date': row['date'], 'days_away': days_away,
                        'industry': sd.get('industry', 'Unknown'),
                        'sector_momentum_60d': sd.get('sector_avg_momentum_60d'),
                        'stock_momentum_60d': sd.get('stock_momentum_60d'),
                    })
            except Exception:
                continue

        if len(upcoming) == 0:
            return f"No watchlist stocks have results scheduled in the next {days_ahead} days."

        upcoming_df = pd.DataFrame(upcoming).sort_values('days_away')
        text = f"Upcoming catalysts, next {days_ahead} days, WITH sector context (direction is never predictable in advance):\n\n"
        for _, row in upcoming_df.iterrows():
            text += f"{row['symbol']}.NS: Results in {row['days_away']} days ({row['date']})\n"
            text += f"  Sector: {row['industry']}\n"
            if pd.notna(row['sector_momentum_60d']):
                sector_read = "growing" if row['sector_momentum_60d'] > 0 else "declining"
                text += f"  Sector 60-day momentum: {row['sector_momentum_60d']:.1f}% ({sector_read})\n"
                if pd.notna(row['stock_momentum_60d']):
                    vs_sector = "in line with" if abs(row['stock_momentum_60d'] - row['sector_momentum_60d']) < 5 else ("outperforming" if row['stock_momentum_60d'] > row['sector_momentum_60d'] else "underperforming")
                    text += f"  This stock's own momentum: {row['stock_momentum_60d']:.1f}% ({vs_sector} its sector)\n"
            else:
                text += "  Sector momentum data not available for this stock.\n"
            text += "\n"
        text += ("REMINDER: sector trend is context, not a prediction of the specific result. A weak sector "
                 "with a struggling stock ahead of results deserves extra caution; a strong sector with a "
                 "stock already outperforming is a mildly supportive backdrop - neither guarantees the outcome.\n")
        return text
    except Exception as e:
        return f"Upcoming catalysts data unavailable: {e}"

def get_live_price_text(ticker):
    price = get_live_price(ticker)
    if price is None:
        return f"Could not fetch a live price for {ticker} right now."
    return f"{ticker} live price: ₹{price}"

def get_recent_announcements_text(ticker):
    symbol = ticker.replace(".NS", "")
    try:
        df = load_corp_announcements_cache()
        matches = df[df['symbol'] == symbol].sort_values('sort_date', ascending=False)
        if len(matches) == 0:
            return f"{ticker}: No recent corporate announcements in the cached window."
        text = f"{ticker} recent corporate announcements:\n"
        for _, row in matches.head(10).iterrows():
            text += f"  {row['an_dt']}: {row['desc']}\n"
            detail = row.get('attchmntText', '')
            if detail and detail.strip() and detail.strip().lower() != row['desc'].strip().lower():
                text += f"    Detail: {detail}\n"
        text += "(Detail text is directly from the NSE filing when available - real, but sometimes generic. Direction/impact is never predictable in advance.)\n"
        return text
    except Exception as e:
        return f"Announcements data unavailable: {e}"


def get_news_flags(ticker, max_rows=20):
    """UNVALIDATED safety-filter view: screens this stock's cached NSE corporate announcements for
    red-flag events (regulatory action, governance exits, distress/dilution, downgrades, accounting
    concerns) and shows matching filings VERBATIM. Answers 'is this oversold name oversold for a
    reason?' - it is NOT a buy/sell signal, is not backtested, and direction is never predictable."""
    symbol = ticker.replace(".NS", "")
    try:
        df = load_corp_announcements_cache()
    except Exception as e:
        return f"Announcements data unavailable: {e}"
    matches = df[df['symbol'] == symbol].sort_values('sort_date', ascending=False).head(max_rows)
    if len(matches) == 0:
        return f"{ticker}: no cached corporate announcements to screen (cache holds recent filings only)."
    flagged, clear = [], 0
    for _, row in matches.iterrows():
        cats = red_flags_in(f"{row.get('desc') or ''} {row.get('attchmntText') or ''}")
        if cats:
            flagged.append((row, cats))
        else:
            clear += 1
    if not flagged:
        return (f"{ticker}: I read the last {len(matches)} official filings this company sent to the exchange and found "
                f"nothing worrying in them. Note: this only checks NSE filings - it can't see newspaper or analyst news, "
                f"so 'nothing found' is reassuring but not a guarantee it's safe.")
    text = (f"{ticker} - SAFETY CHECK of the company's recent official filings. I flagged the ones below because their "
            f"wording matches known trouble words (fraud, dilution, downgrades, management exits, etc.). This is a "
            f"heads-up to go read them, NOT a prediction of the price:\n\n")
    for row, cats in flagged:
        text += f"  [{' / '.join(cats)}] {row['an_dt']}: {row['desc']}\n"
        detail = (row.get('attchmntText') or '').strip()
        if detail and detail.lower() != str(row['desc']).strip().lower():
            text += f"    Filing text: {detail[:300]}\n"
    text += (f"\n  ({clear} other recent filing(s) looked clean.)\n"
             f"  What to do: open and read the flagged filing before you trust the chart. A stock that has fallen hard "
             f"might have fallen for a real reason (fraud, dilution, insolvency, a downgrade) - if so, the 'it's cheap now' "
             f"bounce you're betting on may not come. When in doubt, skip it.\n")
    return text


def get_significant_announcements_scan():
    try:
        df = load_corp_announcements_cache()
        if len(df) == 0:
            return "No corporate announcements cached for the watchlist in the current window."
        mask = df['desc'].str.lower().apply(lambda d: any(kw in d for kw in HIGH_SIGNAL_ANNOUNCEMENT_KEYWORDS))
        significant = df[mask].sort_values('sort_date', ascending=False)
        if len(significant) == 0:
            return "No high-signal corporate announcements found in the watchlist recently."
        text = "Significant recent announcements (UNVALIDATED, informational only - direction is never predictable):\n\n"
        for _, row in significant.head(30).iterrows():
            text += f"{row['symbol']}.NS: {row['an_dt']} - {row['desc']}\n"
        return text
    except Exception as e:
        return f"Significant announcements scan unavailable: {e}"


TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "scan_watchlist_text_breakout",
        "description": "EXPERIMENTAL (UNVALIDATED) scan for Momentum Breakout setups (VCP / High Tight Base) in Mid/Small-cap stocks. 5-year backtest failed to demonstrate statistical edge (z_paired < 2.0). Informational screening only, not a validated buy signal.",
        "parameters": {"type": "object", "properties": {"limit": {"type": ["number", "string", "object"]}}}
    }},
    {"type": "function", "function": {
        "name": "get_snapshot_text_breakout",
        "description": "Detailed momentum breakout snapshot for ONE stock: pivot trigger, base depth, VCP squeeze ratio, 2R target, and trailing 10 EMA.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string", "description": "NSE ticker with .NS suffix"}}, "required": ["ticker"]}
    }},
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
        "parameters": {"type": "object", "properties": {"limit": {"type": ["number", "string", "object"]}, "rsi_threshold": {"type": ["number", "string", "object"]}}}
    }},
    {"type": "function", "function": {
    "name": "get_live_price_text",
    "description": "Gets the current live price for ONE stock, bypassing any cache - use when the user wants to confirm the exact current price before acting, especially if cache freshness is in question.",
    "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
}},
    {"type": "function", "function": {
        "name": "get_catalyst_scan_text",
        "description": "UNVALIDATED, informational-only scan for stocks with unusual volume spikes (>100% above prior day) across the whole watchlist, regardless of RSI. This is NOT a backtested strategy - no historical news archive exists to test it. Use to find candidates worth checking for real news catalysts, not as a standalone signal.",
        "parameters": {"type": "object", "properties": {"limit": {"type": ["number", "string", "object"]}}}
    }},
    {"type": "function", "function": {
        "name": "scan_watchlist_text_long",
        "description": "Long-term (~1 month) MOMENTUM scan: ranks the liquid Mid/Small universe by 12-month momentum and surfaces the VALIDATED top quartile as a diversified BASKET (2014-2026 monthly: ~+0.75%/month over the universe, z_paired 3.3, survivorship-flattered; hold ~20 sessions, no fixed stop/target - they measured harmful). Buy strength. WARNING: momentum crashes hard periodically - present it as a basket held ~monthly and sized small, NOT a single pick.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": ["number", "string", "object"]},
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
        "name": "record_trade_entry",
        "description": "Logs a real trade entry - freezes the current signal snapshot (RSI, momentum, regime, etc.) permanently for future reference. Call this when the user says they've actually entered/bought a position.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"}, "term": {"type": "string", "enum": ["short", "long"]},
                "shares": {"type": ["number", "string", "object"]}, "capital_used": {"type": ["number", "string", "object"]},
                "risk_pct": {"type": ["number", "string", "object"]}, "entry_price": {"type": ["number", "string", "object"], "description": "Actual fill price if different from current market price"}
            },
            "required": ["ticker", "term", "shares", "capital_used", "risk_pct"]
        }
    }},
    {"type": "function", "function": {
    "name": "get_significant_announcements_scan",
    "description": "Proactively scans the WHOLE watchlist for high-signal corporate announcements (management changes, takeover disclosures, M&A, fundraising) in the last 5 days. UNVALIDATED, informational only - tells you WHAT was announced, never predicts market direction.",
    "parameters": {"type": "object", "properties": {}}
}},
{"type": "function", "function": {
    "name": "get_recent_announcements_text",
    "description": "All recent corporate announcements for ONE specific stock, any category.",
    "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
}},
    {"type": "function", "function": {
        "name": "record_trade_exit",
        "description": "Logs a real trade exit and computes the actual return. Call this when the user says they've sold/closed a position.",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}, "exit_price": {"type": ["number", "string", "object"]}}, "required": ["ticker", "exit_price"]}
    }},
    {"type": "function", "function": {
        "name": "get_open_positions",
        "description": "Lists all currently open logged trades.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "get_similar_past_trades",
        "description": "Retrieves the user's own past closed trades matching a given profile (term, and for long-term, whether it was a validated setup), with honest win rate/return stats. ALWAYS includes explicit sample-size caveats - never overstate confidence from few trades. Use this before finalizing any recommendation to ground it in the user's real personal track record.",
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "enum": ["short", "long"]},
                "validated_setup": {"type": ["boolean", "string"], "description": "Optional, long-term only - filter to only validated setups"}
            },
            "required": ["term"]
        }
    }},
    {"type": "function", "function": {
    "name": "get_announcement_reaction_text",
    "description": "Shows the REAL, observed price/volume reaction since a stock's most recent significant announcement - use this instead of guessing what an announcement means. After checking reaction, always follow up with get_full_analysis to see if the current price now matches a validated entry rule.",
    "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}
    }},
    {"type": "function", "function": {
        "name": "get_exit_check_text",
        "description": "Actively checks all open logged positions against the validated exit rule (stop/target/time-expiry) plus early-warning momentum reversal context. Use whenever the user asks whether to hold or exit, or wants a status check on open trades.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
    "name": "get_upcoming_catalysts_scan",
    "description": "Proactively scans the WHOLE watchlist for stocks with results or board meetings scheduled in the next N days - a 'watch this week' list. Does NOT predict direction of the move, only tells you WHAT is scheduled and WHEN.",
    "parameters": {"type": "object", "properties": {"days_ahead": {"type": ["number", "string", "object"]}}}
}},
    {"type": "function", "function": {
        "name": "get_strategy_health_text",
        "description": "Compares the user's REAL closed trades against the backtested expectation, and runs a CUSUM decay alarm. Use when asked how the strategy is performing, whether it still works, or whether results are on track. Always relay the sample-size caveat and the note about the most recent 12 months.",
        "parameters": {"type": "object", "properties": {"term": {"type": "string", "enum": ["short", "long"]}}}
    }},
    {"type": "function", "function": {
        "name": "evaluate_user_trade",
        "description": (
            "USE THIS whenever the user names a stock THEY are interested in or have already bought, "
            "rather than one the scan surfaced - e.g. 'I bought 5 shares of XYZ at 400', 'what do you "
            "think of ABC', 'is RELIANCE a good buy'. Works for ANY NSE ticker including ones outside "
            "the backtested universe. Pass entry_price and shares whenever the user mentions them. "
            "It states explicitly whether the backtested edge applies to the setup - when it says no "
            "edge applies, relay that clearly and do NOT quote strategy statistics as if they covered "
            "this trade."),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "entry_price": {"type": ["number", "string", "object"],
                                "description": "The user's own entry price, if they gave one."},
                "shares": {"type": ["number", "string", "object"],
                           "description": "Number of shares the user holds or plans to buy, if given."}
            },
            "required": ["ticker"]
        }
    }},
    {"type": "function", "function": {
        "name": "calculate_position_size",
        "description": "Calculates shares to buy given capital and risk %. Will BLOCK and return a warning instead of sizing if risk_pct exceeds 2%, or if the stock has an extreme/parabolic move flag (long-term only) - requires confirmed=true to override after explicitly asking the user. ticker is REQUIRED and must be a real stock symbol - if the user hasn't named a specific stock, scan first to find one before calling this.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"}, "total_capital": {"type": ["number", "string", "object"]},
                "risk_pct": {"type": ["number", "string", "object"]}, "term": {"type": "string", "enum": ["short", "long"]},
                "confirmed": {"type": ["boolean", "string"], "description": "Set to true only after the user has explicitly confirmed they want to proceed despite a warning."}
            },
            "required": ["ticker", "total_capital"]
        }
    }},
]


def execute_tool(function_name, function_args):
    if function_name == "scan_watchlist_text_breakout":
        limit = int(parse_number(function_args.get('limit', 10), default=10))
        return scan_watchlist_text_breakout(limit)
    elif function_name == "get_snapshot_text_breakout":
        return get_snapshot_text_breakout(function_args['ticker'])
    elif function_name == "get_snapshot_text_short":
        return get_snapshot_text_short(function_args['ticker'])
    elif function_name == "get_snapshot_text_long":
        return get_snapshot_text_long(function_args['ticker'])
    elif function_name == "get_full_analysis":
        return get_full_analysis(function_args['ticker'], function_args.get('term', 'breakout'))
    elif function_name == "scan_watchlist_text_short":
        limit = int(parse_number(function_args.get('limit', 30), default=30))
        rsi_threshold = parse_number(function_args.get('rsi_threshold', 30), default=30)
        return scan_watchlist_text_short(limit, rsi_threshold)
    elif function_name == "scan_watchlist_text_long":
        limit = int(parse_number(function_args.get('limit', 30), default=30))
        return scan_watchlist_text_long_momentum(limit)
    elif function_name == "get_catalyst_scan_text":
        limit = int(parse_number(function_args.get('limit', 15), default=15))
        return get_catalyst_scan_text(limit)
    elif function_name == "record_trade_entry":
        return record_trade_entry(
            function_args['ticker'], function_args['term'],
            int(parse_number(function_args['shares'])), parse_number(function_args['capital_used']),
            parse_number(function_args['risk_pct']), parse_number(function_args.get('entry_price'))
        )
    elif function_name == "get_significant_announcements_scan":
        return get_significant_announcements_scan()
    elif function_name == "get_recent_announcements_text":
        return get_recent_announcements_text(function_args['ticker'])
    elif function_name == "get_live_price_text":
        return get_live_price_text(function_args['ticker'])
    elif function_name == "record_trade_exit":
        return record_trade_exit(function_args['ticker'], parse_number(function_args['exit_price']))
    elif function_name == "get_open_positions":
        return get_open_positions()
    elif function_name == "get_similar_past_trades":
        vs = function_args.get('validated_setup')
        vs = parse_bool(vs) if vs is not None else None
        return get_similar_past_trades(function_args['term'], vs)
    elif function_name == "get_fundamentals_text":
        return get_fundamentals_text(function_args['ticker'])
    elif function_name == "get_institutional_activity_text":
        return get_institutional_activity_text(function_args['ticker'])
    elif function_name == "get_announcement_reaction_text":
        return get_announcement_reaction_text(function_args['ticker'])
    elif function_name == "get_upcoming_catalysts_scan":
        days_ahead = int(parse_number(function_args.get('days_ahead', 7), default=7))
        return get_upcoming_catalysts_scan(days_ahead)
    elif function_name == "get_exit_check_text":
        return get_exit_check_text()
    elif function_name == "get_market_regime_text":
        return get_market_regime_text()
    elif function_name == "check_upcoming_results":
        return check_upcoming_results(function_args['ticker'])
    elif function_name == "get_strategy_health_text":
        return get_strategy_health(function_args.get('term', 'short'))
    elif function_name == "evaluate_user_trade":
        return evaluate_user_trade(
            function_args.get('ticker', ''),
            parse_number(function_args.get('entry_price')),
            parse_number(function_args.get('shares')))
    elif function_name == "calculate_position_size":
        confirmed = parse_bool(function_args.get('confirmed', False), default=False)
        total_capital = parse_number(function_args.get('total_capital'), default=DEFAULT_CAPITAL)
        risk_pct = parse_number(function_args.get('risk_pct', DEFAULT_RISK_PCT), default=DEFAULT_RISK_PCT)
        pos = calculate_position_size(function_args.get('ticker', ''), total_capital, risk_pct, function_args.get('term', 'short'), confirmed)
        return json.dumps(pos, indent=2)
    return "Unknown function"