# NSE Trading Assistant — instructions for AI agents

Read `README.md` for strategy detail and `HANDOFF.md` for where the project currently stands.
This file is about *how to work on the code* without breaking it or reintroducing errors that
have already been paid for.

---

## The one thing to understand about this project

**Every claim here is measured, and several confident-sounding claims have already been proven
wrong by the project's own data.** Three separate times a result that looked strong collapsed
under better statistics:

1. **Overlapping trades** (2026-07) — RSI stays <30 for days, so one episode was counted as ~3.4
   near-identical trades. Deflated every z-score by ~1.7x.
2. **Day-clustering** (2026-08) — trades on the *same day across different stocks* share one
   market factor. Small-cap z went 12.06 → 7.03 → **2.74**. Mid-cap and the Downtrend tier stopped
   being demonstrable entirely.
3. **Naive vs paired inference** — `open_offer` news events showed naive z=7.17 and paired z=0.44.
   The naive number was high only because the *control* was also losing.

So: **never present a number without saying how it was measured.** If you find yourself about to
say "this clearly works", that is the exact moment the project has historically been wrong.

---

## Non-negotiable discipline

- **Backtest before adopting.** Every signal/filter idea gets tested against a random-entry
  control using `backtest_engine.py` before it touches a live tool. No exceptions, no
  "obviously right" rules. See the REJECTED table in `README.md` — most obvious ideas failed.
- **Use `day_clustered_edge`, not just `edge_vs_control`.** Trade-level z-scores are misleading
  for anything that selects days or fires broadly. `z_paired` is the headline number.
- **Entry timing must be realistic.** For event studies, entry is the *next session's open*,
  never the pre-news close. Anything else is look-ahead.
- **Never let the agent state a fact not traceable to a tool result.** Enforced via
  `SHARED_RULES` in `config.py`, which both `agent.py` and `mcp_server.py` import — edit it in
  one place and all interfaces update.
- **XGBoost return-predictors score R² ≈ 0.** They are displayed as a de-emphasised data point
  and must never drive logic. `meta_label.py` (P(win)) replaced them and is the real signal.

---

## Commands

```bash
python refresh_cache.py          # daily; several minutes, downloads 748 stocks
python main.py                   # CLI — always picks up latest code
streamlit run app.py             # needs manual restart after code changes
python news_watcher.py --once --dry --force   # phone watcher, sends nothing
```

Tests are plain files, no framework, no network:
`test_user_trade.py` `test_discipline.py` `test_trade_journal.py` `test_news_watcher.py`
`test_alert_watcher.py` `test_telegram_bot.py` `test_category_flows.py`
plus `python backtest_engine.py` (self-check).

On Windows use `PYTHONIOENCODING=utf-8` or ₹ symbols crash the console.

---

## Three interfaces, three restart behaviours

- `main.py` (CLI) — re-reads everything each run. **Test fixes here first, it is the fastest signal.**
- `app.py` (Streamlit) — must be manually stopped and restarted after any code change.
- `mcp_server.py` (Claude Desktop) — persistent background process. Needs a full **system-tray
  quit**, not a window close. Editing `tools.py` has zero effect until then.

---

## Recurring bugs — check these first

1. **Duplicate function definitions.** `tools.py` has been patched many times; functions have
   ended up defined twice with the stale copy silently winning. If a fix "doesn't take effect",
   grep for duplicate `def` names before assuming the logic is wrong.
2. **Code inserted before the variable it references.** Sorting/filtering logic must go AFTER
   `df = pd.DataFrame(...)`. Caused a real `UnboundLocalError`.
3. **Feature computation lives in `features.py`.** `cache_manager.py` used to have its own
   duplicated block — any new feature column must appear wherever the cache is built, or it
   silently won't exist at runtime.
4. **yfinance period must be long enough.** A 252-day rolling calc needs `period="2y"`, not
   `"6mo"` — this caused a silent "Unknown" trend tier across the whole scan.
5. **"possibly delisted" in a refresh is usually rate-limiting**, not delisting. The retry pass
   recovers them (49/49 recovered in a recent run). Only worry if a ticker fails twice.
6. **Never duplicate the verdict logic.** `exit_verdict()` and `setup_checklist()` exist so the
   alert watcher and the on-demand check cannot drift apart. Extract, don't copy.

---

## Phone deployment constraints (news_watcher.py)

Runs on a spare Android under Termux. It deliberately imports **neither pandas nor nsefin, and
does not import `config.py`** — all three pull pandas, which compiles from source on Android and
routinely fails. It reads the watchlist with the `csv` module and calls NSE over plain HTTP.

**If you add an import to `news_watcher.py` or `notify.py`, check it is pure-Python.** The only
dependencies on the phone are `requests` and `python-dotenv`. `tools.py` is imported lazily
inside `_context_for()` and allowed to fail, so the phone degrades gracefully.

Deploy: `adb` lives at `~/AppData/Local/Android/Sdk/platform-tools/adb.exe` (not on PATH).
Set `MSYS_NO_PATHCONV=1` in Git Bash. Push to `/sdcard/Download/`, then `cp` from inside Termux —
adb cannot write into Termux's private home. `find /sdcard` does not work on that device; use `ls`.

---

## Tone the user expects

Direct, technically specific, no hedging or flattery. State uncertainty as a number, not a vibe.
If a result is negative, lead with that. He has repeatedly and explicitly valued being told an
idea failed over being handed something that merely looks good — several of his own ideas have
been measured and rejected in this repo, and that is treated as the system working.

Do not volunteer position sizing unless asked; do not assume his capital.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
