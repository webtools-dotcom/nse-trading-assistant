# Behavioral rule spec 2 — stock-level cross-sectional proxies

Generated 2026-08-01 from 80 web sources (deep research) + the implementation-constraints doc.
Notebook: `33255a89-e4bf-42aa-9f19-174418390738`.

**Nothing here is validated.** Hypothesis list only. See "Implementability review" at the bottom.

Unlike spec 1, these vary **across stocks on the same day**, so they survive day-clustered
inference — they select stocks within a day rather than selecting days.

---

### **1. Nominal Share Price (Non-Proportional Thinking)**
*   **Behavioral Mechanism:** Investors exhibit "non-proportional thinking," where lower-priced stocks respond more strongly to news in general, leading to more pronounced overreactions and subsequent reversals [1, 2].
*   **Formula:** $Price_{t}$ (Current daily closing price) [3, 4].
*   **Threshold & Direction:** **Lowest quintile** of nominal prices predicts **HIGHER** forward returns when coupled with a reversal signal [5, 6].
*   **Effect Size:** Long-run reversals are strongest among lower-priced stocks; magnitude varies significantly with price but is almost unrelated to market capitalization [5, 7].
*   **Replication & Decay:** Stable across different time periods from the 1920s to 2016; no evidence of decay despite declining tick sizes [8-10].
*   **Transaction Costs:** Low-priced stocks have higher percentage bid-ask spreads [4, 8]. While gross returns are higher, execution at the bid/ask can significantly degrade performance [11].
*   **Confidence:** **High.** The relationship is robust to size controls and consistent across decades [8, 9].
*   **Filter Action:** **INCLUDE** candidates in the lowest price quintiles to amplify the RSI-oversold reversal.

### **2. MAX Effect (Lottery-Like Preference)**
*   **Behavioral Mechanism:** Investors irrationally prefer stocks with "lottery-like" payoffs (extreme positive returns), leading to overvaluation and subsequent underperformance [12-14].
*   **Formula:** $MAX = \max(R_{i,d})$ where $R_{i,d}$ is the daily logarithmic return for days $d = 1 \dots 21$ (trailing trading month) [15-17].
*   **Threshold & Direction:** **High MAX** (top decile/quintile) predicts **LOWER** forward 5–15 day returns [12, 18, 19].
*   **Effect Size:** High-MAX portfolios generate risk-adjusted alphas of -4.8% to -6.0% monthly in emerging markets [20, 21].
*   **Replication & Decay:** Robustly replicated in the US, Europe, South Korea, and India [22-25]. Some evidence suggests the effect has weakened since 2010 in certain developed markets [26].
*   **Transaction Costs:** Effect is most pronounced in small-cap stocks where costs are higher [27]. Raw return spreads often lack significance, suggesting the alpha may be partially consumed by frictions [20, 21].
*   **Confidence:** **High.** Validated specifically in the Indian stock market (2001–2021) [24, 25].
*   **Filter Action:** **EXCLUDE** candidates with a top-decile daily return spike in the last 21 days (prevents buying "exhaustion" spikes).

### **3. Institutional Conviction (Market-Cap Normalized Flow)**
*   **Behavioral Mechanism:** Distinguishes informed institutional "conviction" from noise trading. Large institutional positions relative to firm size indicate informed signals [28, 29].
*   **Formula:** $Intensity = \frac{Net Institutional Buy Value_{i,t}}{Market Capitalization_{i,t}}$ (Lookback: 1 day) [30].
*   **Threshold & Direction:** **Quartile 4 (Highest Intensity)** predicts **HIGHER** forward returns [28, 31].
*   **Effect Size:** Q4 institutional buying generated +12.12% cumulative abnormal returns (CAR) over 50 days in Korea (2020–2024) [28, 31].
*   **Replication & Decay:** Recent study (2025) resolves prior conflicts; shows that normalization by market cap is required to see the signal [28, 32, 33].
*   **Transaction Costs:** Survives costs if focusing on high-conviction (Q4) regimes [34].
*   **Confidence:** **Medium.** Strong evidence in Asian markets, and flow data is backtestable for NSE from April 2023 [35, 36].
*   **Filter Action:** **INCLUDE** candidates where the current day's institutional net buy/market-cap is in the top quartile.

### **4. Capital Gains Overhang (CGO)**
*   **Behavioral Mechanism:** The disposition effect leads investors to sell winners too early and hold losers too long [37, 38].
*   **Formula:** $CGO_{t} = \frac{P_{t-1} - RP_{t}}{P_{t-1}}$, where $RP_{t}$ (Reference Price) is a turnover-weighted average of historical prices over $T=504$ trading days [39, 40].
*   **Threshold & Direction:** **Positive CGO** (price > reference point) predicts **HIGHER** forward returns (momentum continuation); **Negative CGO** predicts lower returns [38, 41].
*   **Effect Size:** Significant moderating effect on returns, even after controlling for 52-week highs and momentum [42, 43].
*   **Replication & Decay:** Pronounced in emerging markets; significant through 2017 [42, 44].
*   **Transaction Costs:** High turnover in CGO-based strategies can be mitigated by efficient trading rules, keeping it profitable after costs [45, 46].
*   **Confidence:** **Medium.** Formula is computationally intensive [47].
*   **Filter Action:** **INCLUDE** candidates with positive CGO (indicates "room to run" as disposition-prone sellers are cleared).

### **5. Nearness to 52-Week High (PTH)**
*   **Behavioral Mechanism:** Anchoring. Investors use the 52WH as a valuation anchor, leading to underreaction when prices approach this barrier [48-50].
*   **Formula:** $PTH = \frac{Price_{t}}{52WeekHigh_{i,t}}$ (Lookback: 252 trading days) [51-53].
*   **Threshold & Direction:** **High PTH** (>0.9 or top decile) predicts **HIGHER** forward returns [54-56].
*   **Effect Size:** Abnormal monthly returns of 0.45% (US) and 2.14% (Australia) [55].
*   **Replication & Decay:** Unconditional alpha is deteriorating out-of-sample [57]. Many studies find it is subsumed by price momentum unconditionally [58, 59].
*   **Transaction Costs:** Profits often become insignificant in most markets once transaction costs are charged [60, 61].
*   **Confidence:** **Low.** Higher risk of decay and cost-sensitivity [57, 60].
*   **Filter Action:** **INCLUDE** candidates in the top decile of PTH (momentum/breakout favorability).

---

### **A. Interaction with Oversold Entries**
*   **Redundancy:** **Short-Term Reversal** (lagged 1-month return) is essentially the same signal as RSI(14) < 30; it provides no additive value [62-64].
*   **Subsumption:** **Nominal Share Price** acts as a powerful amplifier for reversals. Reversals are found to be significantly stronger in lower-priced stocks, making this a critical discriminator for RSI entries [1, 5].
*   **Contradiction:** **MAX Effect** may contradict an oversold signal. If a stock is down -30% over 14 days (RSI < 30) but had a single +15% "dead cat bounce" day within that window, its MAX will be high, predicting further underperformance and potentially invalidating the reversal entry [12, 65, 66].

### **B. Contradicted, Decayed, or Cost-Killed**
*   **52-Week High (PTH):** Frequently reported as "cost-killed" in international markets [60]. In US samples, it has shown negative performance in out-of-sample backtests after the original publication [57, 67].
*   **Industry Reversals:** While significant in gross terms, these often disappear once the bid-ask spread is considered [68, 69].
*   **Momentum (Price):** Corporate bond evidence shows 6-month and 12-month momentum can be entirely an artifact of ex-post winsorization and look-ahead bias [70, 71].

### **C. Emerging-Market and India-Specific Evidence**
*   **India-Specific:** The **MAX Effect** was explicitly validated for the Indian market using data from 2001–2021; it confirms that lottery behavior is a significant driver of cross-sectional returns in the NSE [24, 25].
*   **Emerging Market Variation:** **CGO (Capital Gains Overhang)** is documented to be more pronounced in the emerging market group than in developed markets [42].
*   **Reconciliation:** The **High Volume Return Premium (HVRP)** was previously thought to be reversed in Korea (LVRP), but recent evidence shows that appropriate market-cap normalization reveals the standard global HVRP pattern persists [28, 32].

---

### **Ranked Usefulness for NSE Swing System**
1.  **Nominal Share Price:** Highest confidence; directly amplifies the existing reversal signal [5, 7].
2.  **MAX Effect:** High confidence; prevents "lottery" traps which are common in NSE small-caps [24, 25].
3.  **Institutional Conviction:** Medium confidence; provides an "informed vs. noise" filter [28, 31].
4.  **Capital Gains Overhang (CGO):** Medium confidence; technically complex but robust in emerging markets [42, 47].
5.  **Nearness to 52-Week High (PTH):** Low confidence; high risk of decay and cost-kill [57, 60].

---

## Implementability review (added after reading the spec — not NotebookLM output)

| # | Proxy | Buildable? | Notes |
|---|---|---|---|
| 2 | **MAX effect** | ✅ clean | `max(daily return, trailing 21d)`. India-validated 2001–2021. Best candidate. |
| 1 | **Nominal share price** | ✅ clean | Just `close`. Trivial. |
| 5 | **Nearness to 52w high** | ✅ clean | `close / rolling_max(high, 252)`. Low prior. |
| 4 | **Capital gains overhang** | ⚠️ approximate | Needs turnover-weighted reference price; Grinblatt–Han uses turnover = volume / shares outstanding, and **we do not have shares outstanding**. Volume-weighted is a defensible substitute but is not the published formula — any result carries that caveat. |
| 3 | **Institutional conviction** | ❌ not buildable | Requires **per-stock** institutional net flow ÷ market cap. Ours is market-level aggregate. |

### Rule 3 is the same failure as spec 1, and the spec again claimed compliance

It cites our own constraints doc — "flow data is backtestable for NSE from April 2023" — while
requiring a per-stock breakdown that document explicitly says does not exist. **Second time a
generated spec has asserted it obeyed the constraints while requiring stock-level flows.**
Treat "obeys constraints" claims in these specs as unverified until checked by hand.

### The genuinely useful methodological note

Section A states **short-term reversal (lagged 1-month return) is essentially the same signal as
RSI(14)<30 and adds nothing**. That kills an obvious idea before it costs anything, and it
raises the bar for the others: the question is not "does this predict returns" but "does this
add anything to an oversold signal we already trade".

Section A also flags a real tension worth testing directly: MAX may *contradict* the oversold
entry. A stock down 30% over two weeks with one +15% dead-cat-bounce day inside that window has
a high MAX — the reversal logic says buy, the MAX logic says avoid.

### What to test

Each as an include/exclude filter on the existing RSI<30 mid/small ≥₹25cr entry, 5-year panel,
day-clustered, against the same-day random control:

1. MAX (exclude top decile / quintile) — highest prior, India-validated
2. Nominal price (include bottom quintile) — trivial, high claimed confidence
3. 52w-high nearness (include top decile) — low prior, expected to fail on costs
4. CGO (include positive) — approximate formula, run last

Baseline is the ungated RSI<30 result in the same window. A filter only earns its place if it
beats that, not if it merely looks good alone.

---

## BACKTEST RESULT (2026-08-01) — REJECTED as filters, but see the ranking note

`backtest_stock_proxies.py`. 607 mid/small stocks, 689,363 stock-days, 2021-07-30 → 2026-07-29,
non-overlapping, costs charged, cross-sectional percentiles computed per day across the whole
universe, each gate compared against a baseline **matched to the rows where that proxy is
computable**.

**No filter improves the day-clustered edge over its own baseline.**

| Gate | trades | net/trade | z_paired | vs baseline |
|---|---|---|---|---|
| BASELINE RSI<30 ungated | 3,502 | +0.531% | **3.26** | — |
| MAX: exclude top decile | 3,458 | +0.505% | 3.42 | +0.16 |
| MAX: exclude top quintile | 3,362 | +0.443% | 2.89 | −0.37 |
| MAX: exclude top half | 2,821 | +0.288% | 1.84 | −1.42 |
| Price: include bottom quintile | 652 | +0.953% | 2.59 | −0.69 |
| Price: include top quintile | 793 | −0.043% | 1.16 | −2.12 |
| CGO: include positive | 988 | +1.012% | 3.12 | −0.31 |
| CGO: include bottom quartile | 1,017 | +0.112% | 1.78 | −1.65 |

### The MAX effect does not replicate here — and may be reversed

Excluding high-MAX names is supposed to help. Excluding the top decile moves z_paired by +0.16
while dropping only 44 of 3,502 trades — noise. Excluding more hurts **monotonically**
(−0.37, −1.42), which is the wrong shape for a real effect. The inverse gate — taking *only*
top-decile MAX — produced the highest net return in the entire run (+2.919%/trade, 62 trades,
z_paired 1.75), the opposite of the prediction.

62 trades is far too few to claim a reversed effect. But the monotonic damage from excluding
high-MAX names is not consistent with the published direction, on the market where the paper
said it was validated (India, 2001–2021).

### 52-week-high nearness is null by construction

Top-decile PTH yielded **2 trades**; the absolute PTH>0.90 gate yielded **0**. A stock cannot
be both RSI<30-oversold and sitting at its 52-week high. This was untestable, not tested — the
tension flagged in Section A resolves by the two conditions almost never co-occurring.

### The pattern worth keeping: higher return, lower confidence

Three gates roughly **double net return per trade** — bottom-quintile price +0.953%, positive
CGO +1.012%, top-quartile CGO +1.377%, against a +0.531% baseline — while *lowering* z_paired,
because they cut trade count.

As **filters** that is a clear fail: less total edge, less certainty. But the criterion
"maximise aggregate statistical edge" assumes you take every signal, and with finite capital you
take two or three at a time, where expected value per trade is what matters. That makes these
plausible **ranking** inputs rather than gates — the scan already sorts by net EV, and price
percentile and CGO could join that sort.

**That is a different test and it has not been run.** It would need to ask whether the top-N
candidates ranked with these inputs beat the top-N ranked by current net EV. Nothing here
licenses adding them to the sort yet.

### Directional findings that did hold

- Expensive stocks reverse less: top-quintile-price candidates net −0.043% vs +0.953% for the
  cheapest quintile. Consistent with the non-proportional-thinking literature.
- Negative-CGO names underperform positive-CGO names (+0.112% vs +1.012%), the direction
  Grinblatt–Han predict — using the volume-weighted approximation, not their estimator.

Neither improves the strategy as a gate.