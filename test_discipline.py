"""Offline checks for the discipline layer (no network, no real trade log).

These guardrails read the user's own history, so the thing that matters is that they fire on
the right ticker and stay silent on the wrong one - a warning attached to the wrong stock is
worse than no warning.
"""
from datetime import datetime, timedelta

import pandas as pd

import trade_journal as tj
from config import MAX_OPEN_POSITIONS, REVENGE_WINDOW_DAYS, LOSS_STREAK_LENGTH


def _with_log(rows):
    df = pd.DataFrame(rows).reindex(columns=tj.COLUMNS)
    tj._load_log = lambda: df


def _closed(ticker, ret, exit_type, days_ago, risk_pct=1):
    return {'ticker': ticker, 'status': 'closed', 'return_pct': ret, 'exit_type': exit_type,
            'risk_pct': risk_pct,
            'exit_date': (datetime.now() - timedelta(days=days_ago)).strftime('%m/%d/%Y')}


def _open(ticker):
    return {'ticker': ticker, 'status': 'open', 'entry_date': '1/7/2026',
            'entry_price': 100, 'shares': 10, 'risk_pct': 1}


def test_empty_log_is_silent():
    _with_log([])
    d = tj.discipline_check('ANY.NS', 2)
    assert d == {'blocks': [], 'warnings': []}


def test_existing_position_blocks_only_that_ticker():
    _with_log([_open('AAA.NS')])
    assert tj.discipline_check('AAA.NS', 1)['blocks'], "adding to an open position must block"
    assert not tj.discipline_check('BBB.NS', 1)['blocks'], "block leaked onto another ticker"
    assert tj.discipline_check('aaa.ns', 1)['blocks'], "ticker match must be case-insensitive"


def test_open_position_limit():
    _with_log([_open(f'T{i}.NS') for i in range(MAX_OPEN_POSITIONS)])
    assert any('positions already open' in w for w in tj.discipline_check('NEW.NS', 1)['warnings'])
    _with_log([_open(f'T{i}.NS') for i in range(MAX_OPEN_POSITIONS - 1)])
    assert not any('positions already open' in w
                   for w in tj.discipline_check('NEW.NS', 1)['warnings'])


def test_revenge_window_is_bounded_by_ticker_and_time():
    _with_log([_closed('AAA.NS', -3.0, 'stop_loss', 2)])
    assert any('revenge' in w for w in tj.discipline_check('AAA.NS', 1)['warnings'])
    assert not any('revenge' in w for w in tj.discipline_check('BBB.NS', 1)['warnings'])

    _with_log([_closed('AAA.NS', -3.0, 'stop_loss', REVENGE_WINDOW_DAYS + 5)])
    assert not any('revenge' in w for w in tj.discipline_check('AAA.NS', 1)['warnings']), \
        "an old stop-out should no longer count as revenge"

    _with_log([_closed('AAA.NS', 4.0, 'target', 2)])
    assert not any('revenge' in w for w in tj.discipline_check('AAA.NS', 1)['warnings']), \
        "a winning exit is not a revenge trade"


def test_loss_streak_needs_all_losses():
    _with_log([_closed('A.NS', -1.0, 'time_exit', 9), _closed('B.NS', -2.0, 'stop_loss', 6),
               _closed('C.NS', -1.5, 'stop_loss', 3)][:LOSS_STREAK_LENGTH])
    assert any('all losses' in w for w in tj.discipline_check('NEW.NS', 1)['warnings'])

    _with_log([_closed('A.NS', -1.0, 'time_exit', 9), _closed('B.NS', +2.0, 'target', 6),
               _closed('C.NS', -1.5, 'stop_loss', 3)])
    assert not any('all losses' in w for w in tj.discipline_check('NEW.NS', 1)['warnings']), \
        "a win inside the window must break the streak"


def test_risk_creep_needs_enough_history():
    small = [_closed(f'T{i}.NS', 1.0, 'target', 30 + i, risk_pct=1) for i in range(4)]
    _with_log(small)
    assert not any('historical median' in w for w in tj.discipline_check('NEW.NS', 5)['warnings']), \
        "must not lecture on 4 trades of history"
    _with_log(small + [_closed('T9.NS', 1.0, 'target', 40, risk_pct=1)])
    assert any('historical median' in w for w in tj.discipline_check('NEW.NS', 5)['warnings'])
    assert not any('historical median' in w for w in tj.discipline_check('NEW.NS', 1)['warnings'])


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
    print("discipline layer: OK")
