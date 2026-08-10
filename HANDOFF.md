# Handoff — where this project stands (2026-08-10)

Read this with `README.md` (what the strategies are) and `CLAUDE.md` (how to work on the code).
This file is the part that isn't in either: **what actually happened, what was decided, and why.**

---

## Who you're working with

Nishant. Builds by conversation, describes himself as a vibe coder — he does not want to read
diffs, he wants to understand what changed and why it matters. He is also genuinely rigorous:
he asks for ideas to be tested rather than assumed, and has repeatedly accepted "your idea
failed" as a good outcome. Several of his own proposals were measured and rejected in this repo.

**He values being told the truth quickly over being made comfortable.** If something doesn't
work, lead with that. If a number is weak, say the number.

He trades a small real account (~₹4,000–5,000 at the moment) and currently holds two positions.

---

## The single most important thing to know

**This project has been wrong three times about results that looked strong**, and each correction
was found by better statistics, not new data:

| Correction | Effect |
|---|---|
| Overlapping trades (2026-07) | z-scores deflated ~1.7x |
| Day-clustering (2026-08) | Small-cap 7.03 → **2.74**; Mid-cap and Downtrend stopped being demonstrable |
| Naive vs paired inference | News events showed naive z=7.17, paired z=0.44 |

That history is *why* the tone here is so cautious. It is not pessimism — it is calibration
that was paid for. When a new idea looks obviously right, that is the historical warning sign.

---

## Current state of the strategies

**Short-term (RSI<30, Mid/Small, ≥₹25cr, 6-day hold)** — the live strategy.
- Small-cap holds (z_paired 2.74). Mid-cap **no longer demonstrated** (1.73). Downtrend tier
  **gone** (0.71). Flat/Mild is the most reliable tier (4.41), Uptrend highest-return but noisier (2.05).
- **The last 12 months are negative across every configuration tested.** This is real and the
  5-year average hides it.
- Survived intact: oversold-depth ordering, the ≥₹25cr liquidity filter, vol-regime sizing.

**Long-term (~1 month momentum)** — user explicitly deprioritised it ("I don't have that
patience"). Its numbers are still the ORIGINAL overlap-inflated ones and have never been
re-validated. Do not quote them as if they were checked. He holds one long-term position anyway.

---

## What was built in the last session (2026-08-01 → 08-10)

**Research that came back negative — all of it documented, none adopted:**
Two NotebookLM research passes (behavioural finance), participant flow gates, MAX effect,
nominal price, CGO, 52-week-high, candidate-count gating, and event-driven news trading.
~40 configurations tested. See the REJECTED table in `README.md`.

**What actually shipped:**
- `day_clustered_edge` in `backtest_engine.py` + all headline tables re-measured
- Participant category flows (FPI/DII/retail, 815 days) — `cache_manager.py`
- **369,120-filing news archive** (2021-2026) — killed the "news can't be backtested" limitation
- **Dilution filter** — the one validated finding from the news work; QIP/rights/preferential
  announcements underperform by −0.29%/trade over 6 days, z_paired −3.34. Now a scan check.
- **Setup checklist** — 8 PASS/WEAK/FAIL checks + verdict per candidate
- **Discipline layer** — reads his own trade log; blocks adding to open positions, warns on
  revenge re-entry, concentration, loss streaks, risk creep
- **`evaluate_user_trade`** — analyse any ticker he names at his own entry price
- **Phone stack**: `notify.py`, `telegram_bot.py`, `alert_watcher.py`, `news_watcher.py`
  (Termux, LLM-triaged filings, urgent pushes vs evening digest)
- Deleted 7 legacy backtest scripts that had no cost-charging and would reproduce the old
  inflated numbers, plus a broken `evaluate_model.py`

---

## Decisions he made that you should not silently reverse

1. **Position sizing is opt-in.** An old prompt line told the agent to assume ₹10,000 capital
   and size every recommendation. That made it invent his capital, get a zero share count, and
   then downgrade a *good* setup because of it. Removed. Analysis is now a complete answer with
   no share count. He manages his own stops, targets and sizing.
2. **Setup quality and sizing are separate questions.** Never let a sizing outcome change a
   verdict about a stock.
3. **Long-term strategy is out of scope** unless he raises it.
4. **The phone is an awareness tool, not a signal tool.** News was measured and does not predict
   returns. Don't rebuild it into a buy-signal generator.
5. **He knows the cost problem.** At ₹4,000, fixed charges (DP ~₹16 flat + brokerage) run 6–20×
   the measured edge. He has been told, he understood, he's trading small anyway. Don't relitigate
   it every time — mention it when it's decision-relevant, not as a reflex.

---

## Live positions (as of 2026-08-10)

| Ticker | Term | Entry | Date | Shares | Stop | Target |
|---|---|---|---|---|---|---|
| CUPID.NS | long | ₹244.73 | 2026-08-05 | 7 | ₹231.94 | ₹292.45 |
| CEMPRO.NS | short | ₹1206.30 | 2026-08-10 | 1 | ₹1127.15 | ₹1405.65 |

Both open, both in profit. The old trade log was fake test data and has been wiped — these two
are his first real logged trades, so the journal is effectively at n=2. Every "past trades"
answer should carry that caveat.

**Note on CEMPRO:** the tool's checklist FAILED it on market conditions (only 1 candidate that
day) and he took it anyway. It worked. That's a good outcome from a decision the process advised
against — n=1, and worth remembering if he starts generalising from it.

---

## Known open items

- `JBCHEPHARM.NS` — stale in cache since 2026-07-23 (1 of 748). Watch it.
- ~~`agent.py` 3-turn history trim~~ — **fixed 2026-08-10**. `MAX_HISTORY_TURNS = 12`; the old
  value was sized for Qwen's 8000 TPM limit on a provider no longer in use.
- ~~Uncommitted work~~ — **committed and pushed 2026-08-10** to branch
  `behavioral-research-day-clustering`. Not merged to `main`; open a PR when ready.
- `list_builder.py` is unreferenced and probably redundant with `build_universe.py`; left alone
  because it may be the only path to rebuilding the universe.

---

## How he works day to day

`WORKFLOW.md` is the document he actually opens. Two commands on the PC
(`refresh_cache.py`, then `main.py`), one prompt — *"any exits? then scan."* The phone watcher
runs on a spare Android and interrupts him only when a filing is material.

The tool's most valuable output is usually **"no trade today"** — 89% of days are in candidate
bands that historically lose money. That is the system working, not failing.
