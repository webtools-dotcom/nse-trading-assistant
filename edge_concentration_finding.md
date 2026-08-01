# Ranking test + the edge-concentration finding (2026-08-01)

`backtest_ranking.py`. 3,502 candidate trades on 721 days, 2021-10 → 2026-07, mid/small,
≥₹25cr, costs charged. Each scheme ranks that day's candidates and takes the top N; schemes are
compared **paired on the same days**, so none can win by trading on easier days.

## Part 1 — the question asked: do price / CGO rankings beat the current sort?

**No.** Neither improves on the existing net-EV sort at any depth.

| Scheme | top-1 net/trade | vs net_ev | top-2 | vs net_ev |
|---|---|---|---|---|
| net_ev (current sort) | −0.008% | ref | −0.037% | ref |
| random pick | −0.402% | −2.08 z | −0.182% | −1.46 z |
| deep RSI | −0.074% | −0.56 z | −0.118% | −1.10 z |
| price_low | −0.277% | −1.35 z | −0.297% | **−2.39 z** |
| cgo_high | −0.224% | −1.14 z | −0.162% | −1.13 z |
| composite | −0.005% | +0.02 z | −0.168% | −1.37 z |

Two things follow:

1. **The existing net-EV sort is validated** — it beats random candidate selection
   significantly (−2.08, −1.46, −2.58 against it at N=1/2/3). Ranking genuinely matters, and
   the current one is doing real work. That had never been measured.
2. **Price and CGO are rejected as ranking inputs.** `price_low` is significantly *worse* than
   the current sort at N=2. The per-trade uplift seen in `backtest_stock_proxies.py` does not
   survive once you compare selections made on the same day.

## Part 2 — the finding that matters more

**Every scheme is negative at 1–3 trades per day, while the full candidate set averages
+0.531%.** That is not a ranking problem. Taking a few trades per day is itself the problem.

| Mean net per trade | |
|---|---|
| trade-weighted (take everything) | **+0.531%** |
| day-equal-weighted (a few per day) | **−0.190%** |

Sorted by how many candidates competed that day:

| candidates that day | days | trades | mean net | win rate | share of total profit |
|---|---|---|---|---|---|
| 1 | 239 | 239 | +0.124% | 47.3% | 1.6% |
| 2 | 137 | 274 | −0.803% | 43.8% | −11.8% |
| 3 | 79 | 237 | −0.632% | 47.3% | −8.0% |
| 4–5 | 82 | 365 | −0.865% | 43.6% | −17.0% |
| 6–10 | 103 | 796 | −0.182% | 50.1% | −7.8% |
| 11–20 | 54 | 734 | +0.894% | 58.4% | 35.3% |
| **21+** | **27** | **857** | **+2.339%** | **65.1%** | **107.7%** |

**81 days out of 721 — 11% — carry the entire profit.** Every bucket below 11 candidates is
negative or flat.

### Why this is credible rather than a data-mining artefact

It is the same effect the README already validated independently, measured a different way.
Days with many simultaneous oversold names *are* high-volatility panic days, and the vol-regime
table already shows the edge lives there (calmest quartile −0.81%/trade, most volatile quartile
+1.64%, z=9.27, n=2,959). Candidate count is a more direct proxy for the same thing.

### What it means practically

The headline **+0.53%/trade assumes you take every signal**. A trader taking two or three names
on a normal day is trading the negative buckets. This does not invalidate the strategy — it
says the strategy is a *panic-day* strategy, and spreading trades evenly across the calendar
converts a positive expectancy into a negative one.

### Caveats before acting on it

- This is an **in-sample bucket sort**, not a validated rule. Nothing has been walk-forwarded,
  search-adjusted, or tested out-of-sample.
- Candidate count is not knowable before the scan runs, but it *is* knowable before you trade,
  so a rule built on it is implementable without look-ahead.
- The thresholds (11, 21) are read off this table and would be curve-fit if adopted as-is. The
  monotonic gradient across buckets is the finding; the cut-points are not.
- Position sizing already scales down in calm markets via the vol-regime rule, so part of this
  may already be handled. Whether candidate count adds anything *beyond* the vol percentile is
  untested.

---

# VALIDATION (2026-08-01) — partly confirmed, but it is mostly market beta

`backtest_concentration.py`. Four tests. **Verdict: do not hardcode a candidate-count gate.**

## A. Walk-forward — direction replicates, significance does not

Threshold chosen on training data only, applied to the held-out fold:

| fold | train thr | test high-count | test low-count | z_day |
|---|---|---|---|---|
| 1 | 6 | +1.907% (176 tr) | −0.149% (231 tr) | 1.49 |
| 2 | 4 | +1.451% (190 tr) | +0.594% (165 tr) | −0.99 |
| 3 | 4 | +1.027% (732 tr) | −0.173% (116 tr) | −0.08 |
| 4 | 5 | +1.445% (439 tr) | +0.281% (132 tr) | 0.60 |
| 5 | 5 | −0.581% (621 tr) | −1.504% (143 tr) | 0.33 |

High-count days beat low-count days in **5 of 5 folds** (sign test p≈0.03), including fold 5
where both are negative. But no individual fold is statistically significant, and fold 2's
day-clustered z is negative. Direction is consistent; magnitude is not established.

## B. Versus random control — this is what deflates the finding

| candidates | strategy | random control | edge | z_day |
|---|---|---|---|---|
| 1–2 | −0.371% | −0.722% | +0.351% | 1.68 |
| 3–5 | −0.773% | −0.953% | +0.180% | 0.56 |
| 6–10 | −0.182% | −0.719% | +0.537% | 0.85 |
| 11–20 | +0.894% | +0.251% | +0.643% | 1.05 |
| **21+** | **+2.339%** | **+1.271%** | +1.068% | 0.81 |

**Random entries also earn +1.271% on 21+ candidate days.** Roughly half the concentration is
the market bouncing, not the signal working better. The strategy's *edge over random* rises
only mildly across buckets (+0.35 → +1.07%) and is not significant in any bucket.

So "the edge is concentrated on 11% of days" was overstated in the section above. What is
concentrated is **absolute return**, which is largely beta. The RSI signal's edge over random
is roughly flat across candidate counts.

## C. Beyond the vol-regime rule? — overlapping, incrementally unproven

`corr(vol percentile, candidate count) = 0.394` — related, not redundant. Strategy net/trade:

| vol quartile | few | mid | many |
|---|---|---|---|
| calm | −1.292% | −0.301% | −0.052% |
| q2 | −0.552% | −1.431% | +0.004% |
| q3 | −0.627% | +1.260% | +2.865% |
| panic | +0.171% | +1.442% | +2.344% |

Candidate count separates *within* every vol quartile, which is the right shape for added
information. But within the panic quartile alone, many-vs-few gives z_day = 0.79 — suggestive,
not established. The existing vol-percentile sizing rule already captures most of this.

## D. Gradient shape — the strongest result

Across deciles of candidate count, Spearman **rho = 0.842, p = 0.0022**, rising from −0.371%
(median 2 candidates) to +3.073% (median 43). A smooth monotonic gradient, not a single spiking
bucket — so the pattern itself is not a curve-fit artefact, whatever its cause.

## Conclusion

Real pattern, wrong explanation. The gradient is robust (D) and directionally replicates out of
sample (A), but it is substantially market beta rather than signal quality (B), and what remains
is largely already handled by the volatility-percentile sizing rule (C).

**Not adopted as a gate or a sizing input.** A rule saying "only trade when many names trigger"
is a market-timing rule wearing a signal's clothes, and market-timing rules are exactly what
failed in `backtest_flow_gate.py`.

**What is justified**: report the candidate count in the scan output as context. It is real
information, it is free, and a trader seeing "2 candidates today" versus "31 candidates today"
is seeing something that genuinely predicts their absolute return — provided it is labelled as
market conditions rather than as signal strength.
