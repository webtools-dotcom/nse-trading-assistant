# Behavioral rule spec — NotebookLM research output

Generated 2026-08-01 from 49 web sources (deep research) + the implementation-constraints doc.
Notebook: `13ec2cef-10d0-4bf6-ba63-ece48057d227`.

**Nothing here is validated. This is a hypothesis list.** Per project discipline, no rule below
goes into `tools.py` until it survives `backtest_engine.py` against a random-entry control.
See the "Implementability review" at the bottom — two of the four rules cannot be built with
the data we have, despite the spec claiming otherwise.

---

This Developer Rule Specification for a National Stock Exchange (NSE) swing-trading system is synthesized from the provided sources, adhering strictly to the permitted inputs: daily OHLCV, Nifty 50, India VIX, and daily participant-category net cash flows (FPI, Mutual Fund, etc.) [1-3].

### **Psychological Regime Rule Specifications**

#### **1. Informed FII Innovation (Foreign Institutional Information)**
*   **Trigger:** **Top Quintile of FII Flow Innovations.** Innovations are computed as the residuals ($e_{it}$) from a panel regression predicting daily stock-level FII net flow ($FII\_Net_{it}$) using 5-day lagged flows, market returns, and volatility [4-6]. For practical swing implementation:
    *   **Lookback:** 5 trading days [4, 7].
    *   **Formula:** $Residual = Actual\_FII\_Net - Predicted\_FII\_Net$.
    *   **Threshold:**Residual must be in the top 20% of the NSE universe for the observation period [8, 9].
*   **Multiplier & Direction:** **1.0x (Long).** The effect on forward returns is **Positive** and permanent, reflecting informed trading [10-12].
*   **Source:** *Foreign Fund Flows and Stock Returns: Evidence from India*; Indian NSE market; 2006–2011; reported effect size is a coincident abnormal return of ~0.88–0.90% [13, 14].
*   **Replication Status:** Replicated via out-of-sample validation (2012–2013) [15].
*   **Confidence:** **High.** The study uses proprietary NSE-specific FII trade data and findings are consistent across multiple Indian market phases [16, 17].

#### **2. VIX-Gated FII Liquidity Reversal**
*   **Trigger:** **India VIX > Median AND Bottom Quintile FII Innovations.** This identifies transient price declines driven by FII "fire sales" during periods of global stress [18-20].
    *   **Lookback:** Current day VIX vs. 252-day median; 5-day cumulative FII flow innovation [7, 21].
    *   **Threshold:** India VIX > its median level; FII Innovation residual in the bottom 20% [8, 22].
*   **Multiplier & Direction:** **1.5x (Long).** Forward 1-week returns are **Positive** as transient price declines reverse [11, 12, 23].
*   **Source:** *Foreign Fund Flows and Stock Returns - International Growth Centre (IGC)*; Indian market; 2006–2011; reported effect size is a 0.36%–0.42% reversal within five days [13, 24].
*   **Replication Status:** Replicated out-of-sample (2012–2013) [15].
*   **Confidence:** **High.** The asymmetric response to FII outflows during high-volatility regimes is a well-documented microstructure phenomenon [20, 25, 26].

#### **3. Retail Attention Momentum (Weekly Lead)**
*   **Trigger:** **Top Quintile Weekly Retail Net Cash Flow.** Heavily bought stocks by retail investors predict near-term positive returns at a weekly horizon [27, 28].
    *   **Lookback:** 5 trading days (Wednesday to Wednesday per source) [29, 30].
    *   **Formula:** $\text{Retail Proportion of Buys (PB)} = \frac{\text{Retail Net Flow}}{\text{Total Cash Volume}}$ [21, 31].
    *   **Threshold:** PB must be in the top quintile of the panel [29].
*   **Multiplier & Direction:** **0.75x (Long).** Forward returns are **Positive** for the subsequent two weeks [28, 32].
*   **Source:** *Do Retail Trades Move Markets?*; US Market (brokerage data); 1983–2000; reported effect size is a 1.37% monthly return spread between top and bottom quintiles [29, 33].
*   **Replication Status:** **Failed Replication/Decayed.** Recent analysis (2016–2021) shows this effect has disappeared for large-cap stocks [34, 35].
*   **Confidence:** **Low.** While historically strong in US data, the source admits retail attention does not generate superior long-term returns and recent replications show significant attenuation [36-38].

#### **4. DII Absorption (Structural Support)**
*   **Trigger:** **Positive DII Net Cash Flow (₹cr).** Domestic Institutional Investors (DIIs) have emerged as the primary drivers of Indian market levels, effectively absorbing FPI selling [39, 40].
    *   **Lookback:** 5-day rolling average of DII Net Flows [41].
    *   **Threshold:** Net DII Flow > ₹0 [40].
    *   **Formula:** $\text{DII Net} = \text{Mutual Fund Net} + \text{Insurance Net} + \text{Bank Net} + \text{AIF Net} + \text{PMS Net}$ [2].
*   **Multiplier & Direction:** **1.0x (Long).** The correlation with benchmark performance is **Strongly Positive** [40].
*   **Source:** *Structural Decoupling of the Indian Equity Market*; Indian Market; 2021–2026 [41, 42]. Reported effect size: Beta = 0.091 (Nifty 50 increases ~0.091 points for every ₹1 crore of net DII investment) [43].
*   **Replication Status:** Unreplicated (contemporary 2026 study) [44, 45].
*   **Confidence:** **Medium.** While correlations are high (r = 0.685), Granger causality tests suggest DIIs are market-responsive (momentum-chasing) rather than market-driving [46, 47].

---

### **A. Contradicted or Decayed**
*   **Retail Market Timing:** Aggregate retail order imbalances (ARA) were found to fail at predicting future market-wide returns across multiple studies [48-52]. This implies that while retail flow might signal cross-sectional stock picks, it cannot be used to time Nifty index entries.
*   **Large-Cap Retail Predictability:** The ability of retail order imbalance to predict large-cap stock returns has largely vanished in the post-2016 era [34, 37, 38]. System design should restrict retail-based rules to small-cap or mid-cap segments where the effect remains statistically significant, albeit weakened [53, 54].
*   **FII Dominance Narrative:** Earlier literature emphasizing FIIs as the sole "market movers" is contradicted by 2021–2026 Indian data, which shows FII flows have shifted to a weak and statistically insignificant correlation with NSE benchmark indices [40, 55]. Relying solely on FII selling as a "crash" signal may result in false negatives.

### **B. Out of Scope**
*   **Internalized Retail Order Imbalance ($Mroib$):** This robust predictor requires sub-penny execution data (TAQ flag ‘D’) and quote midpoint analysis to identify internalized wholesale trades [56-58]. It cannot be computed from daily OHLCV.
*   **High-Frequency Order Book Imbalance (OBI):** Causal signals extracted from the Limit Order Book (LOB) require tick-by-tick order lifetime, modification counts, and modification-time filters [59-61].
*   **Delivery Percentage Conviction:** Though identified as a key retail-conviction proxy for the Indian market, it is categorized as "Tier B" with insufficient backtestable history in the implementation constraints [62, 63].
*   **Social Media/Sentiment Analysis:** While sources discuss the "sum of all FEARS" and retail attention via search/sentiment, these are explicitly excluded by implementation constraints [3, 48, 64, 65].
*   **Margin Call Liquidations:** Sources discuss forced retail liquidations and margin call hits (e.g., in the Korean market), but since margin debt data for the NSE is unavailable, this regime cannot be quantified [3, 66-68].

---

## Implementability review (added after reading the spec — not NotebookLM output)

### Rules 1 and 2 are NOT implementable as written

Both require **stock-level** FII flows: rule 1 regresses "daily stock-level FII net flow
$FII\_Net_{it}$" and thresholds on "top 20% of the NSE universe"; rule 2 does the same on the
bottom quintile. Our `category_flows.pkl` is **market-level aggregate** — one net figure per
category per day for the entire market, with no per-stock breakdown. The NYU Stern study used
proprietary NSE stock-level FII trade data that is not publicly published.

The spec asserts these obey the constraints. They do not. This is the failure mode the
constraint block was written to prevent, and it still got through — worth remembering for
future research passes.

Degraded market-level versions are possible (FII flow innovation as a *market regime gate*
rather than cross-sectional stock selection), but that is a different rule and the cited effect
sizes (0.88% abnormal return, 0.36–0.42% five-day reversal) do not transfer to it.

### Rule 3 is low-value

Failed replication post-2016, US brokerage data 1983–2000, and the spec itself rates it Low.
It also prescribes restricting to small/mid-cap — which we cannot do, since aggregate flows
have no cap-tier breakdown. Our scan is already mid/small-only, so a market-level gate would
combine with that filter by accident rather than by design.

### Rule 4 is computable but weak

`DII_net = MUTUAL_FUNDS + INSURANCE + BANK + AIF + PMS` is directly computable from our cache.
Two problems: (a) the spec's own Granger result says DIIs are **momentum-chasing, not
market-driving**, which is close to fatal for predictive use; (b) the source period 2021–2026
overlaps our flow history 2023–2026, so backtesting it here is near in-sample and is not
independent confirmation.

### The most important finding is a negative one

Section A states that aggregate retail order imbalance **fails to predict market-wide returns**
across multiple studies. That speaks directly to the −0.48 retail/FPI correlation and 65.5%
opposite-sign days we measured: the relationship is real and structural, but the literature
says it likely carries no index-timing value. Useful expectation-setting before spending
compute on it.

### Recommended next step

Test the market-level flow variables as a **regime gate on the existing RSI<30 mid/small
strategy**, not as a standalone signal — the same shape as the validated volatility-regime
rule. Concretely: does conditioning entries on FPI net flow percentile, retail net flow
percentile, or retail/FPI divergence improve net-per-trade over the ungated baseline?
That is cheap (data is local, `backtest_engine.py` exists) and directly answerable.

Expect it to fail. Section A says so, the window is 3.3 years and one regime, and the base
strategy has itself been flat for 12 months. Worth running precisely because it is cheap and
the answer is currently unknown.

---

## BACKTEST RESULT (2026-08-01) — REJECTED, no flow gate is adopted

`backtest_flow_gate.py`. 607 mid/small-cap stocks, turnover ≥ ₹25cr, 2023-04-05 → 2026-07-29,
non-overlapping trades, costs charged, flows lagged one day, percentiles computed point-in-time
on a trailing 252-day window. Baseline and all gates measured inside the same window.

**No gate improves on the ungated baseline.**

| Gate | trades | days | net/trade | z (naive) | **z_paired** |
|---|---|---|---|---|---|
| **BASELINE RSI<30, no gate** | 2,577 | 507 | +0.459% | 6.07 | **2.32** |
| FPI buying hard (pctl>0.75) | 57 | 21 | +3.187% | 4.66 | 2.38 |
| Divergence low (pctl<0.25) | 59 | 21 | +3.513% | 5.27 | 2.37 |
| DII 5d buying (pctl>0.75) | 1,505 | 160 | +0.735% | 6.42 | 2.31 |
| Retail selling (pctl<0.25) | 1,125 | 112 | +1.333% | 8.60 | 2.15 |
| DII absorbing (net>0) | 2,473 | 433 | +0.503% | 6.30 | 2.09 |
| Divergence high (pctl>0.75) | 311 | 43 | +1.199% | 5.03 | −1.39 |

The two gates that nominally edge the baseline (2.38, 2.37 vs 2.32) fire on **21 days each out
of 507**, are 2 of 16 configurations tried, and are largely the *same 21 days* — "FPI buying
hard" and "retail-minus-FPI divergence low" are near-identical conditions. That is one noisy
observation, not two findings.

This matches the literature. Section A of the spec above states that aggregate retail order
imbalance fails to predict market-wide returns across multiple studies; that is exactly what
happened here.

### The methodological finding is the valuable one

**Naive trade-level z-scores are badly wrong for a market-level gate**, and would have sold
this hard. "Retail selling" shows z=8.60 naive versus z_paired=2.15 — *below* the baseline it
was supposed to improve. The reason: a market-level gate selects **days**, so all its trades
share a handful of dates and one common market factor. 1,125 trades spread over 112 days carry
roughly 112 observations' worth of information, not 1,125.

This is the cross-sectional twin of the overlapping-trade error the project already corrected
once (README, sample uniqueness). It was corrected within each stock; it was never corrected
*across* stocks. **Any future whole-market signal must be tested day-clustered.** The
`z_paired` column — each gate day against the same day's random control — is the right default.

Worth noting the baseline itself only reaches z_paired=2.32 over this window. Under
day-clustered inference the core strategy is far weaker than the headline 5-year z=7.03
suggests, which is consistent with the README's "edge lost" finding for the recent period.