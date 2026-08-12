"""Exit-engineering backtests for the live RSI<30 swing system.

Entry is held FIXED (the live signal: RSI<30, Mid/Small-cap, turnover >= Rs25cr). Only the
EXIT rule changes. Because every row conditions on the same entered trades, this is a smaller
multiple-testing surface than entry research - but it still goes through the same discipline:
non-overlapping, costs charged, and day-clustered inference with z_paired as the headline.

Two questions, from the exit-engineering literature (Alvarez, Connors, et al.):

  TEST 1 - Stop width. Literature says tight stops HURT mean-reversion (they realise the very
           dip the strategy bets will revert). Sweep the stop from the live 2xATR out to none.
  TEST 2 - RSI-recovery exit vs the fixed 6-day clock. Standard MR exit is "sell when RSI
           recovers", not a time clock. Win condition here is not only higher net/trade - it is
           equal-or-better net at a SHORTER hold, which on a small account means less cost drag
           and capital freed sooner.

Neither result is adopted by running this. It produces numbers; the decision is separate, and
the honest prior is that most of this repo's exit/entry hypotheses have died at exactly this step.

    python backtest_exits.py
"""

import numpy as np
import pandas as pd

from backtest_engine import (simulate_trades, edge_vs_control, day_clustered_edge,
                             sharpe, deflated_sharpe)
from backtest_day_clustered import load_panel, liquid_rsi30, HORIZON

MIDSMALL = lambda t, cp, d: cp in ('Mid', 'Small')


def collect(panel, signal, universe, sim_kwargs, seed=42):
    """(strategy_trades, control_trades) over the same subset, both run through the SAME exit
    rule. Same-day random control, so a result cannot come from the exit rule flattering the
    strategy relative to a differently-exited control."""
    rng = np.random.default_rng(seed)
    strat, ctrl = [], []
    for ticker, cap, df in panel:
        if not universe(ticker, cap, df):
            continue
        mask = signal(df).fillna(False).values
        rand = rng.random(len(df)) < 0.10
        dates = df['date'].values
        for lst, m in ((strat, mask), (ctrl, rand)):
            for t in simulate_trades(df, m, horizon_days=HORIZON, **sim_kwargs):
                t['entry_date'] = dates[t['entry_idx']]
                lst.append(t)
    return strat, ctrl


def _reasons(trades):
    """Compact exit-reason breakdown: stop / target / rsi / time."""
    c = {'stop': 0, 'target': 0, 'rsi': 0, 'time': 0}
    for t in trades:
        r = t['reason']
        c['stop'] += r in ('stop', 'stop_gap')
        c['target'] += r == 'target'
        c['rsi'] += r == 'rsi_recover'
        c['time'] += r == 'time'
    n = max(len(trades), 1)
    return f"{c['stop']*100//n:>2}/{c['target']*100//n:>2}/{c['rsi']*100//n:>2}/{c['time']*100//n:>2}"


def row(label, strat, ctrl):
    """Print one row, return (label, net_returns, sharpe) for the multiple-testing footer."""
    if len(strat) < 30:
        print(f"  {label:<22} {len(strat):>6} trades - too few")
        return None
    net = [t['net_pct'] for t in strat]
    naive = edge_vs_control(net, [t['net_pct'] for t in ctrl])
    clu = day_clustered_edge(strat, ctrl)
    if clu is None:
        print(f"  {label:<22} {len(strat):>6} trades - insufficient days")
        return None
    held = np.mean([t['held'] for t in strat])
    sr = sharpe(net, holding_days=held)
    verdict = "OK" if clu['z_paired'] >= 2.0 else ("weak" if clu['z_paired'] >= 1.0 else "GONE")
    print(f"  {label:<22} {naive['n_strategy']:>6} {clu['n_days']:>5}  {naive['strategy_avg']:+7.3f}%  "
          f"{clu['z_paired']:>8.2f}  {held:>5.2f}  {naive['win_rate']:>4.1f}  {_reasons(strat):>11}   {verdict}")
    return (label, net, sr)


HEADER = (f"  {'exit config':<22} {'trades':>6} {'days':>5}  {'net/tr':>8}  {'z_paired':>8}  "
          f"{'held':>5}  {'win%':>4}  {'st/tg/rs/tm':>11}   verdict")


def dsr_footer(rows):
    """Search-adjusted guard. A sweep reports the best of several correlated configs; the
    Deflated Sharpe asks how likely that best is real vs the max of noisy draws. Weak at this
    trial count (a handful of rows) - reported as a floor, not a verdict."""
    rows = [r for r in rows if r is not None]
    if len(rows) < 2:
        return
    srs = [r[2] for r in rows]
    best_i = int(np.argmax(srs))
    n_obs = len(rows[best_i][1])
    d = deflated_sharpe(srs[best_i], srs, n_obs=n_obs)
    if d is None:
        print("  DSR: n/a")
        return
    print(f"  DSR: best='{rows[best_i][0]}' SR={d['observed_sr']:.2f} vs noise ceiling "
          f"{d['noise_ceiling_sr']:.2f} over {d['n_trials']} configs -> P(real)={d['dsr']:.2f} "
          f"(want > 0.95; weak at this trial count)")


STOPS = [("2.0x", 2.0), ("3.0x", 3.0), ("4.0x", 4.0), ("6.0x", 6.0), ("none", 100.0)]
PERIODS = [("2021-10 -> 2022-12", '2021-10-01', '2022-12-31'),
           ("2022-12 -> 2024-09", '2022-12-31', '2024-09-30'),
           ("2024-09 -> 2025-02", '2024-09-30', '2025-02-28'),
           ("2025-02 -> 2025-12", '2025-02-28', '2025-12-31'),
           ("2025-12 -> 2026-07", '2025-12-31', '2026-07-29')]


def _subset(panel, start, end):
    sub = [(t, cp, d[(d['date'] >= start) & (d['date'] <= end)].reset_index(drop=True))
           for t, cp, d in panel]
    return [(t, cp, d) for t, cp, d in sub if len(d) > HORIZON + 20]


def stop_period_row(label, sub):
    """net/trade per stop width for one period, with z_paired for the live 2x and candidate 4x."""
    nets, z2, z4, ntr = [], float('nan'), float('nan'), 0
    for sl, stop in STOPS:
        s, c = collect(sub, liquid_rsi30, MIDSMALL, {'stop_atr_mult': stop})
        if len(s) < 30:
            nets.append("   n/a")
            continue
        clu = day_clustered_edge(s, c)
        nets.append(f"{np.mean([t['net_pct'] for t in s]):+6.2f}")
        if sl == "2.0x":
            ntr = len(s)
            z2 = clu['z_paired'] if clu else float('nan')
        if sl == "4.0x":
            z4 = clu['z_paired'] if clu else float('nan')
    print(f"  {label:<20} {ntr:>5}  " + "  ".join(nets) + f"   | {z2:>5.2f}/{z4:<5.2f}")


def run():
    panel = load_panel()
    print(f"Panel: {len(panel)} stocks, {panel[0][2]['date'].min().date()} -> "
          f"{panel[0][2]['date'].max().date()}, horizon {HORIZON}d, costs charged")
    print("Entry FIXED = RSI<30, Mid/Small, turnover >= Rs25cr (the live signal). Only exit varies.")
    print("z_paired = day-clustered vs same-day random control  <-- the honest number")
    print("held     = avg trading days held   |   st/tg/rs/tm = exit-reason mix %% (stop/target/rsi/time)\n")

    # ---- TEST 1: stop width. Only stop_atr_mult moves; target and horizon fixed at baseline. ----
    print("=" * 96)
    print("TEST 1 - Stop width (target 2xATR, 6-day time both fixed; row E = effectively no stop)")
    print(HEADER)
    t1 = []
    for label, stop in [("A 2.0xATR (live)", 2.0), ("B 3.0xATR", 3.0), ("C 4.0xATR", 4.0),
                        ("D 6.0xATR", 6.0), ("E none (100x)", 100.0)]:
        s, c = collect(panel, liquid_rsi30, MIDSMALL, {'stop_atr_mult': stop})
        t1.append(row(label, s, c))
    dsr_footer(t1)
    print("  Read: if net/tr and z_paired climb A->E, the 2xATR stop is costing edge. But weight")
    print("  row C for real use - row E has unbounded single-trade risk a small account can't survive.")

    # ---- TEST 1B: does the wider stop still help in each period, esp. the recent negative one? ----
    print("\n" + "=" * 96)
    print("TEST 1B - Stop width across chronological periods (net/trade per stop; the 5y avg hides regimes)")
    print(f"  {'period':<20} {'trds':>5}  {'2.0x':>6}  {'3.0x':>6}  {'4.0x':>6}  {'6.0x':>6}  "
          f"{'none':>6}   | zp 2x/4x")
    for label, start, end in PERIODS:
        stop_period_row(label, _subset(panel, start, end))
    print("  Read: adopt 4xATR only if it beats 2x in the RECENT window too, not just on the 5y avg.")
    print("  If the last row is negative at every stop, no exit tweak fixes a dead entry signal.")

    # ---- TEST 2: RSI-recovery exit vs the fixed 6-day clock. Stop/target fixed at baseline. ----
    print("\n" + "=" * 96)
    print("TEST 2 - RSI-recovery exit vs fixed 6-day clock (stop 2xATR, target 2xATR both fixed)")
    print(HEADER)
    t2 = []
    for label, er in [("A 6-day clock (live)", None), ("B rsi>=40", 40), ("C rsi>=45", 45),
                     ("D rsi>=50 (standard)", 50), ("E rsi>=55", 55)]:
        kw = {} if er is None else {'exit_rsi': er}
        s, c = collect(panel, liquid_rsi30, MIDSMALL, kw)
        t2.append(row(label, s, c))
    dsr_footer(t2)
    print("  Read: the win is equal-or-better net/tr at a SHORTER 'held' - less cost drag, capital")
    print("  freed sooner. A higher net alone with unchanged hold is a weaker result than it looks.")

    print("\n" + "=" * 96)
    print("Rows within a test are subdivisions of one dataset -> individual z_paired carry")
    print("multiplicity; the DSR line is the (weak, few-trial) search-adjusted guard.")


if __name__ == "__main__":
    try:
        run()
    except FileNotFoundError:
        print("cache/backtest_5y_short.pkl not found - run refresh_cache.py / build the 5y panel first.")
