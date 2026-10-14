# "This stock has already surged too much" — measured

**Question (2026-09-11):** the long-term momentum scan keeps putting the most-extended name
(CUPID) at the top. Should the tool cut names that have already rallied too far, because they
are riskier?

**Answer: don't cut them — label them.**

- **Return:** rises with momentum. An over-extension *filter* would delete the best names. **Rejected.**
- **Risk:** also rises with momentum, monotonically. **P(down >20% in 20 days) goes 2% → 6%.**
  Shipped as a per-name risk label.

The first pass of this study reported only the return half and called the idea dead. That was
wrong, and it was wrong for a specific, repeatable reason recorded in "How the first pass missed
it" below.

Script: `backtest_longterm_extension.py`. Panel: `cache/backtest_5y_long.pkl`, 522 liquid
Mid/Small stocks, 243,180 stock-days, 20-day hold, entry at the **next session's open**, Indian
round-trip costs charged, day-clustered (`z_paired`) where a z is quoted.

Baseline: the validated top-quartile 12M-1M momentum basket — net +1.38%/trade, z 8.94 vs the
liquid universe.

---

## 1. The headline table — absolute momentum bands inside the basket

Bands are **absolute 12-month momentum**, not within-basket ranks. This is the table that
answers the question.

| 12M momentum | trades | net/trade | z vs basket | P(down >10%) | **P(down >20%)** | **10th pct** | net 60d |
|---|---|---|---|---|---|---|---|
| 30–60% | 15,912 | +1.01% | −0.77 | 13% | **2%** | **−11.5%** | +3.53% |
| 60–100% | 14,460 | +0.98% | −0.21 | 19% | 4% | −14.4% | +6.69% |
| 100–200% | 20,765 | +1.78% | 2.41 | 19% | 3% | −13.9% | +4.42% |
| 200–400% | 6,304 | +2.00% | −4.88 | 20% | 5% | −15.5% | +8.89% |
| **400%+** (Cupid: +630%) | 803 | **+3.21%** | 5.95 | 22% | **6%** | **−17.1%** | +7.63% |

Both gradients are real and they point in **opposite directions**:

- Mean return is highest at the extreme. Cutting extended names removes the best-returning ones.
- Probability of a >20% drawdown roughly **triples**, and the 10th-percentile outcome worsens by
  ~5.6 percentage points, from the mild end of the basket to the extreme.

**Which one matters depends on how many names you hold.** Across a 20-name basket the extra
return pays for the fatter tail. In a 1–2 name position there is nothing to average against —
you simply carry a 6% chance of −20% instead of a 2% chance. This user holds few names.

The shipped label (`config.MOMENTUM_TAIL_RISK`) uses the same bands measured over the **whole
liquid Mid/Small universe** rather than the basket alone — same gradient, ~4× the sample, and it
smooths the one non-monotone step above (the basket's 60–100% band reads 4% on 14k rows, the
universe 3% on 29k): **2% / 3% / 3% / 5% / 6%**, 10th pct **−12.0 / −13.2 / −13.5 / −15.5 / −17.1%**.

> The **z vs basket** column is noise at the extremes — note 200–400% is −4.88 while 400%+ is
> +5.95, which is incoherent. The *return* means in thin bands are not trustworthy (see §3).
> The **risk** columns are ordinary frequencies over large samples and are far more robust.

---

## 2. Rank position — is the #1 name special?

Cupid sits at rank #1. It is:

| slice | trades | net/trade | z vs basket | P(down >10%) | P(down >20%) | 10th pct |
|---|---|---|---|---|---|---|
| **rank #1** | 966 | **+2.99%** | 3.31 | 19% | **6%** | −16.4% |
| rank 2–5 | 3,864 | +1.63% | 0.45 | 23% | 5% | −15.9% |
| rank 6–20 | 14,490 | +1.93% | 4.64 | 18% | 4% | −14.2% |
| rank 21+ | 42,074 | +1.13% | −5.33 | 16% | 3% | −12.8% |

Highest expected return **and** the joint-highest blow-up risk. Both true. The scan's
momentum-descending sort is therefore correct as an *ordering* — the weak part of the list is its
tail (rank 21+, z −5.33), which is why display depth dropped 30 → 20.

---

## 3. Stability

**Risk gradient — holds.** P(down >20%) by chronological third:

| band | 2022-08 → | 2023-12 → | 2025-03 → |
|---|---|---|---|
| 30–60% | 1% | 2% | 2% |
| 60–100% | 1% | 8% | 4% |
| 100–200% | 1% | 4% | 3% |
| 200–400% | 0% | 5% | **11%** |
| 400%+ | 0% (n=51) | 8% (n=600) | 0% (n=150) |

Period 1 was a tape where almost nothing fell 20%, so the gradient is flat there by construction.
In both later periods the extended bands carry the fatter tail, and 200–400% is the clearest
(11% in the most recent third). The 400%+ band is too thin per-period to stand alone — the scan
flags it as a thin sample.

**Return means — do not hold.** z vs the rest of the basket by third: 200%+ band 2.19 / −2.02 /
−2.53; 400%+ band 4.92 / −2.57 / 10.03 on n=51/600/150. Unstable and contradictory. Nothing in
this study should be used to claim extended names *earn more*; the claim is only that they do
**not earn less**, so cutting them is unjustified.

---

## 4. Secondary tests (from the first pass — these stand)

Within-basket quintiles of last-month return, % above 200DMA, distance from 52-week high, and
RSI: in every case the *laggard* quintile is the losing bucket (z vs basket −4.25, −0.81, −4.26,
−3.52 respectively) and the extended quintile is fine or better. Distance from the 52-week high
and RSI carry no warning at this horizon. Consistent with the known result that RSI-oversold
underperforms random at 20 days (z −2.98).

At 60 days every last-month-return quintile lands at ~+5.1% — **there is no "it surged so it must
give it back" effect** at this horizon.

**Rally age.** A name stays in the basket a median of 4 sessions (75th pct 15, max 516). Forward
return by how long it has already been in: 0–5 sessions −2.37, ~1 month in +2.66, 1–3 months
+1.55, 3+ months −2.08 (z vs basket). Pooled effect looks real, but by chronological third it is
2.98 / 0.77 / −0.06 — gone in the recent period. **REJECTED as a filter.**

---

## How the first pass missed it

The first version of this study bucketed extension into **quintiles ranked within the basket**.
On any given day the basket's top quintile contains both a +60% name and a +630% name, so the
extreme tail was averaged into a bucket dominated by ordinary momentum names. The gradient only
appears with **absolute bands**.

It also reported only mean return and the 10th percentile, and read "mean is higher" as "the
concern is wrong" — when the concern was about *blow-up risk on a concentrated position*, a
question the mean cannot answer. Two lessons, both already in the house style but worth restating:

1. **Rank buckets hide absolute extremes.** When the question is about an extreme, bucket by the
   absolute quantity.
2. **Match the statistic to the position size.** Mean return answers a basket question. P(large
   loss) answers a single-position question. This user trades single positions.

---

## What shipped

- `config.MOMENTUM_TAIL_RISK` + `config.momentum_tail_risk()` — the measured band table.
- `scan_watchlist_text_long_momentum` prints per name: *"tail risk 6% chance of −20% in 20d,
  worst-decile −17.1%"*, with a thin-sample flag on the 400%+ band.
- Scan header states both gradients.
- `SHARED_RULES` — the agent must answer "has it run too much?" with both halves and the band's
  actual number, never a vague warning and never a dismissal.
- Display depth 30 → 20 (§2).

## What did NOT ship

- **Any over-extension cut.** It would delete the highest-returning names (§1).
- **A rally-age filter.** Dead in the recent period (§4).
- **A PE cut.** Not backtestable here — the panel has no point-in-time fundamentals, so any PE
  rule would be fitted on today's PE applied to history. PE stays information-only via
  `get_fundamentals_text`.
