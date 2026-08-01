"""Self-check for the date/sort/exit bugs fixed in trade_journal.py. Run directly: python test_trade_journal.py"""
import os
import tempfile
import pandas as pd
import trade_journal as tj


def test_parse_date_handles_both_formats():
    assert tj._parse_date("7/6/2026") == pd.Timestamp("2026-07-06")
    assert tj._parse_date("2026-07-06") == pd.Timestamp("2026-07-06")
    assert pd.isna(tj._parse_date("not a date"))


def test_load_log_missing_and_empty_file():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "trade_log.csv")
        tj.TRADE_LOG_FILE = path
        df = tj._load_log()
        assert list(df.columns) == tj.COLUMNS
        assert len(df) == 0

        open(path, "w").close()  # zero-byte file
        df = tj._load_log()
        assert len(df) == 0


def test_latest_open_trade_sorts_by_real_date_not_string():
    with tempfile.TemporaryDirectory() as d:
        tj.TRADE_LOG_FILE = os.path.join(d, "trade_log.csv")
        df = pd.DataFrame([
            {**{c: None for c in tj.COLUMNS}, 'trade_id': 'A', 'ticker': 'X.NS', 'term': 'short',
             'entry_date': '7/6/2026', 'entry_price': 100, 'stop_loss': 90, 'target': 120, 'status': 'open'},
            {**{c: None for c in tj.COLUMNS}, 'trade_id': 'B', 'ticker': 'X.NS', 'term': 'short',
             'entry_date': '7/13/2026', 'entry_price': 110, 'stop_loss': 95, 'target': 130, 'status': 'open'},
        ])
        tj._save_log(df)

        result = tj.log_trade_exit('X.NS', 115)
        # '7/13/2026' is the later date; string-sort would have picked '7/6/2026' instead.
        assert result['entry_price'] == 110, f"expected the later trade (B, entry 110), got entry_price={result['entry_price']}"


def test_check_exit_signals_skips_unparseable_date_instead_of_crashing():
    with tempfile.TemporaryDirectory() as d:
        tj.TRADE_LOG_FILE = os.path.join(d, "trade_log.csv")
        df = pd.DataFrame([
            {**{c: None for c in tj.COLUMNS}, 'trade_id': 'A', 'ticker': 'X.NS', 'term': 'short',
             'entry_date': 'garbage', 'entry_price': 100, 'stop_loss': 90, 'target': 120, 'status': 'open'},
        ])
        tj._save_log(df)
        results = tj.check_exit_signals()
        assert results[0]['error']


if __name__ == "__main__":
    test_parse_date_handles_both_formats()
    test_load_log_missing_and_empty_file()
    test_latest_open_trade_sorts_by_real_date_not_string()
    test_check_exit_signals_skips_unparseable_date_instead_of_crashing()
    print("test_trade_journal.py: all checks passed")
