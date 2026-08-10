import pandas as pd
import numpy as np
import os
from datetime import datetime
from config import (SHORT_HORIZON_DAYS, LONG_HORIZON_DAYS, MAX_OPEN_POSITIONS,
                    REVENGE_WINDOW_DAYS, LOSS_STREAK_LENGTH)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADE_LOG_FILE = os.path.join(BASE_DIR, "trade_log.csv")

COLUMNS = [
    'trade_id', 'ticker', 'term', 'entry_date', 'entry_price', 'stop_loss', 'target',
    'shares', 'capital_used', 'risk_pct',
    'rsi_at_entry', 'model_signal_at_entry', 'volume_spike_at_entry',
    'momentum_60d_at_entry', 'validated_setup_at_entry', 'extreme_momentum_at_entry',
    'relative_strength_nifty_at_entry', 'sector_relative_strength_at_entry', 'market_regime_at_entry',
    'status', 'exit_date', 'exit_price', 'exit_type', 'return_pct', 'holding_days'
]


def _parse_date(value):
    """Accepts both ISO (2026-07-06) and M/D/YYYY (7/6/2026, from a spreadsheet round-trip)."""
    return pd.to_datetime(value, errors='coerce')


def _load_log():
    if not os.path.exists(TRADE_LOG_FILE) or os.path.getsize(TRADE_LOG_FILE) == 0:
        return pd.DataFrame(columns=COLUMNS, dtype=object)
    df = pd.read_csv(TRADE_LOG_FILE, dtype=object)
    df = df.reindex(columns=COLUMNS)
    for col in ('entry_date', 'exit_date'):
        parsed = _parse_date(df[col])
        df[col] = parsed.dt.strftime('%Y-%m-%d').where(parsed.notna(), df[col])
    return df

def _save_log(df):
    df.to_csv(TRADE_LOG_FILE, index=False)


def log_trade_entry(ticker, term, shares, capital_used, risk_pct, levels, market_regime=None,
                    entry_price=None, entry_date=None):
    """entry_date (YYYY-MM-DD) backdates a trade that was taken days ago. Without it the row is
    stamped today, which silently corrupts days-held and therefore the time-exit rule."""
    df = _load_log()

    live_price = None
    try:
        from data_fetcher import get_live_price
        live_price = get_live_price(ticker)
    except Exception:
        pass

    reference_price = live_price if live_price is not None else levels['current_price']

    # The sanity check compares against TODAY's price, which is only meaningful for a trade
    # entered today. A backdated entry legitimately differs from the current price.
    if entry_price is not None and reference_price is not None and entry_date is None:
        if abs(entry_price - reference_price) / reference_price > 0.15:
            # Provided entry_price is wildly off from real price - almost certainly an error, ignore it
            entry_price = None

    actual_entry_price = entry_price if entry_price is not None else reference_price
    trade_id = f"{ticker}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    row = {col: None for col in COLUMNS}
    row.update({
        'trade_id': trade_id,
        'ticker': ticker,
        'term': term,
        'entry_date': entry_date or datetime.now().strftime('%Y-%m-%d'),
        'entry_price': actual_entry_price,
        'stop_loss': levels.get('stop_loss'),
        'target': levels.get('target'),
        'shares': shares,
        'capital_used': capital_used,
        'risk_pct': risk_pct,
        'rsi_at_entry': levels.get('rsi'),
        'model_signal_at_entry': levels.get('model_signal_pct'),
        'status': 'open',
    })

    if term == 'short':
        row['volume_spike_at_entry'] = levels.get('volume_spike')
    else:
        row['momentum_60d_at_entry'] = levels.get('momentum_60d_pct')
        row['validated_setup_at_entry'] = levels.get('validated_setup')
        row['extreme_momentum_at_entry'] = levels.get('extreme_momentum')
        row['relative_strength_nifty_at_entry'] = levels.get('relative_strength_pct')
        row['sector_relative_strength_at_entry'] = levels.get('sector_relative_strength')
        row['market_regime_at_entry'] = market_regime

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _save_log(df)
    return trade_id


def log_trade_exit(ticker, exit_price):
    df = _load_log()
    open_trades = df[(df['ticker'] == ticker) & (df['status'] == 'open')]

    if len(open_trades) == 0:
        return {'error': f"No open trade found for {ticker}. Did you log the entry first?"}

    idx = _parse_date(open_trades['entry_date']).sort_values().index[-1]
    row = df.loc[idx]

    entry_price = float(row['entry_price'])
    stop_loss = float(row['stop_loss']) if pd.notna(row['stop_loss']) else None
    target = float(row['target']) if pd.notna(row['target']) else None

    return_pct = ((exit_price - entry_price) / entry_price) * 100
    entry_date = _parse_date(row['entry_date'])
    holding_days = int(np.busday_count(entry_date.date(), datetime.now().date())) if pd.notna(entry_date) else None

    if stop_loss is not None and exit_price <= stop_loss * 1.01:
        exit_type = 'stop_loss'
    elif target is not None and exit_price >= target * 0.99:
        exit_type = 'target'
    else:
        exit_type = 'manual_exit'

    df.loc[idx, 'status'] = 'closed'
    df.loc[idx, 'exit_date'] = datetime.now().strftime('%Y-%m-%d')
    df.loc[idx, 'exit_price'] = exit_price
    df.loc[idx, 'exit_type'] = exit_type
    df.loc[idx, 'return_pct'] = round(return_pct, 2)
    df.loc[idx, 'holding_days'] = holding_days

    _save_log(df)
    return {
        'ticker': ticker, 'entry_price': entry_price, 'exit_price': exit_price,
        'return_pct': round(return_pct, 2), 'exit_type': exit_type, 'holding_days': holding_days
    }

def get_open_positions():
    df = _load_log()
    open_df = df[df['status'] == 'open']
    if len(open_df) == 0:
        return "No open positions currently logged."
    text = "Open positions:\n"
    for _, row in open_df.iterrows():
        text += f"  {row['ticker']} ({row['term']}) - entered {row['entry_date']} @ ₹{row['entry_price']}, {row['shares']} shares\n"
    return text


def discipline_check(ticker, risk_pct=None):
    """Behavioural guardrails read off the user's OWN trade log.

    Deliberately makes no claim about future prices - these constrain the trader, not the
    trade, which is why they carry no backtest. Every message says what the user actually did,
    so it can be argued with rather than obeyed blindly.

    Returns {'blocks': [...], 'warnings': [...]}. Blocks are overridable with confirmed=true,
    matching the existing risk gates.
    """
    out = {'blocks': [], 'warnings': []}
    try:
        df = _load_log()
    except Exception:
        return out
    if len(df) == 0:
        return out

    ticker = (ticker or '').strip().upper()
    open_df = df[df['status'] == 'open']

    # Adding to a position the plan never said to add to. The validated strategy enters once
    # and exits on stop/target/time - there is no pyramiding or averaging-down rule in it.
    same = open_df[open_df['ticker'].str.upper() == ticker] if len(open_df) else open_df
    if len(same) > 0:
        row = same.iloc[0]
        out['blocks'].append(
            f"You already hold {ticker} - entered {row['entry_date']} at Rs{row['entry_price']}, "
            f"{row['shares']} shares. Buying more is averaging down or pyramiding, and neither "
            f"is part of the tested plan (one entry, exit on stop/target/time). If this is "
            f"deliberate, say so and I will size it.")

    if len(open_df) >= MAX_OPEN_POSITIONS:
        out['warnings'].append(
            f"{len(open_df)} positions already open (your discipline limit is "
            f"{MAX_OPEN_POSITIONS}). Each new name adds correlated exposure - oversold NSE "
            f"mid/smallcaps tend to fall together.")

    closed = df[df['status'] == 'closed'].copy()
    if len(closed) == 0:
        return out
    closed['_exit'] = closed['exit_date'].apply(_parse_date)
    closed = closed.dropna(subset=['_exit']).sort_values('_exit')

    # Revenge re-entry: the same name that just stopped you out.
    recent_stops = closed[
        (closed['ticker'].str.upper() == ticker)
        & (closed['exit_type'].astype(str).str.contains('stop', case=False, na=False))
        & (closed['_exit'] >= datetime.now() - pd.Timedelta(days=REVENGE_WINDOW_DAYS))]
    if len(recent_stops) > 0:
        r = recent_stops.iloc[-1]
        out['warnings'].append(
            f"{ticker} stopped you out on {r['exit_date']} ({r['return_pct']}%), within the last "
            f"{REVENGE_WINDOW_DAYS} days. Re-entering a name that just hurt you is the classic "
            f"revenge trade - it may still be a valid setup, but say why it is different now.")

    # Size creep after losses.
    last = closed.tail(LOSS_STREAK_LENGTH)
    if len(last) == LOSS_STREAK_LENGTH and (pd.to_numeric(last['return_pct'], errors='coerce') < 0).all():
        out['warnings'].append(
            f"Your last {LOSS_STREAK_LENGTH} closed trades were all losses "
            f"({', '.join(f'{v}%' for v in last['return_pct'])}). Nothing says the next one is "
            f"more likely to lose - but this is exactly when size creeps up to 'win it back'. "
            f"Consider trading smaller, not larger.")

    if risk_pct is not None:
        hist = pd.to_numeric(closed['risk_pct'], errors='coerce').dropna()
        if len(hist) >= 5 and risk_pct > hist.median() * 1.5:
            out['warnings'].append(
                f"Requested risk {risk_pct}% is well above your own historical median of "
                f"{hist.median():.2f}% across {len(hist)} logged trades. Deliberate, or drift?")
    return out


def get_similar_past_trades(term, validated_setup=None):
    df = _load_log()
    closed = df[(df['status'] == 'closed') & (df['term'] == term)].copy()

    if validated_setup is not None and term == 'long':
        target_str = str(validated_setup)
        closed = closed[closed['validated_setup_at_entry'].astype(str) == target_str]

    count = len(closed)
    if count == 0:
        return f"No past closed trades yet matching this profile (term={term}). This will be your first data point."

    closed['return_pct'] = pd.to_numeric(closed['return_pct'], errors='coerce')
    win_rate = (closed['return_pct'] > 0).mean() * 100
    avg_return = closed['return_pct'].mean()

    if count < 10:
        confidence_note = f"⚠️ Only {count} past trade(s) match this profile - this is anecdotal, NOT statistically meaningful yet. Do not treat this as a reliable pattern."
    elif count < 30:
        confidence_note = f"Only {count} past trades match this profile - an early signal at best, still fairly noisy. Treat with caution."
    else:
        confidence_note = f"{count} past trades match this profile - a reasonably sized personal sample."

    text = f"Your past trades matching this profile (term={term}"
    text += f", validated_setup={validated_setup}" if validated_setup is not None else ""
    text += f"):\n\nCount: {count}\nWin rate: {win_rate:.1f}%\nAverage return: {avg_return:.2f}%\n\n{confidence_note}\n\n"
    text += "Individual trades:\n"
    for _, row in closed.sort_values('entry_date').iterrows():
        text += f"  {row['ticker']} ({row['entry_date']}): {row['return_pct']}% ({row['exit_type']})\n"
    return text

def get_strategy_health(term='short'):
    """Compares your REAL closed trades against what the backtest says to expect.

    The gap between the two is your true cost model, measured rather than assumed - it
    captures slippage, timing and execution that no backtest can know in advance.
    """
    from config import GROSS_EDGE_SHORT_PCT, GROSS_EDGE_LONG_PCT, ROUND_TRIP_COST_PCT
    from decay_monitor import cusum

    df = _load_log()
    closed = df[(df['status'] == 'closed') & (df['term'] == term)].copy()
    closed['return_pct'] = pd.to_numeric(closed['return_pct'], errors='coerce')
    closed = closed[closed['return_pct'].notna()]
    closed = closed.iloc[_parse_date(closed['entry_date']).argsort()]  # chronological

    gross = GROSS_EDGE_SHORT_PCT if term == 'short' else GROSS_EDGE_LONG_PCT
    expected = gross - ROUND_TRIP_COST_PCT
    n = len(closed)
    if n == 0:
        return (f"No closed {term}-term trades logged yet. Expected net is {expected:+.2f}%/trade "
                f"once you have a track record to compare against.")

    realised = closed['return_pct'].astype(float)
    text = (f"Strategy health, {term}-term ({n} closed trade(s)):\n"
            f"  expected net/trade (backtest): {expected:+.2f}%\n"
            f"  your realised net/trade      : {realised.mean():+.2f}%\n"
            f"  gap (execution + slippage)   : {realised.mean() - expected:+.2f}%\n")

    if n < 30:
        text += (f"  ⚠️ {n} trades is far too few to judge anything. At least ~30 closed trades are "
                 f"needed before the gap or any decay signal means much.\n")
    else:
        cu = cusum(realised.values, expected_mean=expected)
        text += (f"  decay alarm: {'RAISED' if cu['alarm'] else 'not raised'} "
                 f"({cu['pct_of_threshold']:.0f}% of trigger)\n")
        if cu['alarm']:
            text += ("  ⚠️ Realised returns have fallen persistently below expectation. Review before "
                     "adding new positions.\n")
    text += ("\nSeparately, the 5-year backtest shows the edge was NOT detectable in the most recent "
             "12 months (the random-entry control fell too, so it may be a hard market rather than a "
             "broken signal - one period cannot tell). Size accordingly.\n")
    return text


def check_exit_signals():
    """Checks every open position against the validated exit rule (stop/target/time) plus early-warning context."""
    df = _load_log()
    open_trades = df[df['status'] == 'open']
    if len(open_trades) == 0:
        return "No open positions to check."

    results = []
    for _, row in open_trades.iterrows():
        ticker = row['ticker']
        term = row['term']
        entry_date = _parse_date(row['entry_date'])
        if pd.isna(entry_date):
            results.append({'ticker': ticker, 'term': term, 'error': f"Unparseable entry_date: {row['entry_date']!r}"})
            continue
        days_held = int(np.busday_count(entry_date.date(), datetime.now().date()))
        horizon = SHORT_HORIZON_DAYS if term == 'short' else LONG_HORIZON_DAYS

        results.append({
            'ticker': ticker, 'term': term, 'days_held': days_held, 'horizon': horizon,
            'entry_price': row['entry_price'], 'stop_loss': row['stop_loss'], 'target': row['target'],
        })
    return results