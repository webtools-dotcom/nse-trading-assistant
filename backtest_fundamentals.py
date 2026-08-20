"""Do fundamentals (ROE, ROCE, cash-conversion, profit margin, revenue growth, D/E) predict
forward returns in THIS universe - i.e. should they stay informational, or earn a role in the
scan output?

THE CEILING, READ FIRST. yfinance gives no point-in-time fundamentals history - only today's
(possibly restated) annual statements. Indian FYs are almost all March-end, so every stock's
report lands in the SAME few cohorts. Clustered by cohort (the honest unit, exactly like
day_clustered_edge clusters by entry date), effective N = number of fiscal cohorts ~= 4-5, NOT
the number of stocks. So z_paired here has almost no power BY CONSTRUCTION. Two more biases both
push results UP: survivorship (panel = today's survivors) and restatement (statements are the
current view, not what was known then). Asymmetry that makes the test still worth running: a
factor that shows NO edge even with the deck stacked in its favour is a trustworthy "keep it
informational". A factor that DOES show edge is suspect and needs point-in-time data to believe.

Method per fiscal cohort: rank the liquid Mid/Small universe by the factor, enter the top quartile
at the OPEN ~45 trading days after fiscal year-end (report lag - no look-ahead), hold H days net of
costs, pair against the same cohort's universe mean.

    python backtest_fundamentals.py            # uses cache/fundamentals_annual.pkl if present
    python backtest_fundamentals.py --refresh  # re-download statements (slow: ~1 call/stock)
"""

import os
import pickle
import sys

import numpy as np
import pandas as pd
import yfinance as yf

from backtest_engine import day_clustered_edge
from config import CAP_BUCKET_MAP, MIN_TURNOVER_INR, LONG_HORIZON_DAYS, round_trip_cost_pct
from data_fetcher_long import _row

PANEL = "cache/backtest_5y_long.pkl"
FUND_CACHE = "cache/fundamentals_annual.pkl"
H = LONG_HORIZON_DAYS
REPORT_LAG = 45          # trading days after FYE before we could act on the filing
HIGHER_IS_BETTER = {'roe': True, 'roce': True, 'cash_conv': True, 'margin': True,
                    'rev_growth': True, 'debt_equity': False}


def fetch_annual(tickers):
    """Per fiscal year-end date: the raw ingredients for each factor. Best-effort, cached."""
    rows = []
    for i, t in enumerate(tickers):
        try:
            s = yf.Ticker(t)
            inc, bal, cf = s.income_stmt, s.balance_sheet, s.cashflow
        except Exception:
            continue
        rev = _row(inc, 'Total Revenue')
        ni = _row(inc, 'Net Income', 'Net Income Common Stockholders')
        ebit = _row(inc, 'EBIT', 'Operating Income')
        assets = _row(bal, 'Total Assets')
        cur_liab = _row(bal, 'Current Liabilities', 'Total Current Liabilities')
        equity = _row(bal, 'Stockholders Equity', 'Total Stockholder Equity')
        debt = _row(bal, 'Total Debt')
        ocf = _row(cf, 'Operating Cash Flow', 'Total Cash From Operating Activities')
        if rev is None or ni is None:
            continue
        for d in rev.index:                       # one row per fiscal year-end
            def g(sr):
                return float(sr[d]) if sr is not None and d in sr.index and pd.notna(sr[d]) else np.nan
            r, n = g(rev), g(ni)
            eq, ce = g(equity), (g(assets) - g(cur_liab))
            rows.append({
                'ticker': t, 'fye': pd.Timestamp(d),
                'roe': (n / eq * 100) if eq and eq > 0 else np.nan,
                'roce': (g(ebit) / ce * 100) if ce and ce > 0 else np.nan,
                'cash_conv': (g(ocf) / n) if n else np.nan,
                'margin': (n / r * 100) if r else np.nan,
                'debt_equity': (g(debt) / eq) if eq and eq > 0 else np.nan,
                'rev': r,
            })
        if (i + 1) % 50 == 0:
            print(f"  fetched {i + 1}/{len(tickers)}")
    df = pd.DataFrame(rows)
    # revenue growth = this FYE revenue vs the same ticker's prior FYE revenue
    df = df.sort_values(['ticker', 'fye'])
    df['rev_growth'] = df.groupby('ticker')['rev'].pct_change() * 100
    return df


def load_fundamentals(tickers, refresh):
    if not refresh and os.path.exists(FUND_CACHE):
        return pd.read_pickle(FUND_CACHE)
    print(f"Downloading annual statements for {len(tickers)} stocks (slow)...")
    df = fetch_annual(tickers)
    os.makedirs(os.path.dirname(FUND_CACHE), exist_ok=True)
    df.to_pickle(FUND_CACHE)
    print(f"Saved {FUND_CACHE}: {len(df)} fiscal-year rows, {df['ticker'].nunique()} stocks")
    return df


def forward_returns(panel):
    """For each (ticker, fye) we attach the net forward return entering REPORT_LAG days after fye."""
    idx = {}
    for t, df in panel.items():
        df = df.sort_values('date').reset_index(drop=True)
        idx[t] = df
    return idx


def entry_return(df, fye):
    """Enter at the open of the first bar >= fye + REPORT_LAG (in trading days), hold H, net cost."""
    after = df[df['date'] > fye]
    if len(after) <= REPORT_LAG + H + 1:
        return None, None
    e = after.iloc[REPORT_LAG]
    x = after.iloc[REPORT_LAG + H]
    if e['open'] <= 0 or e['turnover_60d'] < MIN_TURNOVER_INR:
        return None, None
    net = (x['close'] - e['open']) / e['open'] * 100 - round_trip_cost_pct(e['turnover_60d'])
    cohort = pd.Timestamp(fye).to_period('Q')     # fiscal cohort = the clustering unit
    return net, cohort


def run(refresh=False):
    try:
        panel = pd.read_pickle(PANEL)
    except FileNotFoundError:
        print("cache/backtest_5y_long.pkl not found - run build_backtest_panel_long.py first.")
        return
    liquid = [t for t in panel if CAP_BUCKET_MAP.get(t) in ('Small', 'Mid')]
    fund = load_fundamentals(liquid, refresh)
    idx = forward_returns({t: panel[t] for t in liquid if t in panel})

    # attach forward return + cohort to every fiscal-year row we have price data for
    recs = []
    for _, row in fund.iterrows():
        df = idx.get(row['ticker'])
        if df is None:
            continue
        net, cohort = entry_return(df, row['fye'])
        if net is None:
            continue
        rec = {'cohort': cohort, 'net': net, 'ticker': row['ticker']}
        rec.update({f: row[f] for f in HIGHER_IS_BETTER})
        recs.append(rec)
    a = pd.DataFrame(recs)
    if a.empty:
        print("No overlapping fundamental + price rows. Try --refresh.")
        return

    n_cohorts = a['cohort'].nunique()
    print(f"\n{a['ticker'].nunique()} stocks, {len(a)} fiscal-year events, "
          f"{n_cohorts} fiscal cohorts, hold {H}d, entry +{REPORT_LAG}d after FYE, costs charged.")
    print(f"EFFECTIVE N ~= {n_cohorts} (cohorts), NOT {len(a)} (events). z_paired below is capped by "
          f"that.\nControl = same-cohort universe mean. Top-quartile sort per factor.\n")
    print(f"  {'factor':<14}{'events':>8}{'cohorts':>9}{'net/tr':>10}{'ctrl/tr':>10}{'z_paired':>10}")

    for f, higher in HIGHER_IS_BETTER.items():
        d = a.dropna(subset=[f]).copy()
        if d['cohort'].nunique() < 3 or len(d) < 40:
            print(f"  {f:<14}{len(d):>8}{'too few':>9}")
            continue
        d['rank'] = d.groupby('cohort')[f].rank(pct=True, ascending=higher)
        sel = d[d['rank'] >= 0.75]
        strat = [{'entry_date': c, 'net_pct': r} for c, r in zip(sel['cohort'], sel['net'])]
        ctrl = [{'entry_date': c, 'net_pct': r} for c, r in zip(d['cohort'], d['net'])]
        clu = day_clustered_edge(strat, ctrl)
        if clu is None:
            print(f"  {f:<14}{len(sel):>8}{'n/a':>9}")
            continue
        print(f"  {f:<14}{len(sel):>8}{clu['n_paired_days']:>9}{sel['net'].mean():>+9.2f}%"
              f"{d['net'].mean():>+9.2f}%{clu['z_paired']:>10.2f}")

    print("\nRead: |z_paired| >= 2 with a POSITIVE net-vs-control gap would argue for promoting a factor")
    print("to the scan. Given effective N ~= a handful of cohorts, expect noise - anything that")
    print("survives here is a candidate to RE-test on point-in-time data, not a green light.")


if __name__ == "__main__":
    run(refresh="--refresh" in sys.argv)
