# Long-term re-checks + frog-in-the-pan (2026-09-25)

`python backtest_longterm_recheck.py` · top quartile of liquid Mid/Small by 12M-1M momentum, one
rebalance every 20 sessions (49 per offset, all 20 offsets), entry next open, 20d hold, costs
charged. A-vs-B paired per rebalance date. Pass bar: z_paired ≥ 2 and ≥ 3/5 periods.

| test | A − B per month | z_paired median (range) | periods A>B | verdict |
|---|---|---|---|---|
| R1 low-atr% vs high-atr% half | −0.81% | −1.40 (−2.80..−0.31) | 0/5 | old claim **backwards** — risk dial only |
| R2 top 20 vs rest of quartile | +0.69% | 1.40 (−0.40..2.25) | 4/5 | direction holds, not demonstrated (old z +5.33) |
| F1 smooth vs jumpy (frog-in-the-pan) | −1.03% | −2.20 (−3.45..−1.32) | 0/5 | **REJECTED** — wrong sign |

Tails (offset 0, per trade): low-atr 2.1% vs high-atr 4.2% P(<−20%); top-20 4.9% vs rest 2.3%;
smooth 3.2% vs jumpy 3.1%.

**Frog reversal is not a finding.** Pre-registered was smooth > jumpy. The flip is post-hoc, ID is
barely related to atr% (Spearman 0.09), and inside each vol half it fades to z −1.51 / −0.88. With
49 independent months it would need a fresh out-of-sample window before anyone trades on it.

**R3 tail bands hold** on non-overlapping rebalances — P(<−20% in 20d): 30-60% 1.9%, 60-100% 2.5%,
100-200% 3.2%, 200-400% 3.5%, 400%+ 9.3% (n=43, thin; every-day count 6.1%, n=803).
