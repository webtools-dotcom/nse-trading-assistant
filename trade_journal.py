import pandas as pd
import os
from datetime import datetime

TRADE_LOG_FILE = "trade_log.csv"

COLUMNS = [
    'trade_id', 'ticker', 'term', 'entry_date', 'entry_price', 'stop_loss', 'target',
    'shares', 'capital_used', 'risk_pct',
    'rsi_at_entry', 'model_signal_at_entry', 'volume_spike_at_entry',
    'momentum_60d_at_entry', 'validated_setup_at_entry', 'extreme_momentum_at_entry',
    'relative_strength_nifty_at_entry', 'sector_relative_strength_at_entry', 'market_regime_at_entry',
    'status', 'exit_date', 'exit_price', 'exit_type', 'return_pct', 'holding_days'
]


def _load_log():
    if not os.path.exists(TRADE_LOG_FILE):
        return pd.DataFrame(columns=COLUMNS, dtype=object)
    return pd.read_csv(TRADE_LOG_FILE, dtype=object)

def _save_log(df):
    df.to_csv(TRADE_LOG_FILE, index=False)


def log_trade_entry(ticker, term, shares, capital_used, risk_pct, levels, market_regime=None, entry_price=None):
    """Freezes the current signal snapshot (already computed by tools.py) into a new open trade row."""
    df = _load_log()

    actual_entry_price = entry_price if entry_price is not None else levels['current_price']
    trade_id = f"{ticker}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    row = {col: None for col in COLUMNS}
    row.update({
        'trade_id': trade_id,
        'ticker': ticker,
        'term': term,
        'entry_date': datetime.now().strftime('%Y-%m-%d'),
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

    idx = open_trades.sort_values('entry_date').index[-1]
    row = df.loc[idx]

    entry_price = float(row['entry_price'])
    stop_loss = float(row['stop_loss']) if pd.notna(row['stop_loss']) else None
    target = float(row['target']) if pd.notna(row['target']) else None

    return_pct = ((exit_price - entry_price) / entry_price) * 100
    entry_date = datetime.strptime(row['entry_date'], '%Y-%m-%d')
    holding_days = (datetime.now() - entry_date).days

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