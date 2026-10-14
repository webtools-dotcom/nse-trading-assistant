"""Verdict thresholds only - no network, no cache needed.

The verdict is the one piece of fundamentals logic that makes a recommendation ("size normally"
vs "trade smaller or skip"), so it is the one piece that must not drift silently. Everything
else in get_fundamentals_text is display.

    python test_fundamentals_verdict.py
"""

from tools import fundamental_verdict, _trend_rising

SOLID = {'cash_conversion': 1.1, 'interest_cover': 9.0, 'debt_to_equity': 40}


def test_solid():
    v, why = fundamental_verdict(SOLID)
    assert v == "Solid", (v, why)


def test_any_single_fragile_beats_every_solid():
    for bad in ({'cash_conversion': -0.3}, {'interest_cover': 1.0}, {'debt_to_equity': 250}):
        v, why = fundamental_verdict({**SOLID, **bad})
        assert v == "Fragile", (bad, v, why)


def test_pledge_and_promoter_exit_are_fragile():
    v, _ = fundamental_verdict(SOLID, {'pledge_pct': 30.0})
    assert v == "Fragile", v
    v, _ = fundamental_verdict(SOLID, {'promoter_change_1y_pp': -6.0})
    assert v == "Fragile", v
    # promoters buying more is never a red flag
    v, _ = fundamental_verdict(SOLID, {'promoter_change_1y_pp': 6.0})
    assert v == "Solid", v


def test_thresholds_are_inclusive_at_the_boundary():
    assert fundamental_verdict({**SOLID, 'pledge_pct': None})[0] == "Solid"
    assert fundamental_verdict(SOLID, {'pledge_pct': 24.9})[0] == "Solid"
    assert fundamental_verdict(SOLID, {'pledge_pct': 25.0})[0] == "Fragile"
    assert fundamental_verdict(SOLID, {'promoter_change_1y_pp': -4.9})[0] == "Solid"
    assert fundamental_verdict(SOLID, {'promoter_change_1y_pp': -5.0})[0] == "Fragile"


def test_missing_data_is_unknown_not_solid():
    v, why = fundamental_verdict({})
    assert v == "Unknown", (v, why)
    # one good number is not enough to call a business sturdy
    assert fundamental_verdict({'interest_cover': 9.0})[0] == "Mixed"


def test_trend_direction_is_read_oldest_to_newest():
    # yfinance serves statements newest-first; judging direction without sorting inverts it
    newest_first = [(2026, 300.0), (2025, 200.0), (2024, 100.0)]
    assert _trend_rising(newest_first) is True
    assert _trend_rising([(2026, 100.0), (2025, 200.0), (2024, 300.0)]) is False
    assert _trend_rising([(2026, 100.0), (2025, 200.0)]) is None   # too short to judge


def test_falling_sales_and_profit_is_fragile():
    falling = [(2026, 100.0), (2025, 200.0), (2024, 300.0)]
    v, _ = fundamental_verdict({**SOLID, 'rev_trend': falling, 'pat_trend': falling})
    assert v == "Fragile", v




def test_fragile_blocks_position_sizing_and_confirm_clears_it():
    """The gate, not just the label - a Fragile name must not get a share count silently."""
    import tools

    # A synthetic setup that clears every earlier gate, so this test measures the business-quality
    # gate alone and does not turn red whenever the real market moves.
    clean = {'current_price': 100.0, 'stop_loss': 95.0, 'target': 110.0, 'rsi': 25.0,
             'meta_win_prob': 0.62, 'below_meta_floor': False, 'net_ev_pct': 1.2}
    fragile = {'cash_conversion': -0.4, 'debt_to_equity': 300}

    orig = (tools.get_swing_levels_short, tools.get_fundamentals,
            tools.promoter_snapshot, tools.get_live_price, tools.discipline_check)
    tools.get_swing_levels_short = lambda t, stock_df=None: dict(clean)
    tools.get_live_price = lambda t: 100.0
    tools.discipline_check = lambda t, r: {'blocks': [], 'warnings': []}
    tools.get_fundamentals = lambda t: dict(fragile)
    tools.promoter_snapshot = lambda t: {'pledge_pct': 40.0}
    try:
        blocked = tools.calculate_position_size("TEST.NS", 100000, term="short")
        assert blocked.get('blocked') is True, blocked
        assert blocked.get('business_quality') == 'Fragile', blocked

        # the user's call, not the tool's: confirming must let the trade through
        ok = tools.calculate_position_size("TEST.NS", 100000, term="short", confirmed=True)
        assert not ok.get('blocked') and ok.get('shares_to_buy', 0) > 0, ok

        # a solid business must not be gated at all
        tools.get_fundamentals = lambda t: {'cash_conversion': 1.1, 'interest_cover': 9.0,
                                           'debt_to_equity': 40}
        tools.promoter_snapshot = lambda t: {}
        assert not tools.calculate_position_size("TEST.NS", 100000, term="short").get('blocked')

        # a data failure must never block a valid trade
        tools.get_fundamentals = lambda t: {'error': 'network down'}
        assert not tools.calculate_position_size("TEST.NS", 100000, term="short").get('blocked')
    finally:
        (tools.get_swing_levels_short, tools.get_fundamentals,
         tools.promoter_snapshot, tools.get_live_price, tools.discipline_check) = orig


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("all fundamentals-verdict tests passed")
