# 📈 NSE Momentum & Swing Trading Assistant

> A personal AI-powered research tool for Indian NSE microcap stocks — combining backtested quantitative strategies, institutional flow data, fundamentals, market regime context, and an LLM agent with enforced risk controls.

![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![License](https://img.shields.io/badge/license-Personal%20Use-lightgrey.svg)
![Status](https://img.shields.io/badge/status-active-success.svg)
![Data](https://img.shields.io/badge/data-NSE%20Microcap%20250-orange.svg)

---

## ⚠️ Read this first

**This is a research and decision-support tool. It does not place trades, and it is not financial advice.** Every strategy in this repo was built the honest way: hypothesize → backtest against a random-entry control → only keep what survives. Where a signal didn't survive that test, this README says so plainly. The tool's job is to organize real data and enforce risk discipline — the trading decision is always yours.

---

## 🧠 What this actually is

Most "AI trading bot" projects skip the part where you check if the idea works before building around it. This one doesn't. Every strategy here was validated against **5 years of data across 250 NSE microcap stocks**, benchmarked against a random-entry control group, with statistical significance (z-scores) reported honestly — including the strategies that *didn't* work and were discarded.

The result: two independently validated trading strategies, wrapped in a multi-tool LLM agent that enforces risk rules in code (not just polite prompting), with deterministic fundamental labeling (no LLM-narrated inconsistency) and explicit cross-signal reasoning between market regime and stock-level setups.

---

## 📊 The two validated strategies

### 🔹 Short-term Swing (4–6 days)
| | |
|---|---|
| **Signal** | RSI < 30 (oversold) |
| **Exit** | 2× ATR stop-loss / 2×–3.5× ATR targets |
| **Backtest** | 250 stocks, 5 years, 11,266 simulated trades |
| **Edge vs random entry** | +0.58% per trade |
| **Z-score** | **8.08** (statistically strong) |

### 🔹 Long-term Position (~1 month)
| | |
|---|---|
| **Signal** | Near 52-week high + confirmed uptrend (Price > SMA50 > SMA200) — a **momentum**, not mean-reversion, strategy |
| **Exit** | Fixed -8% stop-loss / +16% target |
| **Backtest** | 250 stocks, 5 years, 52,832 simulated trades |
| **Edge vs random entry** | +1.72% per trade |
| **Z-score** | **12.06** (strongest signal found in this project) |

> 🚫 **What got tested and rejected**: RSI-oversold at the 1-month horizon was tested and *actively underperformed* random entries (z-score **-2.98**). The two strategies are not interchangeable — mean-reversion and momentum are close to opposite effects, and this repo proves it with its own data instead of assuming it.

---

## 🛠️ Feature set

- ✅ **Dual-horizon scanning** across 227+ NSE Microcap 250 index constituents (real, tradable businesses — not hand-picked)
- ✅ **Relative strength vs Nifty 50** — filters out stocks just riding a broad market rally
- ✅ **Sector-relative strength** — filters out stocks just riding a sector-wide rally
- ✅ **Market regime & breadth check** — % of watchlist above 200-day average + Nifty's own trend status, with the agent required to explicitly reason across regime and stock-level signals rather than reporting them separately
- ✅ **Fundamentals** (P/E, revenue/earnings growth, margins, ROE, debt) — free, via yfinance, with **deterministic threshold labels** (no LLM-narrated "low/moderate/high" inconsistency)
- ✅ **Institutional footprint** — 30-day delivery % trend + bulk/block deal tracking, straight from NSE
- ✅ **Earnings calendar awareness** — flags upcoming results that could gap through a stop-loss
- ✅ **Verified company descriptions** — pulled from real filings, with an explicit anti-hallucination rule so the agent never invents business details
- ✅ **Code-enforced risk gates** — blocks position sizing above 2% risk or on parabolic/extreme-momentum setups until explicitly overridden
- ✅ **Multi-step agentic reasoning** — chains tool calls (scan → fundamentals → institutional → results → regime → sizing) automatically
- ✅ **Provider-agnostic** — swap between Groq, DeepSeek, Anthropic, local Ollama, or a self-hosted model via one config line
- ✅ **Local caching layer** — daily refresh, no live API hammering during actual usage

---

## 🏗️ Architecture
User question
│
▼
┌───────────────────────────────┐
│    Agent (multi-step loop)    │  ←── system prompt routes short vs long-term
└───────────────┬───────────────┘
│ tool calls (up to 12 rounds)
▼
┌─────────────────────────────────────────────┐
│  scan_watchlist_text_short / _long           │
│  get_full_analysis (forces full checklist)   │
│    ├─ market regime (long-term only)         │
│    ├─ snapshot (RSI/momentum/ATR/stops)      │
│    ├─ fundamentals (P/E, growth, ROE)        │
│    ├─ institutional activity (delivery/bulk) │
│    └─ upcoming results                       │
│  calculate_position_size (risk-gated)        │
└───────────────┬───────────────────────────────┘
│ reads from
▼
┌─────────────────────────────────────────────┐
│         Local cache (refreshed daily)        │
│  price data · delivery history · bulk deals  │
│  Nifty index · sector RS · market breadth    │
│  results calendar                            │
└───────────────────────────────────────────────┘

## 📁 Project structure
├── config.py                       # watchlist, feature sets, model paths, LLM providers, risk defaults
├── data_fetcher.py                  # short-term feature engineering (RSI, MACD, ATR)
├── data_fetcher_long.py              # long-term feature engineering (SMA50/200, momentum, fundamentals)
├── cache_manager.py                  # local cache: price, delivery, bulk deals, Nifty, sector RS, breadth, results
├── model_trainer_short.py             # trains short-term XGBoost model
├── model_trainer_long.py              # trains long-term XGBoost model
├── refresh_cache.py                   # run daily - refreshes all cached data
├── tools.py                           # 9 agent tools + risk-gating + deterministic labeling logic
├── agent.py                           # LLM agent loop (multi-step tool calling)
├── main.py                            # CLI chat interface
├── app.py                             # Streamlit browser chat interface
├── nse_watchlist_full.csv              # NSE Microcap 250 constituent list
├── requirements.txt
└── trading_model_short.pkl / trading_model_long.pkl   # trained models (minor inputs only, see Limitations)

---

## 🚀 Quick start

```bash
git clone <this-repo-url>
cd trading-assistant
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Create a `.env` file in the project root:
GROQ_API_KEY=your_key_here

First-time setup:
```bash
python model_trainer_short.py    # long-term model is already included; only short-term needs training
python refresh_cache.py
```

Daily use:
```bash
python refresh_cache.py          # refresh once per day
python main.py                   # or: streamlit run app.py
```

---

## 🔧 The 9 agent tools

| Tool | What it does |
|---|---|
| `scan_watchlist_text_short` | Finds RSI<30 candidates (backtested, z=8.08) |
| `scan_watchlist_text_long` | Finds validated momentum candidates: near-high + uptrend + outperforming Nifty (backtested, z=9.69) |
| `get_snapshot_text_short` / `_long` | Full technical snapshot for one stock |
| `get_full_analysis` | **Forces** the complete checklist (regime + snapshot + fundamentals + institutional + results) — no inconsistent skipping between sessions |
| `get_fundamentals_text` | P/E, growth, margins, ROE, debt with deterministic labels, verified business description |
| `get_institutional_activity_text` | 30-day delivery % trend, recent bulk/block deals |
| `check_upcoming_results` | Upcoming earnings/board meetings within the hold window |
| `get_market_regime_text` | Overall market breadth + Nifty trend status - not stock-specific |
| `calculate_position_size` | Exact share count for given capital/risk — **blocks** and requires explicit confirmation above 2% risk or on parabolic setups |

---

## 🧩 Switching LLM providers

One line in `config.py`:
```python
ACTIVE_PROVIDER = "groq"   # or "deepseek", "anthropic", "local_ollama", "kaggle_ngrok", ...
```
Any OpenAI-compatible endpoint works — including local models via Ollama or a self-hosted model tunneled through ngrok. Tested and working across Groq (GPT-OSS-120B, Qwen3.6-27B) with tolerant boolean-type parsing to handle inconsistent tool-calling behavior between models.

---

## 🛑 Honest limitations

- **The XGBoost model signals are weak** — confirmed via backtesting (R² near zero, direction accuracy ~48–50%). Kept in the output for transparency but **never** the basis of a recommendation. The real edge comes entirely from the two validated rule-based strategies above.
- **Backtests exclude trading costs, slippage, and survivorship bias.** Real-world edge should be confirmed via paper trading before committing real capital.
- **Free-tier data sources** (yfinance, nselib, nsefin) occasionally rate-limit or have coverage gaps. The tool degrades gracefully — skips failed tickers, flags stale cache — rather than crashing silently.
- **Sector/Nifty RS and market breadth are reasonable, data-grounded additions but not independently re-backtested** as compound conditions layered onto the two core strategies. Treat them as informed context, not separately validated rules.
- **The agent can occasionally invent plausible-sounding but false specifics** if a data field is genuinely missing — a known LLM failure mode. Mitigated via verified data fields and explicit anti-hallucination instructions, but always sanity-check anything not traceable to an actual tool output.

---

## 🙏 Inspiration & credits

Architecture ideas reviewed (never copied — all code here is original) from:
[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) · [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) · [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) · [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) · [microsoft/qlib](https://github.com/microsoft/qlib) · [Fincept-Corporation/FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal)

---

## 📜 Disclaimer

This project is for personal research and educational purposes. Nothing here constitutes financial advice. Trading equities carries real risk of loss. The author(s) are not registered financial advisors. Use paper trading to validate any strategy before risking real capital.

---

*Built iteratively, backtested honestly, one validated signal at a time.*