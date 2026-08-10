# Can you trade corporate filings? — measured, 2021-2026

`build_news_archive.py` + `backtest_news_events.py`. **369,120 filings, 2021-08 → 2026-08,
745 symbols.** 16,472 classified material events. Entry at the next session's OPEN, exit at
close 1/2/3 days later, costs charged, day-clustered against a random-entry control.

**Verdict: REJECTED. No event type is tradeable long at any horizon, in any market regime.**

## The headline

| Hold | avg gap | net/trade | z_paired | win rate |
|---|---|---|---|---|
| 1 day | +0.35% | **−0.88%** | 0.80 | 30.5% |
| 2 days | +0.35% | **−0.71%** | −0.22 | 37.0% |
| 3 days | +0.35% | **−0.58%** | −0.44 | 40.2% |

Every event type is negative. Win rates 21–42%, all below a coin flip.

## The regime test — this is the decisive one

The first run covered only a falling market, so the obvious objection was "nothing worked then."
Extending the archive to 5 years kills that objection:

| Period | Control | Strategy | Edge | z_paired |
|---|---|---|---|---|
| 2021-08 → 2022-12 (volatile) | −1.14% | −1.03% | +0.11% | −0.29 |
| **2023-01 → 2024-09 (BULL)** | −0.65% | −0.64% | **+0.00%** | **−1.04** |
| 2024-09 → 2026-08 (falling) | −0.87% | −0.59% | +0.28% | 0.69 |

**In the 2023-24 Indian small-cap bull run, news events produced an edge of exactly zero.**
Not small. Zero. The market regime was never the explanation.

## The mechanism was not what I predicted

I expected the reaction to happen in the overnight gap, leaving nothing for a retail entry.
Wrong: **the average gap is +0.35%**. There is barely a reaction at all. Filings are simply not
the price-moving events the idea assumes — most "material" corporate news is already known,
already priced, or genuinely unimportant.

## What naive statistics would have said

`open_offer`, 3-day hold: **naive z = 7.17**. Day-clustered: **z_paired = 0.44**.

The naive figure is high only because the control was also losing. "Loses less than random" is
not bankable unless you can short it. Every apparent winner here dissolves the same way.

## Two things that did survive, neither of them useful for buying

**Acquisitions** hold z_paired ≈ 2.0-2.2 across all three horizons — the most consistent signal
in the table. But net return stays **negative** (−0.84% / −0.68% / −0.50%). They lose less than
random, consistently. That is a relative result you cannot bank.

**Fund raising is reliably bad**: z_paired −2.13 / −2.64 / **−3.19**, worsening with holding
period, net −1.00% to −1.07%. This is the only genuinely significant, sign-stable finding in
the whole study — QIPs, preferential issues and rights issues dilute, and the market knows it.
Actionable only as a *don't buy* filter, or as a short you are not set up to take.

## A design caveat, stated plainly

Entering at the open and exiting at the close systematically captures intraday drift and misses
overnight drift, which is why *every* absolute number here - strategy and control alike - is
negative. That biases the levels, not the comparison: both sides are measured identically, so
the **edge** column and `z_paired` are the valid read. They say zero.

## What this changes

- The README's "news/announcement signals cannot be backtested at all (no historical news
  archive)" is **no longer true**. There is now a 369k-filing archive and a working harness.
  Future news ideas get measured in minutes.
- `get_significant_announcements_scan` and `get_catalyst_scan_text` are labelled UNVALIDATED.
  They can now be tested properly rather than carrying a permanent asterisk.
- The phone watcher stays an **awareness** tool. Its messages already say announcement signals
  are not backtested and are "a prompt to look, not a signal to trade." That wording is now
  measured rather than cautious boilerplate.

## The idea that was tested

"Buy on today's news, hold one to three days, capture the opportunity." Measured across every
material filing NSE published for a 748-stock universe over five years and three market
regimes, with retail-realistic entry timing: **it loses money.** Not unproven — measured.
