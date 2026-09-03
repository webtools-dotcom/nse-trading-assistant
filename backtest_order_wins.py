"""Do ORDER WINS drift? The category the original news backtest never tested.

    python backtest_order_wins.py

WHY THIS IS A SEPARATE TEST
---------------------------
`backtest_news_events.py` measured eight event types - open offers, mergers, acquisitions,
delistings, buybacks, rating changes, fund raising, CEO changes - and returned z_paired
0.80 / -0.22 / -0.44 for 1/2/3-day holds. That verdict is quoted in every alert the news tool
sends. But there is no order-win category in its EVENT_TYPES list, and "company bags order" is
now the single most common alert the tool produces. It has never been measured.

The archive holds ~1,330 of them under NSE's own categories, so this classifies on `desc`
rather than on the stub text: the stub is one sentence and often omits the words a text filter
needs, while the exchange category is assigned by NSE and is reliable.

SECOND QUESTION, ASKED AT THE SAME TIME
---------------------------------------
"Small companies react harder to news than big ones" is a specific, testable claim. A Rs200cr
order is transformative for a Rs500cr company and a rounding error for Reliance, so the cap
breakdown below is the direct test of it.

Everything else - next-open entry, costs, the random same-day control, day-clustered z_paired -
is imported from backtest_news_events.py unchanged. Reusing the machinery is the point: a
result that comes from new plumbing is a result about the plumbing.
"""

import re

import pandas as pd

from backtest_engine import day_clustered_edge
from backtest_news_events import (ARCHIVE, HEADER, control_trades, load_prices, report,
                                  simulate)

# NSE's own categories. Both mean the same thing from different filers - the company that won
# the order, and the company that awarded it.
ORDER_CATEGORIES = ('bagging/receiving of orders', 'awarding of order')

# NSE only CREATED those categories in late 2024 - there are literally zero of them before,
# so classifying on category alone confines the test to a single falling-market regime, which
# is exactly the objection the original news backtest had to answer by widening its window.
# Earlier order wins were filed under generic categories ("Updates", "Press Release") and can
# only be recovered from the stub text. This pattern adds 1,132 events, 428 of them in the
# 2021-23 bull run, and is deliberately strict: a verb of winning next to a noun of contract.
ORDER_TEXT = re.compile(
    r"\b(bag(s|ged|ging)?|win(s|ning)?|won|secur(e|es|ed)|receipt of|received)\b"
    r"[^.]{0,60}\b(order|contract|letter of intent|loi|work order|purchase order)\b", re.I)

HOLD_DAYS = (1, 2, 3, 5)          # 5 added: a contract is a slower story than a takeover


def load_order_events():
    archive = pd.read_pickle(ARCHIVE)
    rows = []
    for rec in archive.values():
        desc = (rec.get('desc') or '').lower()
        text = str(rec.get('attchmntText') or '')
        by_cat = any(c in desc for c in ORDER_CATEGORIES)
        if not by_cat and not ORDER_TEXT.search(text):
            continue
        ts = pd.to_datetime(rec.get('sort_date'), errors='coerce')
        if pd.isna(ts):
            continue
        rows.append({'symbol': rec['symbol'], 'ts': ts, 'event': 'order_win',
                     'source': 'category' if by_cat else 'text', 'text': text})
    df = pd.DataFrame(rows)
    df['day'] = df['ts'].dt.normalize()
    # A company often files the same order twice (intimation, then press release).
    return df.drop_duplicates(subset=['symbol', 'day'])


def cap_report(tr, ctrl, hold):
    """Does company size change the answer? The direct test of 'small caps react harder'."""
    print(f"  {'-- by company size':<26}")
    for cap in ('Small', 'Mid', 'Large'):
        print(report(f"     {cap}", tr[tr['cap'] == cap], ctrl, hold))


def main():
    print("Loading archive and prices...")
    events = load_order_events()
    prices = load_prices()
    print(f"{len(events):,} order-win events, {events['ts'].min():%Y-%m-%d} -> "
          f"{events['ts'].max():%Y-%m-%d}, {events['symbol'].nunique()} symbols\n")
    print("gap       = prev close -> entry open. The move you CANNOT capture.")
    print("net/trade = entry open -> exit close after costs. What is LEFT.")
    print("z_paired  = day-clustered vs a random control on the SAME days. The headline.\n")

    for hold in HOLD_DAYS:
        tr = simulate(events, prices, hold)
        if tr.empty:
            continue
        ctrl = control_trades(prices, sorted(tr['entry_date'].unique()), hold)
        print("=" * 88)
        print(f"HOLD {hold} DAY(S)   |   random control on the same days: "
              f"{ctrl['net_pct'].mean():+.3f}%/trade, n={len(ctrl):,}")
        print(HEADER)
        print(report("ORDER WINS (all)", tr, ctrl, hold))
        cap_report(tr, ctrl, hold)
        # If the two ways of finding the same event disagree, the classifier IS the finding:
        # the text-matched set is the only one that reaches back into the bull market.
        print(f"  {'-- by how it was found':<26}")
        for src in ('category', 'text'):
            sub = simulate(events[events['source'] == src], prices, hold)
            print(report(f"     {src}", sub, ctrl, hold))
        print()

    # Same split the original test used, so a bull regime is judged on its own.
    from backtest_news_events import by_period
    by_period(events, prices, hold=2)

    print("=" * 88)
    print("4 holds x 4 cuts = 16 comparisons. Treat the best of them as the maximum of 16")
    print("noisy draws, not as a discovery. Entry is the next session's OPEN, never the")
    print("pre-news close - the gap column is the part that was never available to you.")


if __name__ == "__main__":
    main()
