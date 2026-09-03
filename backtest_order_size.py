"""Does an order's SIZE relative to the company change the answer?

    python backtest_order_size.py

`backtest_order_wins.py` rejected order wins outright: -0.98%/trade, no edge in any regime.
This tests the one version of the idea with a mechanism left in it - that a Rs602cr order for a
Rs3,000cr company is a different event from 0.2% of market cap, and that lumping them together
is what buried the signal.

TWO HONEST LIMITATIONS, BOTH OF WHICH BITE
------------------------------------------
1. SELECTION. Only ~12% of stub texts state a rupee figure; the rest are in PDF attachments the
   archive never stored (it keeps no attachment URL either, so they cannot be re-fetched without
   re-downloading five years of announcements). Filings that put the number in the one-line
   summary are plausibly the bigger, more newsworthy ones, so this sample is not the population.

2. MARKET CAP IS MEASURED TODAY. The watchlist CSV holds current market caps, and a company that
   won an order in 2021 may be worth five times more now, which would make every old order look
   trivially small. This corrects for it by scaling with the stock's own price:

       mcap_then ~= mcap_now * (close_then / close_now)

   That assumes share count did not change much - wrong for anyone who did a big QIP or split,
   right enough for most - and it is far better than pretending 2021 orders happened at today's
   valuation.

Neither limitation is fatal to a first look, and both are fatal to treating the result as final.
"""

import re

import pandas as pd

from backtest_news_events import HEADER, control_trades, load_prices, report, simulate
from backtest_order_wins import load_order_events

WATCHLIST = "nse_watchlist_expanded.csv"

# "Rs. 1,234.56 crore", "INR 45 Cr", "Rs 90 lakh", "₹1,200 crores"
AMOUNT_RE = re.compile(
    r"(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(crore|crores|cr\b|lakh|lakhs|mn|million)",
    re.I)
FOREIGN_RE = re.compile(r"(usd|us\s*\$|\$|dollar|eur|euro|gbp|pound|jpy|yen)", re.I)
UNIT_TO_CR = {'crore': 1.0, 'crores': 1.0, 'cr': 1.0,
              'lakh': 0.01, 'lakhs': 0.01,
              'mn': 0.1, 'million': 0.1}          # 1 million rupees = 0.1 crore


def parse_amount_cr(text):
    """Largest rupee figure in the text, in crore, or None. Pure.

    Largest rather than first: a filing often names the order value and then a smaller
    component ("... of Rs 602 crore, including Rs 45 crore of spares").
    """
    best = None
    for m in AMOUNT_RE.finditer(text or ""):
        # "USD 30 million" is about Rs250cr, not Rs3cr. Guessing an exchange rate across five
        # years would add error to the very number being bucketed, so foreign-currency figures
        # are dropped instead - a smaller honest sample beats a mis-sized larger one.
        if FOREIGN_RE.search((text or "")[max(0, m.start() - 24):m.start()]):
            continue
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        cr = val * UNIT_TO_CR[m.group(2).lower().rstrip('.')]
        if cr <= 0 or cr > 500_000:               # > Rs5 lakh crore is a parse error
            continue
        if best is None or cr > best:
            best = cr
    return best


def load_caps_cr():
    df = pd.read_csv(WATCHLIST)
    return {str(r.Symbol).strip(): float(r.market_cap) / 1e7
            for r in df.itertuples() if pd.notna(r.market_cap) and r.market_cap > 0}


def attach_size(events, prices, caps):
    """Add amount_cr and pct_of_mcap, with market cap rolled back to the event date."""
    rows = []
    for ev in events.itertuples():
        amt = parse_amount_cr(ev.text)
        mcap_now = caps.get(ev.symbol)
        if not amt or not mcap_now:
            continue
        d = prices.get(ev.symbol)
        if d is None or d.empty:
            continue
        past = d[d['date'] <= ev.ts.normalize()]
        if past.empty:
            continue
        close_then, close_now = past['close'].iloc[-1], d['close'].iloc[-1]
        if not (close_then > 0 and close_now > 0):
            continue
        mcap_then = mcap_now * (close_then / close_now)
        rows.append({'symbol': ev.symbol, 'ts': ev.ts, 'event': 'order_win',
                     'amount_cr': amt, 'mcap_cr': mcap_then,
                     'pct_of_mcap': 100.0 * amt / mcap_then})
    return pd.DataFrame(rows)


BUCKETS = [("< 1% of mcap", 0, 1), ("1 - 5%", 1, 5), ("5 - 15%", 5, 15), ("> 15%", 15, 1e9)]


def main():
    print("Loading archive and prices...")
    events = load_order_events()
    prices = load_prices()
    caps = load_caps_cr()
    sized = attach_size(events, prices, caps)
    print(f"{len(events):,} order events -> {len(sized):,} with a parseable rupee figure "
          f"AND a market cap ({100*len(sized)/len(events):.0f}%)\n")
    if sized.empty:
        return
    q = sized['pct_of_mcap'].describe(percentiles=[.25, .5, .75, .9])
    print("order value as % of market cap at the time:")
    print(f"  median {q['50%']:.2f}%   p75 {q['75%']:.2f}%   p90 {q['90%']:.2f}%   "
          f"max {q['max']:.0f}%\n")

    for hold in (1, 2, 3, 5):
        tr = simulate(sized, prices, hold)
        if tr.empty:
            continue
        ctrl = control_trades(prices, sorted(tr['entry_date'].unique()), hold)
        print("=" * 88)
        print(f"HOLD {hold} DAY(S)   |   random control same days: "
              f"{ctrl['net_pct'].mean():+.3f}%/trade")
        print(HEADER)
        print(report("ALL sized orders", tr, ctrl, hold))
        # Each bucket is simulated from its own events rather than joined back onto the trades.
        # Joining on symbol alone would give every order a company ever won the size of its
        # FIRST one, which is exactly the kind of quiet error this whole test is about.
        for label, lo, hi in BUCKETS:
            evs = sized[(sized['pct_of_mcap'] >= lo) & (sized['pct_of_mcap'] < hi)]
            print(report(f"  {label}", simulate(evs, prices, hold), ctrl, hold))
        print()

    print("=" * 88)
    print("Read the limitations at the top of this file before believing any of it: the sample")
    print("is the ~12% of filings that state a number in the stub, and market cap is rolled")
    print("back by price alone. 4 holds x 5 cuts = 20 comparisons.")


if __name__ == "__main__":
    main()
