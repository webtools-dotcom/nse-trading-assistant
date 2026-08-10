# Daily workflow

Two machines, two jobs.

- **PC — the brain.** Scans, analysis, sizing, journal, discipline gates. Where you *decide*.
- **Phone — the ear.** Watches all 748 stocks for material filings, 08:00–23:30. Where you *get told*.
- **Telegram** is the wire between them.

---

## Once ever (already done)

- [x] `.env` has `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_ID`
- [x] Phone: `~/ta/` with 4 files, `--prime` run, watcher running under `nohup python -u`
- [x] Termux battery set to Unrestricted, Termux:Boot script in place

Phone health check, any time:

```bash
tail -20 ~/ta/watcher.log
```

If the last line is older than ~20 minutes during 08:00–23:30 on a weekday, Android killed it.
Restart with `cd ~/ta && nohup python -u news_watcher.py > watcher.log 2>&1 &`.
**A dead watcher looks exactly like a quiet news day.** Check it weekly.

---

## Every morning — 5 minutes, PC

```bash
python refresh_cache.py
```

```bash
python main.py
```

Then one prompt:

> any exits? then scan.

That is the whole daily routine. Everything below is how to *read* what comes back.

---

## Reading the scan — in this order

### 1. The MARKET CONDITIONS line, before anything else

```
MARKET CONDITIONS: 5 candidate(s) passed the filter today - thin - historically the worst band.
  Historical mean -0.77%/trade on days with this many candidates
```

| candidates | historical mean | what it means |
|---|---|---|
| 1–2 | −0.37% | very thin |
| 3–5 | −0.77% | **worst band** |
| 6–10 | −0.18% | ~break-even |
| 11–20 | +0.89% | broad selloff — worth attention |
| 21+ | +2.34% | market-wide capitulation |

**Under 11 → the default is no trade.** 89% of days are here. Roughly half of the effect above
11 is market beta rather than signal quality, so treat it as *conditions*, not a green light.

### 2. Then the candidates themselves

```
BBOX.NS [Small, Uptrend, 47.3% 1yr]: Price ₹726.8, RSI 23.1, Stop ₹649.76, Target ₹803.84
    liquidity 51.6cr/day | round-trip cost 0.5% | NET expected value +1.01%/trade | P(win) 58%
```

Read in this order, and stop at the first fail:

1. **⚠️ flags** — "Downtrend tier + Mid-cap: not distinguishable from random entry once
   day-clustered". Those strata no longer clear the control. Not disproven, but not demonstrated.
2. **P(win)** — below 50% is a *blocked* trade with negative measured EV, not a weak one.
3. **NET expected value** — must be positive. Quote this, never the gross figure.
4. **RSI depth** — <24 earned +1.17%/trade, 30–35 earned +0.10%. Deeper is better, monotonically.
5. **Cap tier** — Small holds (z 2.74). Mid is no longer demonstrated (z 1.73).
6. **Trend tier** — Flat/Mild is most reliable (z 4.41), Uptrend highest-return but noisier
   (z 2.05), Downtrend is gone (z 0.71).

### 3. Only if something survives all six

> full analysis on TICKER

Regime, fundamentals, institutional activity, results calendar, announcements. You are looking
for something that **contradicts** the technical setup — upcoming results, a rating action, a
management exit. One contradiction is enough to skip it.

> similar past trades to this setup

> size 1% risk on TICKER with ₹X capital

Sizing runs the discipline gates. If it blocks, read the reason out loud before overriding it.

---

## Reading a phone alert

Three questions, in order:

1. **Do I hold this stock?** → go to the PC: *"TICKER announced X — where is it against my stop?"*
   The exit rule is validated; the news is not. News says *look*, the stop says *do*.
2. **Is it in today's scan?** → it is context for a decision you were already considering.
3. **Neither?** → read it and do nothing. That is ~17 of the ~18 alerts a day, and doing
   nothing with them is correct.

Never trade *because* an alert arrived. Announcement signals cannot be backtested — there is no
historical news archive — so nothing in that feed carries a measured edge.

---

## Prompts that actually work

| Situation | Prompt |
|---|---|
| Daily | `any exits? then scan.` |
| A candidate survived the checklist | `full analysis on TICKER` |
| Someone gave you a tip | `thoughts on TICKER at ₹X?` |
| You already bought something | `I bought N shares of TICKER at ₹X, what now?` |
| Sizing | `size 1% risk on TICKER with ₹X capital` |
| After entering | `record entry for TICKER at ₹X` |
| After exiting | `record exit for TICKER at ₹X` |
| Monthly | `how is the strategy performing against expectation?` |

Keep-it-honest prompts, worth using often:

- `quote the NET figure after costs, not gross`
- `what would make this trade a mistake?`
- `is that number from a tool result or are you inferring it?`

---

## When you actually trade

All of these must be true. Any one missing → skip.

- [ ] Candidate count 11+
- [ ] No ⚠️ unvalidated-stratum flag
- [ ] P(win) comfortably above 50%
- [ ] NET expected value positive
- [ ] RSI below 26 ideally, below 30 minimum
- [ ] Liquidity well above ₹25cr/day
- [ ] Full analysis found nothing contradicting it
- [ ] Position large enough that fixed costs stay under ~20% of expected gain
- [ ] Sizing produced a real share count and the discipline layer stayed quiet

Then: enter → `record entry` immediately → let the exit rule run. Do not improvise the exit.

---

## Weekly / monthly

- **Weekly:** check `watcher.log` is alive. Reconcile the journal against your broker.
- **Monthly:** `how is the strategy performing against expectation?` — this compares your real
  closed trades to the backtest and runs the CUSUM decay alarm.

---

## Reality check — read this before your first trade

**At ₹4,000 capital, this strategy cannot clear its own costs.** Fixed charges (DP ~₹16 per
sell, plus per-order brokerage) don't scale down with position size:

| position | min cost | with a ₹20/order broker |
|---|---|---|
| ₹500 | 3.40% | 11.39% |
| ₹2,000 | 1.01% | 3.01% |
| ₹7,000 | ~0.5% | ~1.1% |

The measured edge is **+0.53%/trade**. At ₹4,000 with 2% risk your position is ~₹500–600, where
costs are 6–20× the edge. Roughly **₹50,000** is where positions reach ~₹7,000 and fixed costs
fall under a fifth of expected gain.

The backtest charged percentage costs only — it never modelled the flat DP fee, because at
normal size it is negligible. At small size it dominates. So the real picture is worse than the
tool's own net-EV figure shows.

**Also true right now:** the strategy has been flat for 12 months, and the journal has one
closed trade.

**So the highest-value thing you can do today costs nothing:** run the morning routine, and log
the trades you *would* have taken as paper trades. In six months the journal answers the only
question that finally matters — whether the edge survives your execution. Everything else here
is preparation for that.

---

*Not financial advice. Not SEBI-registered. The trading decision is always yours.*
