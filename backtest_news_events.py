"""Is there money left in a corporate filing AFTER the overnight gap?

This is the test behind the "opportunist" idea: a filing lands at 22:38, you buy at the next
open, you sell one to three days later. The question is not whether good news moves stocks -
it obviously does - but whether anything is left once the move you could not trade has already
happened.

THE ONE RULE THAT MATTERS HERE: entry is the OPEN OF THE NEXT TRADING SESSION that begins
after the filing timestamp. Never the pre-news close. Measuring from the close before the news
would price in a move that was never available to a retail trader, and would make every event
type look brilliant. That is exactly the class of look-ahead error the overlap and
day-clustering corrections already caught twice on this project.

The gap itself (prev close -> entry open) is reported separately, because the difference
between the gap and the post-entry return IS the answer: it shows how much of the reaction you
miss versus how much you can actually capture.

    python backtest_news_events.py
"""

import numpy as np
import pandas as pd

from backtest_engine import day_clustered_edge, edge_vs_control
from config import CAP_BUCKET_MAP, round_trip_cost_pct

ARCHIVE = "cache/news_archive.pkl"
PANEL = "cache/backtest_5y_short.pkl"
HOLD_DAYS = (1, 2, 3)

# One primary label per filing, first match wins - ordered so the biggest event type wins when
# a filing mentions several.
EVENT_TYPES = [
    ('open_offer',    ['open offer', 'takeover regulation']),
    ('merger',        ['merger', 'demerger', 'amalgamation', 'scheme of arrangement']),
    ('acquisition',   ['acquisition', 'acquire']),
    ('delisting',     ['delisting']),
    ('buyback',       ['buyback', 'buy-back']),
    ('rating_change', ['downgrade', 'upgrade', 'rating watch', 'revised rating']),
    ('fund_raising',  ['qip', 'qualified institutional', 'preferential issue', 'rights issue',
                       'fund raising', 'fund-raising']),
    ('ceo_change',    ['managing director', 'chief executive', 'ceo', 'chief financial', 'cfo',
                       'chairman']),
]
ROUTINE_NOISE = ['re-appointment', 'reappointment', 'auditor', 'company secretary',
                 'compliance officer', 'registrar', 'debenture trustee', 'reaffirm']


def classify(row):
    blob = f"{row.get('desc') or ''} {row.get('attchmntText') or ''}".lower()
    for name, keys in EVENT_TYPES:
        if any(k in blob for k in keys):
            # Leadership rows are dominated by routine paperwork; everything else is not.
            if name == 'ceo_change' and any(n in blob for n in ROUTINE_NOISE):
                return None
            if name == 'rating_change' and 'reaffirm' in blob:
                return None
            return name
    return None


def load_events():
    archive = pd.read_pickle(ARCHIVE)
    rows = []
    for rec in archive.values():
        etype = classify(rec)
        if not etype:
            continue
        ts = pd.to_datetime(rec.get('sort_date'), errors='coerce')
        if pd.isna(ts):
            continue
        rows.append({'symbol': rec['symbol'], 'ts': ts, 'event': etype})
    df = pd.DataFrame(rows)
    # One event per symbol per type per day - a company often files the same news twice.
    df['day'] = df['ts'].dt.normalize()
    return df.drop_duplicates(subset=['symbol', 'event', 'day'])


def load_prices():
    panel = pd.read_pickle(PANEL)
    out = {}
    for ticker, df in panel.items():
        d = df.sort_values('date').reset_index(drop=True)
        d['date'] = pd.to_datetime(d['date'])
        out[ticker.replace('.NS', '')] = d
    return out


def simulate(events, prices, hold):
    """Entry at the first session OPEN strictly after the filing timestamp."""
    trades = []
    for _, ev in events.iterrows():
        d = prices.get(ev['symbol'])
        if d is None:
            continue
        # Sessions whose OPEN happens after the filing. A filing at 10:00 on day D is treated
        # as tradeable only from D+1 - a retail trader is not filling at that morning's open.
        idx = d.index[d['date'] > ev['ts'].normalize()]
        if len(idx) == 0:
            continue
        i = idx[0]
        if i + hold >= len(d) or i == 0:
            continue
        entry = d['open'].iloc[i]
        prev_close = d['close'].iloc[i - 1]
        exit_px = d['close'].iloc[i + hold - 1]
        if not np.isfinite(entry) or not np.isfinite(exit_px) or entry <= 0 or prev_close <= 0:
            continue
        cost = round_trip_cost_pct(d['turnover_60d'].iloc[i] if 'turnover_60d' in d else None)
        trades.append({
            'symbol': ev['symbol'], 'event': ev['event'], 'entry_date': d['date'].iloc[i],
            'gap_pct': (entry - prev_close) / prev_close * 100,
            'gross_pct': (exit_px - entry) / entry * 100,
            'net_pct': (exit_px - entry) / entry * 100 - cost,
            'cap': CAP_BUCKET_MAP.get(ev['symbol'] + '.NS', 'Unknown'),
        })
    return pd.DataFrame(trades)


def control_trades(prices, dates, hold, seed=7):
    """Random entries on the SAME days - the market itself moves, and that is not an edge."""
    rng = np.random.default_rng(seed)
    syms = [s for s in prices if CAP_BUCKET_MAP.get(s + '.NS') in ('Mid', 'Small')]
    out = []
    for day in dates:
        for sym in rng.choice(syms, size=min(12, len(syms)), replace=False):
            d = prices[sym]
            idx = d.index[d['date'] > day]
            if len(idx) == 0:
                continue
            i = idx[0]
            if i + hold >= len(d) or i == 0:
                continue
            entry, exit_px = d['open'].iloc[i], d['close'].iloc[i + hold - 1]
            if not np.isfinite(entry) or entry <= 0:
                continue
            cost = round_trip_cost_pct(d['turnover_60d'].iloc[i] if 'turnover_60d' in d else None)
            out.append({'entry_date': d['date'].iloc[i],
                        'net_pct': (exit_px - entry) / entry * 100 - cost})
    return pd.DataFrame(out)


def report(label, sub, ctrl, hold):
    if len(sub) < 30:
        return f"  {label:<26} {len(sub):>5}  too few"
    s = [{'net_pct': r.net_pct, 'entry_date': r.entry_date} for r in sub.itertuples()]
    c = [{'net_pct': r.net_pct, 'entry_date': r.entry_date} for r in ctrl.itertuples()]
    clu = day_clustered_edge(s, c)
    naive = edge_vs_control(sub['net_pct'], ctrl['net_pct'])
    zp = f"{clu['z_paired']:>7.2f}" if clu else "      -"
    return (f"  {label:<26} {len(sub):>5} {sub['gap_pct'].mean():>+8.2f}% "
            f"{sub['net_pct'].mean():>+8.2f}% {naive['z']:>7.2f} {zp}  "
            f"{(sub['net_pct'] > 0).mean()*100:>5.1f}%")


HEADER = (f"  {'event type':<26} {'n':>5} {'gap':>9} {'net/trade':>9} {'z':>7} {'z_paired':>7}"
          f" {'win':>6}")


# The first run covered Aug 2024 -> Aug 2026 only, where the random control lost 0.8%/trade -
# a falling market throughout. These windows split the 5-year archive so a bull regime can be
# judged on its own, since "news does not work" and "nothing worked in that period" are
# different claims.
PERIODS = [
    ("2021-08 -> 2022-12  (volatile)", '2021-08-01', '2022-12-31'),
    ("2023-01 -> 2024-09  (BULL)",     '2023-01-01', '2024-09-30'),
    ("2024-09 -> 2026-08  (falling)",  '2024-09-30', '2026-08-31'),
]


def by_period(events, prices, hold=2):
    print("=" * 88)
    print(f"CHRONOLOGICAL SPLIT (hold {hold} days) - does the answer change in a bull market?")
    print(f"  {'period':<34} {'n':>5} {'control':>9} {'net/trade':>9} {'edge':>8} {'z_paired':>8}")
    for label, start, end in PERIODS:
        sub_ev = events[(events['ts'] >= start) & (events['ts'] <= end)]
        if len(sub_ev) < 50:
            print(f"  {label:<34} {len(sub_ev):>5}  too few events")
            continue
        tr = simulate(sub_ev, prices, hold)
        if len(tr) < 50:
            print(f"  {label:<34} {len(tr):>5}  too few trades")
            continue
        ctrl = control_trades(prices, sorted(tr['entry_date'].unique()), hold)
        s = [{'net_pct': r.net_pct, 'entry_date': r.entry_date} for r in tr.itertuples()]
        c = [{'net_pct': r.net_pct, 'entry_date': r.entry_date} for r in ctrl.itertuples()]
        clu = day_clustered_edge(s, c)
        edge = tr['net_pct'].mean() - ctrl['net_pct'].mean()
        zp = f"{clu['z_paired']:>8.2f}" if clu else "       -"
        print(f"  {label:<34} {len(tr):>5} {ctrl['net_pct'].mean():>+8.2f}% "
              f"{tr['net_pct'].mean():>+8.2f}% {edge:>+7.2f}% {zp}")
    print()


def main():
    print("Loading archive and prices...")
    events = load_events()
    prices = load_prices()
    print(f"{len(events):,} classified events, {events['ts'].min():%Y-%m-%d} -> "
          f"{events['ts'].max():%Y-%m-%d}, {events['symbol'].nunique()} symbols\n")
    print("gap       = prev close -> entry open. This is the move you CANNOT capture.")
    print("net/trade = entry open -> exit close, after costs. This is what is LEFT.\n")

    for hold in HOLD_DAYS:
        tr = simulate(events, prices, hold)
        if tr.empty:
            continue
        ctrl = control_trades(prices, sorted(tr['entry_date'].unique()), hold)
        print("=" * 88)
        print(f"HOLD {hold} DAY(S)   |   random control on the same days: "
              f"{ctrl['net_pct'].mean():+.3f}%/trade, n={len(ctrl):,}")
        print(HEADER)
        print(report("ALL EVENTS", tr, ctrl, hold))
        for ev in tr['event'].value_counts().index:
            print(report(ev, tr[tr['event'] == ev], ctrl, hold))
        midsmall = tr[tr['cap'].isin(('Mid', 'Small'))]
        print(report("-- Mid/Small only", midsmall, ctrl, hold))
        print()

    by_period(events, prices, hold=2)

    print("=" * 88)
    print("Entry is the next session's OPEN, never the pre-news close. 8 event types x 3")
    print("holding periods = 24 comparisons; treat the best as the max of 24 noisy draws.")


if __name__ == "__main__":
    main()
