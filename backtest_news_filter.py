"""Does a RED-FLAG news filing make an RSI<30 mean-reversion setup worse?

This is the SAFETY-FILTER test, and it is the OPPOSITE question from backtest_news_events.py.
That file asked "can you BUY on news?" (answer: no, the gap eats it). This asks: given the
validated RSI<30 short-term setup already fired, does a red-flag filing in the days before entry
identify the ones you should have SKIPPED - the INOXWIND case, oversold because something is
actually broken rather than because the market overreacted?

Method, matching the discipline already paid for on this project:
  - Universe/entry = the validated short setup: Mid/Small cap, RSI<30 at signal close, turnover
    >= MIN_TURNOVER_INR, entry at the NEXT session OPEN (never the signal close), hold H days.
  - Non-overlapping per symbol: RSI stays <30 for days, so one episode would otherwise count as
    several near-identical trades and inflate every z. After an entry, skip H days for that name.
  - red-flagged = the symbol had a red-flag filing (config.red_flags_in) in the LOOKBACK days up
    to and including the signal day. Only filings knowable BEFORE entry - no look-ahead.
  - Headline stat = day_clustered_edge(red_flagged, clean): red-flag day-mean minus clean day-mean,
    paired by entry date so the shared market factor nets out. NEGATIVE and large = filter works.
  - A random Mid/Small control on the same days anchors the absolute level of each group.

    python backtest_news_filter.py
"""
import argparse

import numpy as np
import pandas as pd

from backtest_engine import day_clustered_edge, edge_vs_control
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR, round_trip_cost_pct, red_flags_in


# Pre-registered SEVERE-only screen (second, final look at the data). Only the categories that
# genuinely mean "the company is broken": insolvency/IBC, pledge INVOCATION (not creation/release),
# fraud, rating downgrade, and MD/CFO/CEO resignation (not lone directors or company secretaries).
# Deliberately narrower than config.red_flags_in to cut the false positives that diluted v1.
def severe_flags_in(text):
    blob = (text or '').lower()
    hits = []
    if any(k in blob for k in ('insolvency', 'bankruptcy', 'nclt', ' ibc', 'winding up', 'liquidation')):
        hits.append('Insolvency')
    if 'invocation' in blob and 'pledge' in blob:
        hits.append('Pledge invoked')
    if 'fraud' in blob:
        hits.append('Fraud')
    if any(k in blob for k in ('downgrade', 'rating watch', 'negative outlook', 'revised rating')) \
            and not any(g in blob for g in ('upgrade', 'reaffirm', 'assigned')):
        hits.append('Downgrade')
    if any(k in blob for k in ('resignation', 'resigns', 'cessation')) \
            and any(r in blob for r in ('managing director', 'chief financial', 'chief executive', ' ceo', ' cfo')):
        hits.append('MD/CFO exit')
    return hits

ARCHIVE = "cache/news_archive.pkl"
PANEL = "cache/backtest_5y_short.pkl"
HOLD = 6           # the short strategy's own 4-6 day horizon (SHORT_HORIZON_DAYS)
LOOKBACK = 30      # a red-flag filing this many days before the signal still taints the setup
RSI_MAX = 30


def red_flag_days(classifier=red_flags_in):
    """symbol -> sorted np.array of normalized filing days that tripped a red-flag category."""
    archive = pd.read_pickle(ARCHIVE)
    days = {}
    for rec in archive.values():
        if not classifier(f"{rec.get('desc') or ''} {rec.get('attchmntText') or ''}"):
            continue
        ts = pd.to_datetime(rec.get('sort_date'), errors='coerce')
        if pd.isna(ts):
            continue
        days.setdefault(rec['symbol'], []).append(ts.normalize())
    return {s: np.array(sorted(set(v))) for s, v in days.items()}


def load_prices():
    panel = pd.read_pickle(PANEL)
    out = {}
    for ticker, df in panel.items():
        d = df.sort_values('date').reset_index(drop=True)
        d['date'] = pd.to_datetime(d['date'])
        out[ticker.replace('.NS', '')] = d
    return out


def rsi_entries(prices, rflags, hold):
    """Non-overlapping RSI<30 Mid/Small entries, each tagged clean vs red-flagged and by category."""
    lb = pd.Timedelta(days=LOOKBACK)
    trades = []
    for sym, d in prices.items():
        if CAP_BUCKET_MAP.get(sym + '.NS') not in ('Mid', 'Small'):
            continue
        flags = rflags.get(sym)
        last_exit = -1
        rsi = d['rsi'].to_numpy()
        turn = d['turnover_60d'].to_numpy() if 'turnover_60d' in d else np.full(len(d), np.nan)
        for i in range(len(d) - hold - 1):
            if i <= last_exit:
                continue
            if not (rsi[i] < RSI_MAX) or not (turn[i] >= MIN_TURNOVER_INR):
                continue
            entry = d['open'].iloc[i + 1]          # next session open, never the signal close
            exit_px = d['close'].iloc[i + hold]
            if not np.isfinite(entry) or not np.isfinite(exit_px) or entry <= 0:
                continue
            sig_day = d['date'].iloc[i]
            tainted = flags is not None and bool(((flags <= sig_day) & (flags >= sig_day - lb)).any())
            cost = round_trip_cost_pct(turn[i])
            trades.append({
                'symbol': sym, 'entry_date': d['date'].iloc[i + 1],
                'net_pct': (exit_px - entry) / entry * 100 - cost,
                'cap': CAP_BUCKET_MAP.get(sym + '.NS'), 'tainted': tainted,
            })
            last_exit = i + hold                    # enforce non-overlap
    return pd.DataFrame(trades)


def control_trades(prices, dates, hold, seed=7):
    rng = np.random.default_rng(seed)
    syms = [s for s in prices if CAP_BUCKET_MAP.get(s + '.NS') in ('Mid', 'Small')]
    dset = set(pd.to_datetime(dates))
    out = []
    for sym in syms:
        d = prices[sym]
        hit = d.index[d['date'].isin(dset)]
        for i in rng.choice(hit, size=min(len(hit), 40), replace=False) if len(hit) else []:
            if i + hold >= len(d) or i == 0:
                continue
            entry, exit_px = d['open'].iloc[i], d['close'].iloc[i + hold - 1]
            if not np.isfinite(entry) or entry <= 0:
                continue
            out.append({'entry_date': d['date'].iloc[i],
                        'net_pct': (exit_px - entry) / entry * 100 - round_trip_cost_pct(
                            d['turnover_60d'].iloc[i] if 'turnover_60d' in d else None)})
    return pd.DataFrame(out)


def _rows(df):
    return [{'net_pct': r.net_pct, 'entry_date': r.entry_date} for r in df.itertuples()]


def line(label, sub, vs_ctrl):
    if len(sub) < 30:
        return f"  {label:<28} {len(sub):>5}   too few"
    clu = day_clustered_edge(_rows(sub), vs_ctrl)
    zp = f"{clu['z_paired']:>+7.2f}" if clu else "      -"
    return (f"  {label:<28} {len(sub):>5} {sub['net_pct'].mean():>+8.2f}% "
            f"{(sub['net_pct'] > 0).mean()*100:>5.1f}%  {zp}")


def main(severe=False):
    print(f"Loading archive red-flag days and price panel...  [{'SEVERE-only' if severe else 'full'} screen]")
    rflags = red_flag_days(severe_flags_in if severe else red_flags_in)
    prices = load_prices()
    tr = rsi_entries(prices, rflags, HOLD)
    clean = tr[~tr['tainted']]
    red = tr[tr['tainted']]
    print(f"{len(tr):,} non-overlapping RSI<30 Mid/Small entries "
          f"({tr['entry_date'].min():%Y-%m-%d} -> {tr['entry_date'].max():%Y-%m-%d})")
    print(f"  clean: {len(clean):,}   red-flagged: {len(red):,} "
          f"({len(red)/max(len(tr),1)*100:.1f}%)   lookback {LOOKBACK}d, hold {HOLD}d\n")

    ctrl = control_trades(prices, tr['entry_date'].unique(), HOLD)
    ctrl_rows = _rows(ctrl)
    print(f"random Mid/Small control on the same days: {ctrl['net_pct'].mean():+.3f}%/trade, n={len(ctrl):,}\n")

    print(f"  {'group':<28} {'n':>5} {'net/trade':>9} {'win':>6}  {'z vs random':>10}")
    print(line("ALL RSI<30", tr, ctrl_rows))
    print(line("clean (no red flag)", clean, ctrl_rows))
    print(line("red-flagged", red, ctrl_rows))

    print(f"\n  HEADLINE - red-flagged vs clean, paired by day (NEGATIVE = filter has value):")
    head = day_clustered_edge(_rows(red), _rows(clean))
    if head:
        print(f"    day_edge {head['day_edge']:+.3f}%/trade   z_paired {head['z_paired']:+.2f}   "
              f"(n_paired_days {head['n_paired_days']})")
        naive = edge_vs_control(red['net_pct'], clean['net_pct'])
        if naive:
            print(f"    naive (unpaired) edge {naive['edge']:+.3f}%   z {naive['z']:+.2f}")
    else:
        print("    too few paired days to test")

    print("\n  DOWNSIDE TAIL (a safety filter is about avoiding blow-ups, not average return):")
    print(f"    {'group':<20} {'p10':>8} {'worst10%avg':>12} {'min':>8} {'<-8%':>7}")
    for label, g in (("clean", clean), ("red-flagged", red)):
        x = g['net_pct'].to_numpy()
        worst10 = x[x <= np.percentile(x, 10)]
        print(f"    {label:<20} {np.percentile(x,10):>+7.2f}% {worst10.mean():>+11.2f}% "
              f"{x.min():>+7.2f}% {(x < -8).mean()*100:>6.1f}%")
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--severe", action="store_true", help="pre-registered severe-only red flags")
    main(ap.parse_args().severe)
