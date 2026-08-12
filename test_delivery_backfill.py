"""Self-check: update_delivery_history backfills missed trading days, not just today.

Regression guard for the bug where a single failed daily fetch stranded the delivery
history behind (it only ever asked NSE for 'today'). No network - NSE is mocked.
"""
import os
import pickle
import tempfile
from datetime import datetime, timedelta

import pandas as pd
from nselib import capital_market

import cache_manager as cm


def _fake_bhav(available_dates):
    """Returns a bhav_copy stub that only 'has data' for dates in `available_dates`."""
    def _inner(trade_date):
        if trade_date not in available_dates:
            raise Exception(f"Data not found for {trade_date}")
        return pd.DataFrame({'SYMBOL': ['RELIANCE', 'TCS'], 'DELIV_PER': [55.0, 60.0]})
    return _inner


def test_backfills_gap():
    tickers = ['RELIANCE.NS', 'TCS.NS']
    today = datetime.now()
    d = lambda n: (today - timedelta(days=n)).strftime('%d-%m-%Y')

    with tempfile.TemporaryDirectory() as tmp:
        cm.DELIVERY_HISTORY_FILE = os.path.join(tmp, "delivery_history.pkl")

        # Seed history that stops 3 days ago (the "stranded" state).
        seed = pd.DataFrame({'SYMBOL': ['RELIANCE'], 'DELIV_PER': [50.0], 'DATE_FETCHED': [d(3)]})
        with open(cm.DELIVERY_HISTORY_FILE, 'wb') as f:
            pickle.dump(seed, f)

        # NSE now has today, yesterday, and 2 days ago published.
        capital_market.bhav_copy_with_delivery = _fake_bhav({d(0), d(1), d(2), d(3)})

        result = cm.update_delivery_history(tickers, keep_days=30)

        dates = set(result['DATE_FETCHED'].unique())
        # The 3-day gap (0,1,2) must now be filled, seed day retained.
        assert d(0) in dates, "today not backfilled"
        assert d(1) in dates, "yesterday not backfilled"
        assert d(2) in dates, "2-days-ago not backfilled"
        assert d(3) in dates, "seed day lost"
        # Existing day must not be duplicated.
        assert (result['DATE_FETCHED'] == d(3)).sum() == 1, "seed day duplicated"


def test_no_new_data_returns_existing():
    tickers = ['RELIANCE.NS']
    today = datetime.now()
    d = lambda n: (today - timedelta(days=n)).strftime('%d-%m-%Y')

    with tempfile.TemporaryDirectory() as tmp:
        cm.DELIVERY_HISTORY_FILE = os.path.join(tmp, "delivery_history.pkl")
        seed = pd.DataFrame({'SYMBOL': ['RELIANCE'], 'DELIV_PER': [50.0], 'DATE_FETCHED': [d(1)]})
        with open(cm.DELIVERY_HISTORY_FILE, 'wb') as f:
            pickle.dump(seed, f)

        capital_market.bhav_copy_with_delivery = _fake_bhav({d(1)})  # nothing new to fetch
        result = cm.update_delivery_history(tickers)
        assert set(result['DATE_FETCHED'].unique()) == {d(1)}, "should return existing untouched"


if __name__ == "__main__":
    test_backfills_gap()
    test_no_new_data_returns_existing()
    print("OK: delivery backfill self-check passed")
