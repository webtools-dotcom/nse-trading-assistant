"""Offline checks for the user-initiated trade evaluation (no network).

The point of evaluate_user_trade is that it must never silently imply the backtest endorses a
setup it does not cover, so these focus on the verdict branching.
"""
from tools import normalize_ticker, _universe_verdict
from config import MIN_TURNOVER_INR


def _levels(**over):
    base = {'cap_bucket': 'Small', 'rsi': 25.0, 'turnover_60d_cr': 50.0,
            'trend_tier': 'Flat/Mild'}
    base.update(over)
    return base


def test_ticker_normalisation():
    assert normalize_ticker('reliance') == 'RELIANCE.NS'
    assert normalize_ticker(' HDFCBANK.NS ') == 'HDFCBANK.NS'
    assert normalize_ticker('TCS.BO') == 'TCS.BO', "existing exchange suffix must be preserved"
    assert normalize_ticker('') is None and normalize_ticker(None) is None


def test_validated_setup_is_recognised():
    v = _universe_verdict('X.NS', _levels(), 'cache')
    assert v.startswith("VALIDATED SETUP"), v


def test_every_disqualifier_is_stated():
    """A setup outside the strategy must say so, and say WHY - a bare refusal gives the agent
    nothing to relay and it starts improvising reasons."""
    cases = [
        (_levels(cap_bucket='Large'), 'cache', 'Mid/Small'),
        (_levels(rsi=55), 'cache', 'not below 30'),
        (_levels(turnover_60d_cr=MIN_TURNOVER_INR / 1e7 - 1), 'cache', 'below the Rs25cr floor'),
        (_levels(trend_tier='Downtrend'), 'cache', 'Downtrend'),
        (_levels(cap_bucket='Mid'), 'cache', 'Mid-cap'),
        (_levels(cap_bucket='Unknown'), 'live', '748-stock universe'),
    ]
    for levels, source, expect in cases:
        v = _universe_verdict('X.NS', levels, source)
        assert v.startswith("NO BACKTESTED EDGE"), f"{expect}: wrongly passed as validated"
        assert expect in v, f"verdict did not explain '{expect}':\n{v}"


def test_no_edge_verdict_warns_against_quoting_stats():
    v = _universe_verdict('X.NS', _levels(cap_bucket='Large'), 'cache')
    assert 'z-score' in v and 'not a validated signal' in v


if __name__ == "__main__":
    test_ticker_normalisation()
    test_validated_setup_is_recognised()
    test_every_disqualifier_is_stated()
    test_no_edge_verdict_warns_against_quoting_stats()
    print("user trade evaluation: OK")
