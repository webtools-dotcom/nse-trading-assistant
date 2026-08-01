"""Strategy decay detection.

A strategy rarely fails cleanly - it drifts. Drawdowns and structural decay look identical
by eye during the early stages, and by the time the difference is obvious you have already
paid for it. These are the standard tools for telling them apart.

The central diagnostic here is comparing the strategy against its random-entry control over
the same window - the one thing a raw equity curve cannot tell you. A falling equity curve
alone cannot distinguish "the market got hard" from "my signal stopped working"; the control
can, because it is exposed to the market but carries no signal.

Note what this deliberately does NOT do: it does not claim to label a downturn as "regime"
versus "decay". Both produce the same signature - a vanished edge - and a single recent
period cannot separate them. It reports whether the edge is still detectable, and gives the
market's own behaviour as context, leaving the cause open until more data arrives.
"""

import numpy as np
import pandas as pd


def cusum(returns, expected_mean, k_sigma=0.5, h_sigma=7.0):
    """One-sided CUSUM for a downward shift in mean return (Page, 1954).

    Accumulates evidence that realised returns have fallen below `expected_mean`. Noise
    resets the statistic toward zero; a real shift makes it climb until it crosses h.

    k_sigma is the slack (shifts smaller than this are ignored), h_sigma the alarm threshold.

    h_sigma=7 was calibrated EMPIRICALLY, not from the textbook. The standard k=0.5/h=5
    pairing assumes a known mean and variance; here both are estimated from a short sample,
    which adds enough extra variance that h=5 cries wolf far more often than its nominal
    average-run-length suggests. Measured false-alarm rate on stationary noise (300 trials):

        h=4: 24% @100 obs, 42% @200, 69% @400      <- unusable
        h=5: 10% @100 obs, 17% @200, 34% @400
        h=6:  3% @100 obs,  7% @200, 16% @400
        h=7:  1% @100 obs,  2% @200,  7% @400      <- default
        h=8:  1% @100 obs,  1% @200,  4% @400

    Detection power against a genuine mean break is 100% at every one of these thresholds,
    so the higher bar costs some detection speed but no detection. Tune h_sigma down if you
    would rather be warned early and tolerate false alarms.
    """
    r = np.asarray([x for x in returns if np.isfinite(x)], dtype=float)
    if len(r) < 5:
        return {'alarm': False, 'reason': 'insufficient observations', 'n': len(r)}
    sigma = r.std(ddof=1)
    if sigma == 0:
        return {'alarm': False, 'reason': 'zero variance', 'n': len(r)}

    k, h = k_sigma * sigma, h_sigma * sigma
    s, series, alarm_at = 0.0, [], None
    for i, x in enumerate(r):
        s = max(0.0, s + (expected_mean - x) - k)
        series.append(s)
        if alarm_at is None and s > h:
            alarm_at = i
    # 'alarm' means CURRENTLY above threshold, not "crossed at some point in history". A
    # transient that fired years ago and reset is not a live warning, and reporting it as one
    # makes the alarm useless. ever_fired keeps the history without crying wolf now.
    return {
        'alarm': float(series[-1]) > h,
        'ever_fired': alarm_at is not None,
        'first_fired_index': alarm_at,
        'statistic': float(series[-1]),
        'threshold': float(h),
        'pct_of_threshold': float(series[-1] / h * 100) if h > 0 else 0.0,
        'series': series,
        'n': len(r),
    }


def rolling_mean_return(returns, window=50):
    """Rolling average return - the intuitive view. Noisy, but everyone reads it."""
    r = pd.Series([x for x in returns if np.isfinite(x)], dtype=float)
    if len(r) < window:
        return pd.Series(dtype=float)
    return r.rolling(window).mean()


def diagnose(strategy_returns, control_returns, n_buckets=5, labels=None):
    """Split both series into chronological buckets and assess the edge in the latest one.

    IMPORTANT: pass trades in CHRONOLOGICAL order. Pooling them per-ticker (all of stock A,
    then all of stock B) is not a time series and the buckets become meaningless.

    Verdicts:
      HEALTHY    - edge over the random control is intact in the latest bucket.
      WEAKENING  - edge still positive but materially below its historical level.
      EDGE LOST  - edge was real historically, now indistinguishable from zero.
      INVERTED   - strategy is now significantly WORSE than random entry.
      NO EDGE    - no detectable edge in any period.
    """
    s = np.asarray([x for x in strategy_returns if np.isfinite(x)], dtype=float)
    c = np.asarray([x for x in control_returns if np.isfinite(x)], dtype=float)
    if len(s) < n_buckets * 10 or len(c) < n_buckets * 10:
        return {'verdict': 'INSUFFICIENT DATA', 'buckets': []}

    buckets = []
    for i in range(n_buckets):
        sb = s[len(s) * i // n_buckets: len(s) * (i + 1) // n_buckets]
        cb = c[len(c) * i // n_buckets: len(c) * (i + 1) // n_buckets]
        buckets.append({
            'label': labels[i] if labels and i < len(labels) else f'B{i+1}',
            'strategy': float(sb.mean()), 'control': float(cb.mean()),
            'edge': float(sb.mean() - cb.mean()), 'n': len(sb),
        })

    early_edge = float(np.mean([b['edge'] for b in buckets[:-1]]))
    last = buckets[-1]

    # Is the recent edge distinguishable from zero at all? Judging decay on the SIGN of the
    # edge is far too brittle - an edge of -0.02% with p=0.92 is zero, not decay, and calling
    # it decay sends you hunting for a broken signal when the market simply got harder.
    sb = s[len(s) * (n_buckets - 1) // n_buckets:]
    cb = c[len(c) * (n_buckets - 1) // n_buckets:]
    se = np.sqrt(sb.var(ddof=1) / len(sb) + cb.var(ddof=1) / len(cb))
    z_recent = float(last['edge'] / se) if se > 0 else 0.0
    edge_is_zero = abs(z_recent) < 2.0

    early_control = float(np.mean([b['control'] for b in buckets[:-1]]))
    market_also_fell = last['control'] < early_control

    # Deliberately NOT trying to label "regime vs decay". Both produce the same signature -
    # a vanished edge - and one recent period cannot separate them. An earlier version of this
    # function guessed between them from the relative size of the drops, which is biased
    # (a higher-starting series necessarily falls further to reach the same level) and it
    # flipped verdicts on noise. Report what the data supports; leave the cause open.
    if last['edge'] > early_edge * 0.5:
        verdict = 'HEALTHY'
        detail = 'edge over the random control is intact in the most recent period'
    elif z_recent <= -2.0:
        verdict = 'INVERTED'
        detail = 'strategy is now significantly WORSE than random entry - stop trading this signal'
    elif edge_is_zero and early_edge > 0:
        verdict = 'EDGE LOST'
        detail = ('the edge was real historically but is now statistically indistinguishable from zero. '
                  'Whether this is permanent decay or a hard regime CANNOT be determined from one period')
    elif edge_is_zero:
        verdict = 'NO EDGE'
        detail = 'no detectable edge over random entry in any period'
    else:
        verdict = 'WEAKENING'
        detail = 'edge is positive but materially below its historical level'

    if verdict in ('EDGE LOST', 'INVERTED'):
        detail += (f". Market context: the random control {'ALSO fell' if market_also_fell else 'did NOT fall'} "
                   f"({early_control:+.2f}% -> {last['control']:+.2f}%)"
                   f"{' - consistent with a harder market, not only a broken signal' if market_also_fell else ''}")

    return {'verdict': verdict, 'detail': detail, 'buckets': buckets, 'early_edge': early_edge,
            'recent_edge': last['edge'], 'recent_z': z_recent, 'market_also_fell': market_also_fell}


def format_diagnosis(d):
    if not d['buckets']:
        return f"Decay diagnosis: {d['verdict']}"
    lines = [f"{'period':<14}{'strategy':>11}{'control':>11}{'edge':>11}{'n':>7}"]
    for b in d['buckets']:
        lines.append(f"{b['label']:<14}{b['strategy']:>+10.3f}%{b['control']:>+10.3f}%"
                     f"{b['edge']:>+10.3f}%{b['n']:>7}")
    lines.append(f"\nVERDICT: {d['verdict']} - {d['detail']}")
    lines.append(f"  historical edge {d['early_edge']:+.3f}%  ->  recent edge {d['recent_edge']:+.3f}%")
    return "\n".join(lines)


def demo():
    # Each case gets its OWN seeded generator. Sharing one rng across cases makes every test
    # depend on how many random numbers the previous ones drew, so adding a case silently
    # changes unrelated ones - which is exactly how this file broke twice while being written.
    def gen(seed):
        return np.random.default_rng(seed)

    # n=1000 (200/bucket) at sigma=2 gives an edge standard error of ~0.2, so the injected
    # effects below are unambiguous rather than a coin flip on the noise draw.
    N, SD = 1000, 2.0

    # Healthy: constant edge over control throughout.
    r = gen(1)
    assert diagnose(r.normal(0.8, SD, N), r.normal(0.1, SD, N))['verdict'] == 'HEALTHY'

    # Edge disappears while the control is unchanged -> EDGE LOST, market "did NOT fall".
    r = gen(2)
    s = np.concatenate([r.normal(0.8, SD, 800), r.normal(0.1, SD, 200)])
    c = r.normal(0.1, SD, N)
    res = diagnose(s, c)
    assert res['verdict'] == 'EDGE LOST', f"lost edge misread as {res['verdict']}"
    assert not res['market_also_fell']

    # Edge preserved while both fall -> still HEALTHY; a bad market is not a broken signal.
    r = gen(3)
    s = np.concatenate([r.normal(0.8, SD, 800), r.normal(-0.9, SD, 200)])
    c = np.concatenate([r.normal(0.1, SD, 800), r.normal(-1.6, SD, 200)])
    v = diagnose(s, c)['verdict']
    assert v == 'HEALTHY', f"preserved edge in a falling market misread as {v}"

    # Edge gone AND market fell -> EDGE LOST, with the market context recorded.
    r = gen(4)
    s = np.concatenate([r.normal(0.8, SD, 800), r.normal(-0.55, SD, 200)])
    c = np.concatenate([r.normal(0.1, SD, 800), r.normal(-0.55, SD, 200)])
    res = diagnose(s, c)
    assert res['verdict'] == 'EDGE LOST', f"zero edge in a falling market misread as {res['verdict']}"
    assert res['market_also_fell'] and 'harder market' in res['detail']

    # Genuinely worse than random -> INVERTED.
    r = gen(5)
    s = np.concatenate([r.normal(0.8, SD, 800), r.normal(-1.2, SD, 200)])
    c = np.concatenate([r.normal(0.1, SD, 800), r.normal(+0.1, SD, 200)])
    v = diagnose(s, c)['verdict']
    assert v == 'INVERTED', f"inverted signal misread as {v}"

    # CUSUM must fire on an injected downward break...
    r = gen(6)
    broken = np.concatenate([r.normal(1.0, 3, 200), r.normal(-1.5, 3, 200)])
    assert cusum(broken, expected_mean=1.0)['alarm']

    # ...and stay quiet on stationary noise (see the calibration table on cusum()).
    r = gen(7)
    false_alarms = sum(cusum(r.normal(1.0, 3, 200), expected_mean=1.0)['alarm'] for _ in range(20))
    assert false_alarms <= 3, f"false-alarm rate too high: {false_alarms}/20"

    # A transient that fired long ago and recovered must NOT report a live alarm.
    r = gen(8)
    transient = np.concatenate([r.normal(-3.0, 3, 60), r.normal(1.0, 3, 400)])
    cu = cusum(transient, expected_mean=1.0)
    assert cu['ever_fired'] and not cu['alarm'], "recovered transient still reported as a live alarm"

    print("decay_monitor.py self-check passed")


if __name__ == "__main__":
    demo()
