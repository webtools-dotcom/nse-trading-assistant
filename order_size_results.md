# Does order SIZE change the answer? — measured, REJECTED (2026-09-03)

`backtest_order_size.py`. **352 order wins that state a rupee figure**, 2021-08 → 2026-08,
market cap rolled back to the event date. Same machinery as everything else: next-open entry,
costs charged, day-clustered against a random same-day control.

## Why this test existed

`order_win_results.md` rejected order wins outright. The one surviving version of the idea was
that lumping a ₹602cr order for a ₹3,000cr company together with 0.2% of market cap is what
buried the signal — and it is the assumption already baked into the news tool's 5%-of-market-cap
escalation rule.

## Verdict: REJECTED, and backwards. The biggest orders are the worst.

Net %/trade by order value as a share of market cap:

| Bucket | n | gap | hold 1 | hold 2 | hold 3 | **hold 5** | win (5d) |
|---|---|---|---|---|---|---|---|
| < 1% of mcap | 106 | +0.47% | −0.64% | −0.03% | +0.02% | **+0.71%** | 46.2% |
| 1 – 5% | 117 | +1.21% | −1.49% | −1.55% | −1.12% | −0.71% | 39.3% |
| 5 – 15% | 75 | +1.95% | −0.90% | −0.98% | −0.77% | −0.96% | 28.4% |
| **> 15%** | 54 | +2.19% | −1.37% | −1.68% | −2.29% | **−3.11%** | 27.8% |

`z_paired` for the > 15% bucket at hold 5: **−2.92**.

## The mechanism is visible, and it is overreaction — not drift

Look at the gap column. It scales cleanly with size: **+0.47% → +1.21% → +1.95% → +2.19%**. The
market absolutely does react in proportion to how big the order is for the company. That part of
the hypothesis was right.

But the reaction is entirely spent in the gap, before you can buy — and then it **reverses**, and
the reversal is also proportional to size. A transformative order gives back 3.1% over the next
five sessions. This is the opposite of post-earnings drift: it is overreaction followed by mean
reversion.

The only bucket that does not lose is the one where the order barely matters (< 1% of market
cap), and its `z_paired` of 0.47–1.51 is not significant.

## Consequence for the news tool

The 5%-of-market-cap escalation rule in `news_watcher.py` — which promotes a big order from the
evening digest to an immediate push — is **promoting the worst bucket**. It should be reframed
from "this is important, act" to "this is a large reaction that has historically reverted."

## Limitations, which are real

- **Selection.** Only 16% of order filings state a number in the stub. The rest are in PDF
  attachments the archive never stored, and it keeps no attachment URL, so they cannot be
  re-fetched without re-downloading five years of announcements. Filings that put the figure in
  the one-line summary are plausibly the bigger, more newsworthy ones.
- **Market cap is rolled back by price alone** (`mcap_now × close_then / close_now`), which
  assumes a roughly constant share count. Wrong for anyone who did a large QIP or a split.
- **Small buckets.** 54–117 trades each, and 20 comparisons were made. The `> 15%` result is
  consistent in sign across all four holding periods, which is the main reason to take it
  seriously at all.

Taken with `order_win_results.md`, that is three separate tests of the news-to-trade idea —
event type, category, and now size — and all three came back negative.
