"""Honest backtest engine - one implementation, replacing the copy-pasted simulate_trades()
in every backtest_*.py file.

What this fixes versus the old per-file code:

1. NON-OVERLAPPING TRADES. The old code opened a trade on every bar the signal was true.
   RSI stays below 30 for days, so one oversold episode became ~3.4 near-identical trades
   sharing the same forward returns, while compute_stats divided by sqrt(n) as if they were
   independent. Measured inflation on this project's cache: 1.70x on every z-score.
   (Lopez de Prado, Advances in Financial ML, ch.4 - sample uniqueness.)

2. TRANSACTION COSTS. The old code charged zero. On a 4-6 day mid/small-cap hold the Indian
   cost stack is the same order of magnitude as the edge itself.

3. HONEST FILLS. The old code filled stops at exactly stop_loss. Gaps blow through stops;
   filling at min(open, stop) removes a persistent optimistic bias.

4. WALK-FORWARD with purge + embargo, so a 6-day label cannot straddle the train/test
   boundary and leak.

5. SEARCH-ADJUSTED SIGNIFICANCE. Block-bootstrap permutation for anything chosen by scanning
   thresholds, plus a Deflated Sharpe Ratio that accounts for how many trials were run.
"""

import numpy as np
import pandas as pd
from scipy import stats

from config import round_trip_cost_pct


# ============================================================
# Trade simulation
# ============================================================

def simulate_trades(stock_df, entry_mask, horizon_days=6, stop_atr_mult=2.0,
                    target_atr_mult=2.0, charge_costs=True, allow_overlap=False,
                    exit_rsi=None):
    """Simulate trades for one stock.

    entry_mask: boolean array aligned to stock_df rows.
    Returns list of dicts with gross/net return and exit reason.

    allow_overlap=False (the default, and the honest one) takes at most one trade per
    signal episode - no new entry until the previous trade has exited.

    exit_rsi (None = off): if set, the trade also exits when RSI recovers to this level,
    filled on the NEXT open. This is the mean-reversion exit - it bets the trade's thesis
    (a temporary oversold dip) is spent once RSI is back up. Stop and target still take
    priority within a bar; the time exit becomes only a backstop for dips that never revert.
    """
    df = stock_df.reset_index(drop=True)
    mask = np.asarray(entry_mask)
    n = len(df)
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    open_ = df['open'].values if 'open' in df.columns else close
    atr = df['atr'].values
    rsi = df['rsi'].values if 'rsi' in df.columns else None

    turnover = None
    if 'turnover_60d' in df.columns:
        turnover = df['turnover_60d'].values

    trades = []
    last_exit = -1
    for i in np.where(mask)[0]:
        if i >= n - horizon_days - 1:
            break
        if not allow_overlap and i <= last_exit:
            continue
        if not np.isfinite(close[i]) or not np.isfinite(atr[i]) or atr[i] <= 0 or close[i] <= 0:
            continue

        entry = close[i]
        stop = entry - stop_atr_mult * atr[i]
        target = entry + target_atr_mult * atr[i]

        exit_price, reason, held = None, None, horizon_days
        for j in range(1, horizon_days + 1):
            k = i + j
            # Gap through the stop: you are filled at the open, not at your stop price.
            if open_[k] <= stop:
                exit_price, reason, held = open_[k], 'stop_gap', j
                break
            if low[k] <= stop:
                exit_price, reason, held = stop, 'stop', j
                break
            # Conservative: if both barriers are touched intrabar, assume the stop hit first.
            if high[k] >= target:
                exit_price, reason, held = target, 'target', j
                break
            # RSI recovered to the exit level: the reversion this trade bet on has played out.
            # Fill on the NEXT open - RSI is only known at this bar's close, so exiting at that
            # same close would be look-ahead.
            if exit_rsi is not None and rsi is not None and np.isfinite(rsi[k]) and rsi[k] >= exit_rsi:
                nxt = i + j + 1
                if nxt < n:
                    exit_price, reason, held = open_[nxt], 'rsi_recover', j + 1
                else:
                    exit_price, reason, held = close[k], 'rsi_recover', j
                break
        if exit_price is None:
            exit_price, reason, held = close[i + horizon_days], 'time', horizon_days

        gross = (exit_price - entry) / entry * 100
        cost = round_trip_cost_pct(turnover[i] if turnover is not None else None) if charge_costs else 0.0
        trades.append({
            'entry_idx': int(i), 'exit_idx': int(i + held),
            'gross_pct': gross, 'net_pct': gross - cost, 'cost_pct': cost,
            'reason': reason, 'held': held,
        })
        last_exit = i + held

    return trades


def average_uniqueness(trades, n_bars):
    """Fraction of each trade's lifespan not shared with other trades. 1.0 = fully independent.
    Diagnostic: sqrt(1/uniqueness) is roughly the factor by which naive z-scores are inflated."""
    if not trades:
        return 1.0
    conc = np.zeros(n_bars + 1)
    for t in trades:
        conc[t['entry_idx']:t['exit_idx'] + 1] += 1
    vals = []
    for t in trades:
        span = conc[t['entry_idx']:t['exit_idx'] + 1]
        vals.append(np.mean(1.0 / np.maximum(span, 1)))
    return float(np.mean(vals)) if vals else 1.0


# ============================================================
# Statistics
# ============================================================

def edge_vs_control(strategy_returns, control_returns):
    """Welch two-sample test of strategy against a random-entry control.

    Assumes both samples are independent - which is only true if trades were generated
    non-overlapping. Run with allow_overlap=False or this understates the standard error.
    """
    s = np.asarray([r for r in strategy_returns if np.isfinite(r)])
    c = np.asarray([r for r in control_returns if np.isfinite(r)])
    if len(s) < 2 or len(c) < 2:
        return None
    se = np.sqrt(s.var(ddof=1) / len(s) + c.var(ddof=1) / len(c))
    edge = s.mean() - c.mean()
    z = edge / se if se > 0 else 0.0
    return {
        'n_strategy': len(s), 'n_control': len(c),
        'strategy_avg': float(s.mean()), 'control_avg': float(c.mean()),
        'edge': float(edge), 'z': float(z),
        'p_value': float(2 * (1 - stats.norm.cdf(abs(z)))),
        'win_rate': float((s > 0).mean() * 100),
    }


def day_clustered_edge(trades, control_trades):
    """Edge vs control with inference clustered by ENTRY DATE.

    edge_vs_control() assumes trades are independent. Non-overlapping entries make that true
    WITHIN a stock, but not ACROSS stocks: on any given day hundreds of names can trigger
    together and their forward returns share one market factor. 1,125 trades spread over 112
    days carry roughly 112 observations' worth of information, not 1,125 - the cross-sectional
    twin of the overlapping-trade problem in this module's docstring.

    Both trade lists must carry an 'entry_date' key.

    Returns 'z_paired' as the headline: each day's strategy mean against the SAME day's control
    mean. Pairing nets out the common market factor rather than merely acknowledging it, so it
    isolates stock-selection skill and is more powerful than the unpaired day test.
    """
    if not trades or not control_trades:
        return None
    s = pd.Series([t['net_pct'] for t in trades],
                  index=[t['entry_date'] for t in trades]).groupby(level=0).mean()
    c = pd.Series([t['net_pct'] for t in control_trades],
                  index=[t['entry_date'] for t in control_trades]).groupby(level=0).mean()
    if len(s) < 3 or len(c) < 3:
        return None

    se = np.sqrt(s.var(ddof=1) / len(s) + c.var(ddof=1) / len(c))
    unpaired_z = float((s.mean() - c.mean()) / se) if se > 0 else 0.0

    paired = (s - c).dropna()
    z_paired = (float(paired.mean() / (paired.std(ddof=1) / np.sqrt(len(paired))))
                if len(paired) > 2 and paired.std(ddof=1) > 0 else 0.0)

    return {
        'n_days': len(s), 'n_paired_days': len(paired),
        'day_edge': float(paired.mean()) if len(paired) else 0.0,
        'z_day': unpaired_z, 'z_paired': z_paired,
    }


def sharpe(returns, periods_per_year=252, holding_days=6):
    """Trade-level Sharpe annualised by trade frequency."""
    r = np.asarray([x for x in returns if np.isfinite(x)]) / 100.0
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    trades_per_year = periods_per_year / max(holding_days, 1)
    return float(r.mean() / r.std(ddof=1) * np.sqrt(trades_per_year))


def deflated_sharpe(observed_sr, all_trial_srs, n_obs, skew=0.0, kurtosis=3.0):
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).

    Answers: given that we tried N strategies and picked the best, how likely is this
    Sharpe to reflect real skill rather than the maximum of N noisy draws?

    On pure noise, the naive best-of-N test declares a discovery ~100% of the time; DSR
    brings that to ~0.1%. Returns probability the true Sharpe exceeds zero - want > 0.95.

    all_trial_srs should be the EFFECTIVE independent trials. Correlated trials (e.g. a
    threshold sweep) over-deflate if you pass the raw count; see effective_trials().
    """
    trials = np.asarray([s for s in all_trial_srs if np.isfinite(s)])
    n_trials = max(len(trials), 1)
    if n_trials < 2 or n_obs < 3:
        return None

    var_sr = trials.var(ddof=1)
    if var_sr <= 0:
        return None

    # Expected maximum Sharpe under the null of zero true skill (Extreme Value Theory).
    euler = 0.5772156649
    e_max = np.sqrt(var_sr) * (
        (1 - euler) * stats.norm.ppf(1 - 1.0 / n_trials)
        + euler * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    )

    denom = np.sqrt(max(1e-12, 1 - skew * e_max + (kurtosis - 1) / 4.0 * e_max ** 2) / (n_obs - 1))
    return {
        'observed_sr': float(observed_sr),
        'noise_ceiling_sr': float(e_max),
        'n_trials': int(n_trials),
        'dsr': float(stats.norm.cdf((observed_sr - e_max) / denom)),
    }


def effective_trials(trial_returns):
    """Effective number of independent trials, from the correlation structure.

    A threshold sweep produces highly correlated trials; feeding the raw count to
    deflated_sharpe over-deflates and can false-reject a genuine edge. Uses the
    participation-ratio of the correlation eigenvalues.
    """
    mats = [np.asarray(r) for r in trial_returns if len(r) > 1]
    if len(mats) < 2:
        return len(mats)
    m = min(len(x) for x in mats)
    if m < 3:
        return len(mats)
    stacked = np.vstack([x[:m] for x in mats])
    corr = np.corrcoef(stacked)
    corr = np.nan_to_num(corr, nan=0.0)
    eig = np.linalg.eigvalsh(corr)
    eig = eig[eig > 0]
    if len(eig) == 0:
        return len(mats)
    return float(eig.sum() ** 2 / (eig ** 2).sum())


# ============================================================
# Search-adjusted significance
# ============================================================

def block_bootstrap_pvalue(stock_dfs, signal_fn, thresholds, horizon_days=6,
                           n_iter=200, block=10, seed=42):
    """Search-adjusted p-value for a threshold chosen by scanning.

    Reporting the best of K thresholds treats a maximum-of-K statistic as a single test.
    For K=41 at alpha=0.05 the family-wise error rate is ~88%. Bonferroni over-corrects
    because the thresholds are correlated. The honest correction is empirical: shuffle in
    blocks (preserving autocorrelation and volatility clustering), re-run the WHOLE sweep,
    and see how often noise alone produces a winner this good.
    """
    rng = np.random.default_rng(seed)

    def best_stat(dfs):
        best = -np.inf
        for th in thresholds:
            rets = []
            for df in dfs:
                rets += [t['net_pct'] for t in
                         simulate_trades(df, signal_fn(df, th), horizon_days=horizon_days)]
            if len(rets) > 30:
                best = max(best, float(np.mean(rets)))
        return best

    observed = best_stat(stock_dfs)

    worse = 0
    for _ in range(n_iter):
        shuffled = []
        for df in stock_dfs:
            n = len(df)
            starts = rng.integers(0, max(1, n - block), size=int(np.ceil(n / block)))
            idx = np.concatenate([np.arange(s, min(s + block, n)) for s in starts])[:n]
            sh = df.iloc[idx].reset_index(drop=True)
            shuffled.append(sh)
        if best_stat(shuffled) >= observed:
            worse += 1

    return {'observed_best': observed, 'p_value': (worse + 1) / (n_iter + 1), 'n_iter': n_iter}


def plateau_check(threshold_stats, chosen, tolerance=0.20, max_drop=0.10):
    """Real signal sits on a smooth plateau OR a monotonic gradient; curve-fit sits on a spike.

    threshold_stats: {threshold: statistic}. Returns whether shifting the chosen threshold
    by +/-tolerance of the scanned range changes the statistic by less than max_drop
    (relative). A threshold that fails this is fragile regardless of its p-value.

    MONOTONIC curves are treated as robust, not fragile. If the statistic rises steadily as
    the threshold tightens there is no interior peak being fitted - the "threshold" is a
    tradeoff between per-trade edge and trade count, not a selected optimum. Flagging that
    as a spike (which an earlier version of this function did) inverts the conclusion.
    """
    ths = sorted(threshold_stats)
    if chosen not in threshold_stats or len(ths) < 3:
        return {'plateau': False, 'reason': 'insufficient sweep'}

    vals = [threshold_stats[t] for t in ths]
    diffs = np.diff(vals)
    if np.all(diffs >= 0) or np.all(diffs <= 0):
        return {'plateau': True, 'monotonic': True, 'chosen_stat': threshold_stats[chosen],
                'reason': 'monotonic gradient - no interior optimum being fitted, robust'}
    span = (max(ths) - min(ths)) * tolerance
    picked = [t for t in ths if abs(t - chosen) <= span and t != chosen]
    # On a coarse grid the tolerance band can be narrower than the grid spacing, leaving no
    # neighbours at all. Always fall back to the immediately adjacent thresholds - checking
    # the nearest points is the whole intent.
    i = ths.index(chosen)
    for j in (i - 1, i + 1):
        if 0 <= j < len(ths) and ths[j] not in picked:
            picked.append(ths[j])
    neighbours = [threshold_stats[t] for t in picked]
    if not neighbours:
        return {'plateau': False, 'reason': 'no neighbours available'}
    base = threshold_stats[chosen]
    worst_drop = max((base - v) / abs(base) for v in neighbours) if base != 0 else 1.0
    return {
        'plateau': bool(worst_drop <= max_drop),
        'chosen_stat': base,
        'worst_relative_drop': float(worst_drop),
        'reason': 'smooth region' if worst_drop <= max_drop else 'single-spike / fragile',
    }


# ============================================================
# Walk-forward with purge + embargo
# ============================================================

def walk_forward_splits(n_bars, n_splits=4, horizon_days=6, embargo_pct=0.01):
    """Chronological train/test splits that respect label spans.

    A 6-day label starting just before the boundary would otherwise straddle it and leak.
    Purge removes training bars whose labels overlap the test window; embargo additionally
    drops bars immediately after it (serial correlation leaks forward too).
    """
    embargo = int(n_bars * embargo_pct)
    fold = n_bars // (n_splits + 1)
    for k in range(1, n_splits + 1):
        train_end = fold * k
        test_start, test_end = train_end, min(train_end + fold, n_bars)
        if test_end - test_start < horizon_days + 2:
            continue
        purged_train_end = max(0, train_end - horizon_days - embargo)
        if purged_train_end < horizon_days + 2:
            continue
        yield (0, purged_train_end), (test_start, test_end)


# ============================================================
# Reporting
# ============================================================

def report(name, strategy_trades, control_trades, n_bars=None, holding_days=6):
    """One consistent summary block: gross, net, uniqueness, edge vs control."""
    s_gross = [t['gross_pct'] for t in strategy_trades]
    s_net = [t['net_pct'] for t in strategy_trades]
    c_net = [t['net_pct'] for t in control_trades]

    res = edge_vs_control(s_net, c_net)
    lines = [f"--- {name} ---"]
    if res is None:
        lines.append("  insufficient trades")
        return "\n".join(lines)

    avg_cost = np.mean([t['cost_pct'] for t in strategy_trades]) if strategy_trades else 0.0
    lines += [
        f"  trades              : {res['n_strategy']}",
        f"  gross avg/trade     : {np.mean(s_gross):+.3f}%",
        f"  avg round-trip cost : {avg_cost:.3f}%",
        f"  NET avg/trade       : {res['strategy_avg']:+.3f}%",
        f"  control (random)    : {res['control_avg']:+.3f}%",
        f"  edge vs control     : {res['edge']:+.3f}%",
        f"  z-score             : {res['z']:.2f}   (p={res['p_value']:.4g})",
        f"  win rate            : {res['win_rate']:.1f}%",
        f"  Sharpe (annualised) : {sharpe(s_net, holding_days=holding_days):.2f}",
    ]
    if n_bars:
        u = average_uniqueness(strategy_trades, n_bars)
        lines.append(f"  label uniqueness    : {u:.3f} (naive-z inflation if overlapping: {np.sqrt(1/u):.2f}x)")
    return "\n".join(lines)


# ============================================================
# Self-check
# ============================================================

def _synthetic(n=1500, edge=0.0, seed=0):
    """Series with a controllable, RSI-detectable edge.

    The drift is conditioned on a SUSTAINED decline (trailing 10-bar return), not a single
    down bar, because RSI(14) only reaches oversold after persistent selling. Keying the
    injected edge to a one-day drop produces a signal RSI cannot see - which is a bug in
    the test, not the engine.
    """
    rng = np.random.default_rng(seed)
    price = [100.0]
    steps = []
    for _ in range(n):
        trailing = sum(steps[-10:])
        drift = edge if trailing < -4.0 else 0.0
        step = rng.normal(drift, 1.2)
        steps.append(step)
        price.append(max(1.0, price[-1] * (1 + step / 100)))
    close = pd.Series(price[1:])
    df = pd.DataFrame({
        'date': pd.date_range('2020-01-01', periods=n, freq='B'),
        'open': close, 'high': close * 1.01, 'low': close * 0.99, 'close': close,
        'volume': 1e6, 'turnover_60d': 1e9,
    })
    from features import add_short_features
    return add_short_features(df).dropna(subset=['rsi', 'atr']).reset_index(drop=True)


def demo():
    rng = np.random.default_rng(7)

    # 1. A real edge must be recovered.
    edged = [_synthetic(edge=0.9, seed=s) for s in range(6)]
    strat, ctrl = [], []
    for df in edged:
        strat += simulate_trades(df, (df['rsi'] < 30).values, charge_costs=False)
        ctrl += simulate_trades(df, rng.random(len(df)) < 0.10, charge_costs=False)
    res = edge_vs_control([t['net_pct'] for t in strat], [t['net_pct'] for t in ctrl])
    assert res is not None and res['z'] > 2, f"failed to recover a real edge (z={res['z'] if res else None})"

    # 2. Pure noise must NOT produce significance. This is the test that matters.
    noise = [_synthetic(edge=0.0, seed=100 + s) for s in range(6)]
    nstrat, nctrl = [], []
    for df in noise:
        nstrat += simulate_trades(df, (df['rsi'] < 30).values, charge_costs=False)
        nctrl += simulate_trades(df, rng.random(len(df)) < 0.10, charge_costs=False)
    nres = edge_vs_control([t['net_pct'] for t in nstrat], [t['net_pct'] for t in nctrl])
    assert nres is None or abs(nres['z']) < 3, f"found significance in pure noise (z={nres['z']})"

    # 3. Non-overlapping must yield strictly fewer trades than overlapping.
    df = edged[0]
    m = (df['rsi'] < 30).values
    assert len(simulate_trades(df, m, allow_overlap=False)) < len(simulate_trades(df, m, allow_overlap=True))

    # 4. Non-overlapping trades never overlap.
    tr = simulate_trades(df, m, allow_overlap=False)
    assert all(a['exit_idx'] < b['entry_idx'] for a, b in zip(tr, tr[1:])), "overlap leaked through"

    # 5. Costs must reduce net return by exactly the charged amount.
    free = simulate_trades(df, m, charge_costs=False)
    paid = simulate_trades(df, m, charge_costs=True)
    assert all(abs((f['gross_pct'] - p['net_pct']) - p['cost_pct']) < 1e-9 for f, p in zip(free, paid))
    assert paid[0]['cost_pct'] > 0, "costs were not charged"

    # 5b. The RSI-recovery exit must actually fire and be labelled (an oversold-bounce synthetic
    #     recovers RSI within the horizon, so at least one trade should exit on it).
    rsi_ex = simulate_trades(df, m, charge_costs=False, exit_rsi=45)
    assert any(t['reason'] == 'rsi_recover' for t in rsi_ex), "exit_rsi branch never fired"

    # 6. Deflated Sharpe must reject the best of many pure-noise trials.
    noise_srs = [sharpe(rng.normal(0, 6, 400), holding_days=6) for _ in range(200)]
    d = deflated_sharpe(max(noise_srs), noise_srs, n_obs=400)
    assert d is not None and d['dsr'] < 0.95, f"DSR failed to reject a noise winner (dsr={d['dsr']:.3f})"

    # 7. Walk-forward splits must be purged: train must end before test starts.
    for (tr0, tr1), (te0, te1) in walk_forward_splits(1000, n_splits=4, horizon_days=6):
        assert tr1 <= te0 - 6, "purge gap missing - labels can straddle the split"

    # 8. Plateau check must distinguish a smooth region from a spike, and must treat a
    #    monotonic gradient as robust rather than fragile.
    assert plateau_check({20: 1.0, 25: 1.05, 30: 1.1, 35: 1.06, 40: 1.0}, 30)['plateau']
    assert not plateau_check({20: 0.2, 25: 0.2, 30: 1.1, 35: 0.2, 40: 0.2}, 30)['plateau']
    mono = plateau_check({24: 1.17, 26: 0.85, 28: 0.69, 30: 0.53, 32: 0.42}, 26)
    assert mono['plateau'] and mono.get('monotonic'), "monotonic gradient misread as fragile"

    # 9. Day-clustering must deflate a result whose trades all sit on a few dates.
    #    500 trades on 4 days is 4 observations, not 500 - the naive test must not survive it.
    days = pd.to_datetime(['2024-01-02', '2024-02-05', '2024-03-07', '2024-04-09'])
    strat_t, ctrl_t = [], []
    for d_i, d in enumerate(days):
        daily = rng.normal([1.5, -0.9, 2.1, -0.4][d_i], 0.3, 125)
        strat_t += [{'net_pct': float(x), 'entry_date': d} for x in daily]
        ctrl_t += [{'net_pct': float(x), 'entry_date': d} for x in rng.normal(0, 0.3, 125)]
    naive = edge_vs_control([t['net_pct'] for t in strat_t], [t['net_pct'] for t in ctrl_t])
    clustered = day_clustered_edge(strat_t, ctrl_t)
    assert abs(naive['z']) > 4, "test setup: naive z should look significant here"
    assert abs(clustered['z_paired']) < abs(naive['z']) / 2, (
        f"clustering failed to deflate day-concentrated trades "
        f"(naive z={naive['z']:.1f}, paired z={clustered['z_paired']:.1f})")
    assert clustered['n_days'] == 4

    print("backtest_engine.py self-check passed")


if __name__ == "__main__":
    demo()
