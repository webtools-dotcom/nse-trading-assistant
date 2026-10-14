"""Self-check for the sector-context display (tools.peer_strength).

It is DISPLAY ONLY - these asserts exist so a later edit cannot quietly turn it into a filter or
let a two-stock "industry" print as if it were a theme. Plain asserts, no framework, no network.

    python test_peer_strength.py
"""
import pandas as pd

import tools


def fake_cache(spec):
    """{ticker: pct_move_over_60d} -> a price cache shaped like load_price_cache_long()."""
    out = {}
    for t, move in spec.items():
        closes = [100.0] * 60 + [100.0 * (1 + move / 100)]
        out[t] = pd.DataFrame({'close': closes})
    return out


# Two industries in the map; only one has enough members to be a real peer group.
tools.load_industry_map = lambda: {
    'BIG1.NS': {'industry': 'Communication Equipment'},
    'BIG2.NS': {'industry': 'Communication Equipment'},
    'BIG3.NS': {'industry': 'Communication Equipment'},
    'BIG4.NS': {'industry': 'Communication Equipment'},
    'BIG5.NS': {'industry': 'Communication Equipment'},
    'TINY1.NS': {'industry': 'Uranium'},
    'TINY2.NS': {'industry': 'Uranium'},
}

out = tools.peer_strength(fake_cache({
    'BIG1.NS': 50.0, 'BIG2.NS': 10.0, 'BIG3.NS': 10.0, 'BIG4.NS': 10.0, 'BIG5.NS': 10.0,
    'TINY1.NS': 80.0, 'TINY2.NS': 80.0,
}))

# peer group of 5 -> reported; mean is 18%, the leader is 32pp ahead of it
ind, sec_mom, rs = out['BIG1.NS']
assert ind == 'Communication Equipment', ind
assert abs(sec_mom - 18.0) < 0.05, sec_mom
assert abs(rs - 32.0) < 0.05, rs

# a laggard inside the same group reports a NEGATIVE gap, not an absolute one
assert out['BIG2.NS'][2] < 0, out['BIG2.NS']

# 2-stock "industry" is dropped, never averaged into a fake theme
assert 'TINY1.NS' not in out and 'TINY2.NS' not in out
assert tools.MIN_SECTOR_PEERS >= 3, "peer floor must stay above noise"

# no industry map built -> degrades to nothing rather than crashing the scan
tools.load_industry_map = lambda: {}
assert tools.peer_strength(fake_cache({'A.NS': 5.0})) == {}

print("peer strength display: all checks passed")
