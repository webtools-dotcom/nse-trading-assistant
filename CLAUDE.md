\# NSE Trading Assistant — Claude Code Instructions



\## Commands

\- Refresh data: `python refresh\_cache.py` (takes several minutes, downloads 748 stocks)

\- Run CLI: `python main.py`

\- Run Streamlit: `streamlit run app.py`

\- Test a single script: activate venv first — `venv\\Scripts\\activate`



\## Critical: three interfaces, three restart behaviors

\- `main.py` (CLI): re-reads all code fresh every run. Safe to test changes here first.

\- `app.py` (Streamlit): must be manually stopped and restarted after any code change.

\- `mcp\_server.py` (Claude Desktop): runs as a persistent background process. Editing

&#x20; `tools.py`/`cache\_manager.py`/`data\_fetcher\*.py` has NO effect until Claude Desktop is

&#x20; fully quit (system tray → Quit, not window close) and reopened.

When testing a fix, always verify via CLI first — it's the fastest signal.



\## Recurring bug patterns in this codebase — check these first

1\. \*\*Duplicate function/tool definitions.\*\* `tools.py` has been patched many times;

&#x20;  `scan\_watchlist\_text\_short` and others have previously ended up defined twice, with

&#x20;  the earlier (stale) copy silently winning or causing confusion. If a fix "doesn't

&#x20;  take effect," grep for duplicate `def` names before assuming the logic is wrong.

2\. \*\*Code inserted before the variable it references exists.\*\* When adding sorting/filtering

&#x20;  logic to a function, it must go AFTER the `df = pd.DataFrame(...)` line, not before.

&#x20;  Caused a real `UnboundLocalError` once — check placement carefully.

3\. \*\*Groq/Qwen tool-calling sends malformed types\*\*: numbers as strings (`"30"` not `30`),

&#x20;  booleans as strings (`"true"`), and sometimes nested objects (`{"limit": {"limit": 10}}`).

&#x20;  All numeric/boolean tool parameters MUST use `"type": \["number","string","object"]` /

&#x20;  `\["boolean","string"]` in TOOL\_DEFINITIONS, and be passed through `parse\_number()` /

&#x20;  `parse\_bool()` in `execute\_tool` before use. This is NOT needed in `mcp\_server.py` —

&#x20;  Claude's own MCP client sends properly typed JSON.

4\. \*\*A fix applied to `data\_fetcher.py`'s `add\_features()` does NOT affect the actual cache.\*\*

&#x20;  `cache\_manager.py`'s `refresh\_price\_cache\_short`/`\_long` have their OWN duplicated

&#x20;  feature-computation blocks and do not call `add\_features()`. Any new feature column

&#x20;  must be added in BOTH places, or it silently won't appear in the live cache.

5\. \*\*yfinance download period must be long enough for the feature.\*\* A 252-day (1yr)

&#x20;  rolling calc needs `period="2y"`, not `"6mo"` — this caused a real silent "Unknown"

&#x20;  trend-tier bug across the entire scan.



\## Non-negotiable project discipline

\- Every new signal/filter idea gets backtested against a random-entry control (see

&#x20; `backtest\_\*.py` files for the pattern) BEFORE being added to a live tool. Never add

&#x20; an untested "seems obviously right" rule — we've been wrong about "obvious" before

&#x20; (see README: shallow-pullback hypothesis was rejected by real data).

\- Never let the agent state a specific fact (price, news, business description) not

&#x20; traceable to an actual tool result. This is enforced via SYSTEM\_PROMPT in agent.py

&#x20; and `instructions=` in mcp\_server.py's FastMCP() — keep both in sync when adding rules.

\- Model (XGBoost) signals are proven weak (R² ≈ 0) — never let them drive logic beyond

&#x20; being displayed as a labeled, de-emphasized data point.



\## Full project context

See @README.md for the complete strategy tables, architecture, and feature list.

