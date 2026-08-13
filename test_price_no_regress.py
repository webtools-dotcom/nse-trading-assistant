"""Self-check: the price cache never regresses to older data.

Guards the '10pm refresh pulls 2-day-old prices and clobbers good closes' bug.
No network.
"""
import os
import pickle
import tempfile

import pandas as pd

import cache_manager as cm


def _cache(date_str):
    return {'RELIANCE.NS': pd.DataFrame({'date': pd.to_datetime(['2026-08-01', date_str]),
                                         'close': [1300.0, 1329.0]})}


def test_stale_pull_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "short.pkl")
        with open(f, 'wb') as fh:
            pickle.dump(_cache('2026-08-13'), fh)  # good data already cached

        # A later refresh pulls a snapshot missing the newest bar (Yahoo lag).
        returned = cm._save_price_cache_no_regress(_cache('2026-08-11'), f, "short-term")

        assert cm._newest_bar_date(returned) == pd.Timestamp('2026-08-13'), "stale pull overwrote good data"
        with open(f, 'rb') as fh:
            on_disk = pickle.load(fh)
        assert cm._newest_bar_date(on_disk) == pd.Timestamp('2026-08-13'), "disk cache regressed"


def test_fresher_pull_is_saved():
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "short.pkl")
        with open(f, 'wb') as fh:
            pickle.dump(_cache('2026-08-13'), fh)

        cm._save_price_cache_no_regress(_cache('2026-08-14'), f, "short-term")
        with open(f, 'rb') as fh:
            on_disk = pickle.load(fh)
        assert cm._newest_bar_date(on_disk) == pd.Timestamp('2026-08-14'), "fresh pull not saved"


def test_same_day_update_is_saved():
    # 4pm partial bar -> 10pm final bar: same date, must still overwrite.
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "short.pkl")
        with open(f, 'wb') as fh:
            pickle.dump(_cache('2026-08-13'), fh)
        final = {'RELIANCE.NS': pd.DataFrame({'date': pd.to_datetime(['2026-08-01', '2026-08-13']),
                                              'close': [1300.0, 1350.0]})}
        cm._save_price_cache_no_regress(final, f, "short-term")
        with open(f, 'rb') as fh:
            on_disk = pickle.load(fh)
        assert on_disk['RELIANCE.NS']['close'].iloc[-1] == 1350.0, "same-day final not applied"


if __name__ == "__main__":
    test_stale_pull_is_rejected()
    test_fresher_pull_is_saved()
    test_same_day_update_is_saved()
    print("OK: price no-regress self-check passed")
