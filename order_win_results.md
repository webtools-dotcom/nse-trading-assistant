# Do order wins drift? — measured, REJECTED (2026-09-03)

`backtest_order_wins.py`. **2,265 order-win events, 2021-08 → 2026-08, 303 symbols.** Entry at
the next session's OPEN, costs charged, day-clustered against a random same-day control.

## Why this test existed

`backtest_news_events.py` measured eight event types and returned `z_paired` 0.80 / −0.22 /
−0.44. That verdict is quoted in every alert the news tool sends — but **there is no order-win
category in its `EVENT_TYPES` list.** "Company bags order" is by far the most common alert the
tool now produces, and it had never been measured.

## Verdict: REJECTED. No positive edge in any regime, at any horizon, in any size bucket.

| Hold | gap | net/trade | z | **z_paired** | win rate |
|---|---|---|---|---|---|
| 1 day | +0.93% | **−0.98%** | −0.14 | **−1.78** | 28.5% |
| 2 days | +0.93% | **−1.00%** | −0.73 | **−0.52** | 32.8% |
| 3 days | +0.93% | **−0.97%** | −1.42 | **−0.86** | 35.6% |
| 5 days | +0.93% | **−0.94%** | −2.39 | 0.04 | 38.0% |

You lose roughly two times out of three. The **+0.93% gap** is the reaction — and it happens
before you can buy. After that the average trade gives back more than the gap was worth.

## The size hypothesis was wrong, and backwards

"Small companies react harder to news than big ones" was the reason the universe was widened to
2,299 names. Tested directly (hold 1 / 2 / 3 / 5, `z_paired`):

| Cap | n | net/trade (hold 2) | z_paired across holds |
|---|---|---|---|
| **Small** | 1,624 | **−1.11%** | −2.36, −0.95, −1.27, −0.85 |
| Mid | 267 | −0.88% | 0.58, −0.60, −1.35, −0.94 |
| Large | 371 | −0.58% | 1.62, **2.27**, **2.32**, 1.84 |

Small caps are the **worst** bucket, not the best.

Large caps look positive on `z_paired` — and this is the trap the project has already documented
once. **Their net return is still negative** (−0.66% / −0.58% / −0.49% / −0.33%). They only beat
the control because the control lost more. Outperforming a losing benchmark is not making money.

## It is not a market-regime artefact

NSE only created the `Bagging/Receiving of orders/contracts` category in late 2024, so
classifying on category alone confines the test to a single falling market. Recovering earlier
events from the stub text adds 1,071 more, reaching back to 2021:

| Period | control | strategy | edge | z_paired |
|---|---|---|---|---|
| 2021-08 → 2022-12 (volatile) | −1.14% | −1.07% | +0.07% | 1.14 |
| **2023-01 → 2024-09 (BULL)** | −0.63% | −0.78% | **−0.15%** | −1.29 |
| 2024-09 → 2026-08 (falling) | −0.82% | −1.05% | −0.23% | −2.13 |

**No positive edge in the bull run either.** Same objection, same answer as the original news
test.

## What this changes

1. The news tool's order-win alerts — its most common output — carry **no measured edge at
   next-open entry over 1–5 days**. The alert footer should cite this number, not only the
   general filings one.
2. Widening the universe to 2,299 names was still right, but **not for the stated reason**. It
   makes the tool see more; it does not make small-cap order news more tradeable.
3. The intraday tracker premise is **not** directly refuted — this measures next-open entry over
   days, not a same-session move. But the burden of proof has moved, and the honest reading is
   that the tracker's `FADED` side (most news gives the gap back) is the part supported here.

## What was NOT tested

**Order size relative to market cap.** Only 12% of order stubs carry a rupee figure — the
amounts sit in PDF attachments the archive never stored. The hypothesis that a ₹602cr order for
a ₹3,000cr company differs from 0.2% of market cap remains untested, and is the one remaining
version of this idea with a plausible mechanism. Testing it means re-fetching ~2,265 attachments
with `fetch_attachment_text()` from the news repo and re-running this script with size buckets.

16 comparisons were made (4 holds × 4 cuts). Treat the best of them as the maximum of 16 noisy
draws.
