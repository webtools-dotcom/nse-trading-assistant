"""Offline checks for the Catalyst-Fueled Momentum Breakout & Swing Engine."""
import pandas as pd
import numpy as np
import tools
from features import add_short_features


def _fake_stock_df():
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    # Upward trending series with a tight base at the end
    close = 100 + np.linspace(0, 50, 120)
    # last 5 bars tight consolidation
    close[-5:] = [148.0, 149.0, 148.5, 149.5, 150.0]
    high = close + 1.5
    low = close - 1.5
    volume = [2000000] * 120
    volume[-1] = 5000000  # volume expansion on last bar
    df = pd.DataFrame({
        'date': dates,
        'open': close,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    })
    return add_short_features(df)


def test_breakout_levels_calculation():
    df = _fake_stock_df()
    levels = tools.get_breakout_levels("FAKE.NS", stock_df=df)
    
    assert levels['trigger_entry'] > levels['hard_stop'], "Trigger entry must be above hard stop"
    assert levels['risk_per_share'] > 0, "Risk per share must be positive"
    assert levels['target_2r'] > levels['trigger_entry'], "Target 2R must be above entry"
    assert levels['target_2r'] == round(levels['trigger_entry'] + 2 * levels['risk_per_share'], 2), "Target 2R math must be exact"
    assert levels['trailing_ema_10'] > 0, "10 EMA must be positive"
    assert levels['confluence_score'] >= 0 and levels['confluence_score'] <= 100, "Confluence score must be 0-100"
    print("test_breakout_levels_calculation: OK")


def test_breakout_snapshot_text():
    df = _fake_stock_df()
    # Mock load_price_cache_short
    orig = tools.load_price_cache_short
    try:
        tools.load_price_cache_short = lambda: {"FAKE.NS": df}
        snap = tools.get_snapshot_text_breakout("FAKE.NS")
        assert "BUY TRIGGER" in snap
        assert "HARD STOP LOSS" in snap
        assert "TARGET 1 (+2R)" in snap
        assert "TRAILING RUNNER" in snap
        print("test_breakout_snapshot_text: OK")
    finally:
        tools.load_price_cache_short = orig


def test_breakout_scan_watchlist():
    df = _fake_stock_df()
    orig = tools.load_price_cache_short
    try:
        tools.load_price_cache_short = lambda: {"FAKE.NS": df}
        scan_output = tools.scan_watchlist_text_breakout(limit=5, min_score=30)
        assert "BREAKOUT" in scan_output or "FAKE.NS" in scan_output
        print("test_breakout_scan_watchlist: OK")
    finally:
        tools.load_price_cache_short = orig


def test_breakout_position_size():
    df = _fake_stock_df()
    orig = tools.load_price_cache_short
    orig_live = tools.get_live_price
    try:
        tools.load_price_cache_short = lambda: {"FAKE.NS": df}
        tools.get_live_price = lambda t: 150.0
        pos = tools.calculate_position_size("FAKE.NS", total_capital=100000, risk_pct=1.0, term="breakout")
        assert 'shares_to_buy' in pos, f"position sizing failed: {pos}"
        assert pos['shares_to_buy'] > 0, "shares_to_buy must be > 0"
        assert pos['actual_risk_amount'] <= 100000 * 0.01 + 10, "Risk amount must be within 1%"
        print("test_breakout_position_size: OK")
    finally:
        tools.load_price_cache_short = orig
        tools.get_live_price = orig_live


def test_breakout_full_analysis():
    df = _fake_stock_df()
    orig = tools.load_price_cache_short
    try:
        tools.load_price_cache_short = lambda: {"FAKE.NS": df}
        analysis = tools.get_full_analysis("FAKE.NS", term="breakout")
        assert "Momentum Breakout Snapshot" in analysis
        assert "Fundamentals" in analysis
        print("test_breakout_full_analysis: OK")
    finally:
        tools.load_price_cache_short = orig


if __name__ == "__main__":
    test_breakout_levels_calculation()
    test_breakout_snapshot_text()
    test_breakout_scan_watchlist()
    test_breakout_position_size()
    test_breakout_full_analysis()
    print("ALL BREAKOUT ENGINE TESTS PASSED!")
