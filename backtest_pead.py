"""Does an RSI<30 entry that FOLLOWS a bad earnings reaction mean-revert LESS than other RSI<30 entries?

This is the measurement behind the earnings red flag added to tools.py (the INOXWIND case). Historical
earnings NUMBERS are not cached anywhere, so instead of the miss magnitude this uses the market's own
price reaction to the last results filing AS the miss: a stock that dropped hard on/after its last
results IS the miss, revealed by price. Both inputs are already on disk -

  - results dates : the 369k-filing news archive (cache/news_archive.pkl), keyword-filtered to results
  - reaction + forward returns : the 5y panel (cache/backtest_5y_short.pkl)

Entry/exit/costs reuse backtest_engine.simulate_trades UNCHANGED (close entry, 6-day hold, 4x ATR stop
to match the live strategy, costs charged, non-overlapping). The control is random Mid/Small entries run
through the SAME machinery. Inference is day_clustered z_paired - the project's headline stat - both
against the random control and, more directly, post-bad-earnings vs the rest of the RSI<30 cohort.

    PYTHONIOENCODING=utf-8 python backtest_pead.py          # the real run (needs the two caches)
    PYTHONIOENCODING=utf-8 python backtest_pead.py --check   # synthetic self-check, no data needed

A soft flag ships already; this decides whether it should HARDEN to a FAIL or stay a soft flag (or,
if bad-earnings names revert just as well, be dropped). No new data source. Falling-knife hypothesis:
post-bad-earnings RSI<30 names underperform the rest -> negative day-paired edge.
"""
import sys
import pickle

import numpy as np
import pandas as pd

from backtest_engine import simulate_trades, day_clustered_edge
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR

PANEL = "cache/backtest_5y_short.pkl"
ARCHIVE = "cache/news_archive.pkl"

HORIZON = 6            # the live 4-6 day hold
STOP_ATR = 4.0        # live stop (widened from 2x on 2026-08-11)
TARGET_ATR = 2.0
REACTION_K = 2        # trading days after the filing to let the market's verdict settle
LOOKBACKS = (10, 20, 40)      # how many bars back a results event still "explains" the oversold reading
BAD_THRESHES = (0.0, -5.0)    # reaction% at/below which the last results count as a miss

# Results-declaration filings. 'outcome of board meeting' alone is too broad (dividends, fund raising,
# anything a board decides), so it only counts when paired with a results word.
RESULTS_KEYWORDS = ('financial results', 'financial result', 'quarterly result', 'unaudited financial',
                    'audited financial', 'statement of profit')
BOARD_PLUS_RESULT = ('outcome of board meeting', 'board meeting')


def _is_results(desc, text):
    blob = f"{desc or ''} {text or ''}".lower()
    if any(k in blob for k in RESULTS_KEYWORDS):
        return True
    if any(k in blob for k in BOARD_PLUS_RESULT) and 'result' in blob:
        return True
    return False


def load_panel():
    with open(PANEL, 'rb') as f:
        panel = pickle.load(f)
    out = {}
    for ticker, df in panel.items():
        d = df.sort_values('date').reset_index(drop=True)
        d['date'] = pd.to_datetime(d['date'])
        out[ticker] = d
    return out


def results_reactions(panel):
    """symbol(no .NS) -> sorted list of (bar_index, reaction_pct) for each results filing."""
    with open(ARCHIVE, 'rb') as f:
        archive = pickle.load(f)
    by_symbol = {}
    for rec in archive.values():
        if not _is_results(rec.get('desc'), rec.get('attchmntText')):
            continue
        ts = pd.to_datetime(rec.get('sort_date'), errors='coerce')
        if pd.isna(ts):
            continue
        by_symbol.setdefault(rec['symbol'], []).append(ts.normalize())

    out = {}
    for sym, dates in by_symbol.items():
        d = panel.get(sym + '.NS')
        if d is None:
            continue
        close = d['close'].values
        events = []
        for ev in sorted(set(dates)):
            idx = np.searchsorted(d['date'].values, np.datetime64(ev), side='left')  # first bar >= event
            if idx < 1 or idx + REACTION_K >= len(d):
                continue
            base, after = close[idx - 1], close[idx + REACTION_K]
            if not np.isfinite(base) or base <= 0 or not np.isfinite(after):
                continue
            events.append((int(idx), (after - base) / base * 100))
        if events:
            out[sym] = sorted(events)
    return out


def strategy_trades(panel, reactions, lookback, bad_thresh):
    """RSI<30 Mid/Small trades above the turnover floor, each tagged by its most recent prior results
    reaction. Returns (tagged_trades, control_trades) as lists of {entry_date, net_pct, tag}."""
    rng = np.random.default_rng(7)
    strat, control = [], []
    for ticker, d in panel.items():
        if CAP_BUCKET_MAP.get(ticker) not in ('Mid', 'Small'):
            continue
        liquid = (d['turnover_60d'].values >= MIN_TURNOVER_INR) if 'turnover_60d' in d else np.ones(len(d), bool)
        dates = d['date'].values
        evs = reactions.get(ticker.replace('.NS', ''), [])
        ev_idx = np.array([e[0] for e in evs])

        mask = (d['rsi'].values < 30) & liquid
        for t in simulate_trades(d, mask, horizon_days=HORIZON, stop_atr_mult=STOP_ATR,
                                 target_atr_mult=TARGET_ATR):
            i = t['entry_idx']
            tag = 'no_recent_results'
            if len(ev_idx):
                # entry must be strictly AFTER the reaction window (idx..idx+K) closed, or the
                # reaction would peek past the entry bar - look-ahead.
                prior = ev_idx[(i - ev_idx > REACTION_K) & (i - ev_idx <= lookback)]
                if len(prior):
                    reaction = evs[np.where(ev_idx == prior.max())[0][0]][1]
                    tag = 'post_bad_earn' if reaction <= bad_thresh else 'post_ok_earn'
            strat.append({'entry_date': dates[i], 'net_pct': t['net_pct'], 'tag': tag})

        # Control: random entries, same universe, same machinery (the engine's own control pattern).
        cmask = (rng.random(len(d)) < 0.10) & liquid
        for t in simulate_trades(d, cmask, horizon_days=HORIZON, stop_atr_mult=STOP_ATR,
                                 target_atr_mult=TARGET_ATR):
            control.append({'entry_date': dates[t['entry_idx']], 'net_pct': t['net_pct']})
    return strat, control


def _line(label, sub, ref):
    if len(sub) < 30:
        return f"  {label:<26} {len(sub):>5}  too few"
    clu = day_clustered_edge(sub, ref)
    zp = f"{clu['z_paired']:>7.2f}" if clu else "      -"
    edge = f"{clu['day_edge']:>+7.2f}%" if clu else "      -"
    net = np.mean([t['net_pct'] for t in sub])
    win = np.mean([t['net_pct'] > 0 for t in sub]) * 100
    return f"  {label:<26} {len(sub):>5} {net:>+8.2f}% {win:>5.1f}%   day-edge {edge}  z_paired {zp}"


def run():
    print("Loading panel and news archive...")
    panel = load_panel()
    reactions = results_reactions(panel)
    n_events = sum(len(v) for v in reactions.values())
    print(f"{len(panel)} stocks in panel; {n_events:,} results reactions across {len(reactions)} symbols")
    print(f"Params: RSI<30, Mid/Small, turnover>=Rs{MIN_TURNOVER_INR/1e7:.0f}cr, hold {HORIZON}d, "
          f"{STOP_ATR:g}x ATR stop, reaction = close(t-1)->close(t+{REACTION_K}).\n")

    for lookback in LOOKBACKS:
        for bad in BAD_THRESHES:
            strat, control = strategy_trades(panel, reactions, lookback, bad)
            bad_sub = [t for t in strat if t['tag'] == 'post_bad_earn']
            rest = [t for t in strat if t['tag'] != 'post_bad_earn']
            print("=" * 92)
            print(f"LOOKBACK {lookback} bars | miss = reaction <= {bad:g}%   "
                  f"(control: random entries, same universe, n={len(control):,})")
            print(f"  {'subset':<26} {'n':>5} {'net/trade':>9} {'win':>6}")
            print("  " + "-" * 84)
            print(_line("all RSI<30 (baseline)", strat, control))
            print(_line("post BAD earnings", bad_sub, control))
            print(_line("post ok/good earnings", [t for t in strat if t['tag'] == 'post_ok_earn'], control))
            print(_line("no recent results", [t for t in strat if t['tag'] == 'no_recent_results'], control))
            # The decisive test: bad-earnings names vs the REST of the cohort (does filtering them help?).
            filt = day_clustered_edge(bad_sub, rest)
            if filt:
                print(f"  >> FILTER TEST  post-bad vs rest-of-RSI<30, day-paired: "
                      f"edge {filt['day_edge']:+.2f}%/trade, z_paired {filt['z_paired']:+.2f} "
                      f"(n_bad={len(bad_sub)}, n_rest={len(rest)})")
            print()
    print("Read: a NEGATIVE 'FILTER TEST' edge/z means bad-earnings oversold names revert less than their\n"
          "peers -> the red flag earns a harder gate. A ~0 or positive edge means it does not; keep it soft.")


def _check():
    """Synthetic check of the event->bar mapping and tagging, independent of the real caches."""
    dates = pd.date_range('2021-01-01', periods=200, freq='B')
    close = pd.Series(np.linspace(100, 120, 200))
    d = pd.DataFrame({'date': dates, 'close': close}).reset_index(drop=True)
    panel = {'TEST.NS': d}
    # one event at bar 50: reaction uses close[49]->close[52]
    ev = pd.Timestamp(dates[50]).normalize()
    idx = np.searchsorted(d['date'].values, np.datetime64(ev), side='left')
    assert idx == 50, idx
    reaction = (close[52] - close[49]) / close[49] * 100
    assert reaction > 0, reaction   # rising series -> positive reaction
    # tagging: a trade at bar 55 within lookback 10 sees the event; at bar 70 it does not.
    ev_idx = np.array([50])
    assert 50 in ev_idx[(ev_idx < 55) & (55 - ev_idx <= 10)]
    assert len(ev_idx[(ev_idx < 70) & (70 - ev_idx <= 10)]) == 0
    print("ok  event->bar mapping and lookback tagging")
    print("all passed")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _check()
    else:
        run()
