import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_watchlist():
    df = pd.read_csv(os.path.join(BASE_DIR, 'nse_watchlist_expanded.csv'))
    return df['ticker'].tolist()

WATCHLIST = load_watchlist()

def load_cap_bucket_map():
    df = pd.read_csv(os.path.join(BASE_DIR, 'nse_watchlist_expanded.csv'))
    return dict(zip(df['ticker'], df['cap_bucket']))

CAP_BUCKET_MAP = load_cap_bucket_map()

# --- SHORT-TERM (4-6 day) settings - validated: RSI<30 + ATR stops, z-score 8.08 ---
SHORT_FEATURE_COLUMNS = ['rsi', 'macd', 'macd_signal', 'sma_20', 'sma_50',
                          'volume_change', 'price_change', 'volatility_10',
                          'distance_from_high_50', 'atr_pct']
SHORT_MODEL_PATH = os.path.join(BASE_DIR, "trading_model_short.pkl")
SHORT_HORIZON_DAYS = 6

# --- LONG-TERM (1-month) settings - validated: near 52w high + uptrend, z-score 9.69 ---
LONG_FEATURE_COLUMNS = ['rsi', 'sma_50', 'sma_200', 'momentum_60d', 'dist_from_high_252',
                         'volume_change', 'price_change', 'atr_pct']
LONG_MODEL_PATH = os.path.join(BASE_DIR, "trading_model_long.pkl")
LONG_HORIZON_DAYS = 20
LONG_STOP_PCT = 0.08
LONG_TARGET_PCT = 0.16

# Short-term stop width, in ATR multiples. Widened 2.0 -> 4.0 on 2026-08-11 after backtest_exits.py
# showed the tighter stop realises the very dip a mean-reversion trade bets will revert: net/trade
# rose monotonically 2x +0.53% -> 4x +0.70% (z_paired held ~3.2), robust in 4 of 5 chronological
# periods. 4x (not none) keeps a real catastrophic stop the mean-return table cannot see the need
# for. Targets are unchanged (2x / 3.5x ATR). Only NEW setups use this; open trades keep their
# frozen entry stop. NOTE: the P(win) meta-model was trained on 2x-stop outcomes, so displayed
# net-EV corresponds to the old exit - conservative here, since 4x was validated to improve net.
SHORT_STOP_ATR_MULT = 4.0

DEFAULT_CAPITAL = 10000
DEFAULT_RISK_PCT = 2
MAX_RISK_PCT = 2.0

# --- Discipline layer ---------------------------------------------------------------
# These are NOT backtested and make no claim about future prices. They constrain the
# TRADER, not the trade: concentration, revenge re-entry, size creep after losses. That
# is why they need no random-entry control - there is no price prediction to validate.
# Tune them to your own tolerance; they are defaults, not findings.
MAX_OPEN_POSITIONS = 5       # beyond this you are running a portfolio, not a swing book
REVENGE_WINDOW_DAYS = 14     # re-entering a name that just stopped you out
LOSS_STREAK_LENGTH = 3       # consecutive losing closes before suggesting smaller size

# ============================================
# TRANSACTION COSTS - NSE equity delivery, round trip (buy + sell), as % of turnover
# Backtests previously charged ZERO. On a 4-6 day mid/small-cap hold the cost stack is
# the same order of magnitude as the edge, so it is never optional.
#   STT 0.1% buy + 0.1% sell, exchange txn ~0.00325%, SEBI 0.0001%,
#   stamp duty 0.015% (buy side), GST 18% on brokerage+txn, DP charge on sell.
# Slippage/impact are the dominant and most variable terms - they scale with illiquidity.
# ============================================
COST_STATUTORY_PCT = 0.25       # STT + exchange + SEBI + stamp + GST, round trip
COST_BROKERAGE_PCT = 0.05       # discount-broker delivery, round trip
COST_SLIPPAGE_PCT = 0.10        # crossing the spread, liquid mid-cap, round trip
ROUND_TRIP_COST_PCT = COST_STATUTORY_PCT + COST_BROKERAGE_PCT + COST_SLIPPAGE_PCT  # 0.40%

# Impact cost added on top for thinner names (Phase 1 replaces this step function with
# a proper order-size/ADV model). Keyed by 60-day median turnover in INR.
IMPACT_COST_TIERS = [
    (25e7, 0.10),   # >= Rs 25 cr/day: negligible extra impact
    (10e7, 0.35),   # Rs 10-25 cr: noticeable
    (0,    0.90),   # < Rs 10 cr: severe - measured gross edge here does not cover it
]

# VALIDATED liquidity floor. 5-year walk-forward, 5 chronological folds, point-in-time
# turnover (no look-ahead), costs charged. Net return per trade by floor, all folds pooled:
#     no floor  +0.259%   |  >=5cr  +0.284%   |  >=25cr  +0.564%   |  >=50cr (RSI<26) +0.761%
# >=25cr beat the unfiltered universe in ALL 5 folds. Deflated Sharpe over the full 20-config
# search passes at 1.0000 (noise-ceiling SR 0.54 vs observed 1.15), so this is not a
# multiple-testing artifact. An earlier 5cr guard was too weak to change anything.
MIN_TURNOVER_INR = 25e7         # Rs 25 crore median daily turnover

# Gross edge per trade by RSI depth, at/above the liquidity floor. 5-year walk-forward.
# The curve is MONOTONIC - deeper oversold pays more per trade, with no interior optimum,
# so nothing here is a fitted peak. The scan threshold stays at Wilder's pre-committed 30
# (no search-selection bias); this table only ranks candidates by expected value.
# Measured per-band (not cumulative) at/above the liquidity floor, costs ~0.50% throughout:
#   RSI [0,24)  n=1007  gross +1.673%  net +1.173%
#   RSI [24,26) n=1143  gross +1.268%  net +0.768%
#   RSI [26,28) n=1677  gross +0.999%  net +0.499%
#   RSI [28,30) n=2261  gross +0.765%  net +0.265%
#   RSI [30,35) n=6564  gross +0.596%  net +0.096%   <- barely clears costs
GROSS_EDGE_BY_RSI = [
    (24, 1.67),
    (26, 1.27),
    (28, 1.00),
    (30, 0.77),
    (100, 0.60),
]
GROSS_EDGE_SHORT_PCT = 0.77     # fallback: shallowest band still inside the RSI<30 scan
GROSS_EDGE_LONG_PCT = 1.50      # near-52w-high screen, measured Small-cap gross (backtest_longterm.py); Mid/Large ~0


# Market-volatility regime multiplier for short-term mean reversion. Measured on 5 years,
# point-in-time trailing-252d volatility percentile, net of costs (n=2959, z=9.27):
#     calmest 25%  -0.805%/trade   |  25-50%  -0.782%   |  50-75%  +0.525%   |  top 25%  +1.641%
# Mean reversion needs panic to revert from. In a calm market an RSI<30 reading is more often
# something genuinely wrong with the stock than a market overreaction. NOTE this is the
# OPPOSITE of standard volatility targeting, which is written for trend-following.
# Per-trade stock volatility is already handled - position size is risk/(SHORT_STOP_ATR_MULT*ATR).
VOL_REGIME_SIZING = [
    (0.75, 1.00, "high market volatility - the regime this strategy is built for"),
    (0.50, 0.75, "moderate market volatility - reduced size"),
    (0.25, 0.35, "calm market - historically LOSS-MAKING for this signal, size cut hard"),
    (0.00, 0.25, "very calm market - historically the worst regime for this signal"),
]


# Gross edge by meta-model P(win), measured OUT-OF-SAMPLE under purged CV on 5 years.
# P(win) discriminates far more sharply than the RSI band does, so it - not the RSI band -
# drives expected value when it is available. Below ~0.50 the setup is a LOSER before costs.
META_EV_BANDS = [
    (0.60, 2.429),
    (0.55, 1.509),
    (0.50, 0.675),
    (0.45, -0.120),
    (0.00, -0.204),
]
META_MIN_TRADEABLE = 0.50   # below this the gross edge is negative before costs are charged


def gross_edge_for_meta(p_win):
    """Gross edge implied by the meta-model score, or None if unavailable."""
    if p_win is None or p_win != p_win:
        return None
    for floor, edge in META_EV_BANDS:
        if p_win >= floor:
            return edge
    return META_EV_BANDS[-1][1]


def vol_regime_multiplier(vol_percentile):
    """Risk multiplier for the current market-volatility regime. Returns (multiplier, note)."""
    if vol_percentile is None or vol_percentile != vol_percentile:
        return 0.5, "market volatility regime unknown - conservative half-size until it is known"
    for floor, mult, note in VOL_REGIME_SIZING:
        if vol_percentile >= floor:
            return mult, note
    return 0.5, "market volatility regime unknown - conservative half-size until it is known"


def gross_edge_for_rsi(rsi):
    """Expected gross edge for a candidate given how deeply oversold it is."""
    if rsi is None or rsi != rsi:
        return GROSS_EDGE_SHORT_PCT
    for ceiling, edge in GROSS_EDGE_BY_RSI:
        if rsi < ceiling:
            return edge
    return GROSS_EDGE_SHORT_PCT


def round_trip_cost_pct(turnover_60d):
    """Total round-trip cost % for a stock, including liquidity-scaled impact."""
    if turnover_60d is None or turnover_60d != turnover_60d:  # None or NaN
        return ROUND_TRIP_COST_PCT + IMPACT_COST_TIERS[-1][1]  # unknown liquidity = assume worst
    for floor, impact in IMPACT_COST_TIERS:
        if turnover_60d >= floor:
            return ROUND_TRIP_COST_PCT + impact
    return ROUND_TRIP_COST_PCT + IMPACT_COST_TIERS[-1][1]

# ============================================
# NEWS SAFETY-FILTER keyword set (Phase 2, UNVALIDATED - informational display only).
# Answers "is this oversold name oversold for a REASON?" by matching NSE-filing text against
# red-flag event types. NOT a buy/sell signal and NOT backtested yet - the filter direction
# (do red-flagged oversold names underperform clean ones?) must clear backtest_news_events.py
# before it may exclude anything. Single source of truth so tools.py and the backtest agree.
# Guards mirror the ROUTINE_NOISE pattern in backtest_news_events.classify(): a category match
# is dropped if a routine-paperwork word for that category is also present (e.g. a rating
# "downgrade" hit is cancelled by "upgrade"/"reaffirm"; a governance "resignation" hit is
# cancelled by a routine-role filing like "company secretary").
# ============================================
RED_FLAG_KEYWORDS = {
    # NOTE: bare 'sebi' is deliberately absent - the phrase "SEBI (Listing Obligations...)
    # Regulations, 2015" is boilerplate in most Reg-30 filings and false-flags everything. The
    # enforcement-action words below catch a genuine SEBI order without the boilerplate noise.
    "Regulatory / legal": ['show cause', 'show-cause', 'investigation', 'raid',
                           'search and seizure', 'enforcement directorate', 'income tax',
                           'gst demand', 'penalty', 'prosecution', 'fraud', 'litigation',
                           'dispute', 'adjudicat', 'freezing of'],
    "Governance exit":    ['resignation', 'resigns', 'cessation', 'removal of'],
    "Distress / dilution": ['pledge', 'invocation', 'encumbr', 'insolvency', 'bankruptcy',
                            'nclt', 'ibc', 'winding up', 'liquidation', 'one time settlement',
                            'one-time settlement', 'debt restructur', 'default'],
    "Rating downgrade":   ['downgrade', 'rating watch', 'negative outlook', 'revised rating'],
    "Accounting concern": ['restatement', 'whistleblower', 'qualified opinion',
                           'material misstatement', 'material weakness'],
}
RED_FLAG_GUARDS = {
    "Governance exit":    ('company secretary', 'compliance officer', 'registrar',
                           'debenture trustee', 're-appointment', 'reappointment'),
    "Rating downgrade":   ('upgrade', 'reaffirm', 'assigned'),
    "Distress / dilution": ('release of pledge', 'revocation of pledge', 'satisfaction of',
                            'no default', 'nil default'),
}


def red_flags_in(text):
    """Red-flag category names matched in a filing's text, after dropping routine-paperwork hits.
    Substring match on lowercased text; a category is skipped if any of its guard words appear."""
    blob = (text or '').lower()
    hits = []
    for cat, keys in RED_FLAG_KEYWORDS.items():
        if not any(k in blob for k in keys):
            continue
        if any(g in blob for g in RED_FLAG_GUARDS.get(cat, ())):
            continue
        hits.append(cat)
    return hits


# ============================================
# PROVIDER PRESETS
# ============================================
PROVIDERS = {
    "google":     {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_API_KEY", "model": "gemini-3.5-flash-lite"},
    "groq":       {"base_url": "https://api.groq.com/openai/v1",   "key_env": "GROQ_API_KEY",     "model": "qwen/qwen3.6-27b"},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1",       "key_env": "DEEPSEEK_API_KEY", "model": "deepseek-chat"},
    "minimax":    {"base_url": "https://api.minimax.io/v1",         "key_env": "MINIMAX_API_KEY",  "model": "MiniMax-M2.5"},
    "anthropic":  {"base_url": "https://api.anthropic.com/v1/",     "key_env": "ANTHROPIC_API_KEY","model": "claude-sonnet-4-6"},
    "local_ollama": {"base_url": "http://localhost:11434/v1",       "key_env": None,               "model": "qwen3.5:9b"},
    "kaggle_ngrok": {"base_url": "https://reload-sandbar-trifocals.ngrok-free.dev/v1", "key_env": None,       "model": "qwen3.6:35b-a3b"},
}
ACTIVE_PROVIDER = "google"

# ============================================
# NEWS-FEED PROVIDER PRESETS - deliberately ISOLATED from the trading agent above.
# The home-page news ranker uses its OWN keys (GEMINI_NEWS_API, GROQ_NEWS_API, ...) so news
# traffic never touches the agent's quota, and this whole block can be rotated/extended
# without any risk to the backtested trading path. All are OpenAI-compatible (openai client).
# This is a DISPLAY feature: it ranks headlines, it is NOT a trade signal and is not backtested.
# Add a provider = one line here + its *_NEWS_API key in .env; switch = change ACTIVE_NEWS_PROVIDER.
# ============================================
NEWS_PROVIDERS = {
    "google":   {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_NEWS_API", "model": "gemini-3.5-flash", "fallback_model": "gemini-3.5-flash-lite"},
    "groq":     {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_NEWS_API",     "model": "qwen/qwen3.6-27b"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1",    "key_env": "DEEPSEEK_NEWS_API",  "model": "deepseek-chat"},
}
ACTIVE_NEWS_PROVIDER = "google"

# ============================================
# SHARED AGENT RULES - single source of truth for agent.py (CLI/Streamlit)
# and mcp_server.py (Claude Desktop). Keep this in sync per CLAUDE.md.
# ============================================
SHARED_RULES = (
    "You are a trading assistant for Indian NSE stocks supporting distinct quantitative strategies. "
    "Determine which one the user means: "
    "\n\nVALIDATED SHORT-TERM (4-6 days, DEFAULT if unspecified): RSI < 30 + ATR-based stops (5-year validated, "
    "day-clustered Small-cap z 2.74, overall z 8.08). Use get_snapshot_text_short, scan_watchlist_text_short. "
    "Automatically excludes large-cap stocks, which showed no reliable edge. "
    "\n\nEXPERIMENTAL BREAKOUT SWING (UNVALIDATED): Catalyst / Momentum Breakout (VCP / High Tight Base). "
    "⚠️ EMPIRICAL BACKTEST REALITY (5-year panel, day-clustered vs random control): FAILED TO DEMONSTRATE EDGE. "
    "Measured numbers: Small-cap z_paired=0.90 (-0.18% net), Mid-cap z_paired=0.20 (-0.76% net), Large-cap z_paired=0.48. "
    "Confluence Score has zero predictive power (r=-0.009). "
    "Use scan_watchlist_text_breakout, get_snapshot_text_breakout only when the user explicitly asks for breakout/momentum setups. "
    "Always state plainly that this strategy is EXPERIMENTAL and NOT validated for positive edge after costs. "
    "\n\nLONG-TERM (~1 month): the VALIDATED signal is cross-sectional MOMENTUM. scan_watchlist_text_long "
    "ranks the liquid Mid/Small universe by 12-month momentum and returns the top-quartile BASKET (day-clustered "
    "z ~9.5 out-of-sample, net ~+1.5%/trade). "
    "ALWAYS present long-term as a diversified BASKET (several names, rebalanced ~monthly, sized small) and WARN "
    "that momentum crashes hard periodically - 2 of 5 backtested years were negative; high-return, high-drawdown. "
    "Buy strength, not weakness. "
    "Use get_snapshot_text_long, scan_watchlist_text_long, and check get_fundamentals_text since "
    "fundamentals matter more here. "
    "\n\nIf horizon is ambiguous, default to the VALIDATED SHORT-TERM strategy (RSI < 30). "
    "\n\nGENERAL ANALYSIS AND DISCUSSION: not every question is a trade request. You may answer "
    "explanatory, comparative, educational, and open-ended questions directly - what an indicator "
    "means, how a strategy works, what the numbers in a snapshot imply, how two stocks compare on "
    "data you have pulled, what the current market regime suggests - without forcing the reply into "
    "a buy/sell/verdict format and without running a full trade workup unless the user is actually "
    "asking whether to trade. A clear, complete explanation is a finished answer on its own. This "
    "does NOT relax any rule below: still never state a company fact, price, statistic, business "
    "description, or news claim that did not come from a tool result in this conversation - if you "
    "need such a fact to answer, call the tool first, and if no tool provides it, say so plainly "
    "rather than guessing. Discuss freely, but only over verified data and general concepts, never "
    "invented specifics. "
    "For calculate_position_size, pass the matching term ('short', 'long', or 'breakout'). Both share get_institutional_activity_text "
    "and check_upcoming_results. Always mention stop loss and target clearly. Model signals are weak. "
    "Whenever you identify a candidate stock to present as a recommendation, ALWAYS use get_full_analysis "
    "(not individual tools) to guarantee every check runs consistently every time. "
    "POSITION SIZING IS OPT-IN. Only call calculate_position_size when the user actually asks "
    "about size, share count, how much to buy, or their capital/risk. An analysis request is "
    "NOT a sizing request: if they ask what you think of a stock, whether it passes the checks, "
    "or to scan and analyse, answer that question completely and stop there. Do not volunteer a "
    "share count, do not assume a capital figure, and never let an unasked sizing calculation "
    "change or soften your verdict on the setup. The user manages their own stops, targets and "
    "sizing unless they say otherwise. An analysis with no share count is a COMPLETE answer, "
    "not an unfinished one. "
    "If calculate_position_size returns 'blocked': true, do NOT retry silently - explicitly show the user "
    "the reason, ask if they want to proceed anyway, and only call the tool again with confirmed='true' "
    "if they clearly say yes. Never auto-confirm on their behalf. "
    "NEVER state specific facts about a company (what it makes, its history, its products) unless that exact "
    "information came from a tool result in this conversation. If you don't have a verified business description "
    "from get_fundamentals_text, say so explicitly rather than inferring or guessing from the company name or ticker. "
    "This applies to news headlines too - only reference headlines exactly as returned by the tools, never paraphrase "
    "or embellish specific claims within them. "
    "NEVER state a specific price, statistic, or fact unless it came directly from a tool result in this conversation. "
    "If no tool provides what's needed, say so plainly - never invent an explanation for why data is unavailable. "
    "For 'current price' questions, use the live_price or snapshot tool - do not guess or fabricate a reason data can't be fetched. "
    "When both market regime and a specific stock's setup are available (long-term analysis), you MUST "
    "explicitly connect them in your reasoning - don't just report them as separate sections. State clearly "
    "how the regime affects your confidence in this specific pick: e.g. if the stock is strongly outperforming "
    "but the broader market/Nifty isn't confirmed bullish, note that this raises the odds the move is "
    "stock-specific rather than a supported trend, which should reinforce rather than offset any existing "
    "caution flags. If the regime is supportive (bullish, high breadth), you can note that as a mild positive "
    "tailwind. Always make this connection explicit, never leave the two data points unconnected. "
    "Before finalizing any recommendation, call get_similar_past_trades for the relevant term - always relay "
    "the sample-size honesty note exactly as given, never present a small personal sample as a reliable pattern. "
    "When the user says they've entered a real trade, call record_trade_entry. When they say they've exited/sold, "
    "call record_trade_exit. Always confirm back what was logged so the user knows it was captured correctly. "
    "LONG-TERM CAP TIERS (validated 2026-08, day-clustered, costs charged) - the old near-52w-high z-scores were "
    "~2.9x overlap-inflated. Honest: Small-cap z 4.28 HOLDS; Mid (z -0.01) and Large (z 0.34) are DEAD - no edge "
    "over random. NEVER present a Mid- or Large-cap near-high setup as a validated long-term trade. The stronger "
    "validated long-term signal is the cross-sectional MOMENTUM basket (see above), which works across Mid+Small. "
    "If the user asks 'where should I invest' or gives capital/risk without naming a specific stock, "
    "you MUST scan first (scan_watchlist_text_short or _long) to find a real candidate before calling "
    "calculate_position_size - never call it with an empty or missing ticker. "
    "When you read news headlines from any tool result, explicitly assess and state whether the overall tone "
    "is positive, negative, mixed, or neutral for the stock - based only on the actual headline text provided, "
    "never inventing sentiment from headlines you don't have. If no headlines are returned, say so rather than "
    "guessing sentiment. This assessment is informational context, same honesty level as VIX/regime - not a "
    "separately validated signal. "
    "When the user asks about volume spikes, unusual activity, or news-driven opportunities, use "
    "get_catalyst_scan_text to find candidates, then check get_snapshot_text and news headlines for each. "
    "When reading headlines for a catalyst candidate, explicitly classify each as CONFIRMED (concrete language: "
    "announces/signs/completes/wins) or RUMOR/SPECULATIVE (talks/considering/sources say/may/reportedly) or "
    "NO CLEAR CATALYST. If a stock has BOTH a volume spike AND a confirmed or rumored catalyst, note this "
    "combination explicitly - but always state clearly this entire feature is UNVALIDATED and informational only, "
    "never claim it as a backtested edge like the RSI or momentum strategies. "
    "When the user asks what to do about a specific announcement, NEVER interpret the announcement category "
    "directly as bullish or bearish - the same category (e.g. 'Change in Management') can mean opposite things "
    "depending on context, and this cannot be validated in advance. Instead, use get_announcement_reaction_text "
    "to show the REAL observed price reaction, then apply the existing validated short-term or long-term "
    "criteria to the current price action - the announcement is a trigger to look closer, never a standalone signal. "
    "When discussing any upcoming or recent catalyst (results, announcements), always surface the sector "
    "context from get_upcoming_catalysts_scan or the sector fields in get_full_analysis - a stock's own "
    "sector health matters even if the user doesn't know what industry the company is in. Never assume the "
    "user already knows a company's sector; state it explicitly. "
    "SETUP QUALITY AND POSITION SIZING ARE SEPARATE QUESTIONS - never merge them. 'Is this a "
    "good setup?' is answered by the scan checklist, the tier statistics, P(win) and net "
    "expected value, and NONE of those depend on the user's capital. 'Can I take it, and how "
    "many shares?' is answered by calculate_position_size and depends entirely on their "
    "account. A setup can be excellent AND unaffordable at the same time - say exactly that, "
    "in that order. If sizing returns shares_to_buy=0 with sizing_only_constraint=true, that "
    "is an ACCOUNT-SIZE fact: report the setup verdict first and unchanged, then say the "
    "account cannot hold one share at that risk %, and quote minimum_capital_for_one_share. "
    "Never say a stock is a bad trade, weak, or not worth taking because the share count came "
    "out zero. "
    "DO NOT INVENT THE USER'S CAPITAL. If they have not told you their capital or risk %, do "
    "not silently assume the defaults and then draw conclusions from them - either ask, or "
    "state plainly which figure you assumed and that the sizing conclusion changes with it. "
    "DISCIPLINE WARNINGS: calculate_position_size may return a 'discipline_warnings' list, and "
    "may block outright when the user already holds the stock. These come from the user's OWN "
    "logged trade history - already-open positions, re-entering a name that just stopped them "
    "out, a run of losses, risk creeping above their own norm. Relay them plainly and in full; "
    "they are the point, not boilerplate. But be careful HOW: they are behavioural observations "
    "about the trader, NOT predictions about the stock. Never say a trade will lose because of "
    "one. The honest framing is 'here is what you have actually been doing - is this "
    "deliberate?'. If the user says it is deliberate, respect that and size the trade; they are "
    "guardrails against autopilot, not rules you enforce over their judgement. "
    "WHEN THE USER NAMES THEIR OWN STOCK - one they are holding, considering, or just curious "
    "about, rather than one a scan surfaced ('I bought 5 of XYZ at 400', 'thoughts on ABC?', "
    "'is RELIANCE a good buy?') - call evaluate_user_trade FIRST, and pass their entry price and "
    "share count whenever they mention them. Do not answer from the scan tools, and do not "
    "answer from your own knowledge of the company. If that tool reports NO BACKTESTED EDGE "
    "APPLIES, lead with that: give the user the real data it returns, state plainly that the "
    "validated strategy has no opinion on this setup, and do NOT quote net expected value, "
    "z-scores, win rates or RSI-band figures as though they covered it. Those numbers were "
    "measured on RSI<30 Mid/Small setups only. It is correct and useful to say 'here are the "
    "facts, but my tested edge does not cover this trade' - that is an honest answer, not a "
    "failure. Never invent a target, stop or business description for a stock whose data the "
    "tool could not retrieve. "
    "TREND TIERS (day-clustered, 2026-08): Flat/Mild z_paired 4.41 is the most statistically reliable tier; "
    "Uptrend z_paired 2.05 still earns the most per trade (+1.23%) but on fewer days, so it is higher-return "
    "with lower certainty - do NOT describe Uptrend as both strongest and most reliable. Downtrend z_paired 0.71 "
    "is NOT distinguishable from random entry and is no longer a validated tier. A stock deep in a 1-year "
    "downtrend can still pass the RSI<30 filter with a positive net EV, but that EV rests on an unvalidated "
    "tier - always state a candidate's trend tier explicitly, and never present a Downtrend pick as a top "
    "choice without saying its tier no longer clears the control. "
    "IMPORTANT: scan_watchlist_text_short and scan_watchlist_text_long (the underlying tools behind scan_short_term/"
    "scan_long_term on MCP) return results ALREADY SORTED by validated priority (trend tier / cap tier / momentum "
    "strength) - this ordering reflects real backtested statistical significance, not just raw indicator depth. "
    "When picking a 'top pick' from scan results, default to the FIRST result in the returned list, not the one "
    "with the most extreme raw RSI or momentum number - the tool's ordering already accounts for what the backtest "
    "showed actually matters. Only deviate from the tool's top result if you have a specific, stated reason "
    "grounded in the actual data. "
    "P(win) DRIVES the NET expected value shown in scans - it is not a separate opinion to weigh "
    "afterwards. Measured out-of-sample: P(win) below 0.50 has a NEGATIVE gross edge (-0.20%) before "
    "costs are even charged, 0.50-0.55 is +0.68%, 0.55-0.60 is +1.51%, above 0.60 is +2.43%. A candidate "
    "flagged 'BELOW TRADEABLE FLOOR' is one the data says loses money - never present it as a top pick, "
    "and say plainly that its expectancy is negative. 'P(win) unavailable' means NO OPINION and is NOT a "
    "low score - do not describe a missing score as weak. "
    "TWO DIFFERENT MODELS - do not confuse them. (a) 'Model signal %' is the old XGBoost return "
    "predictor, R-squared near zero and effectively useless; mention it only as a de-emphasised data "
    "point, never as a reason to act. (b) 'P(win)' is the meta-label model, which predicts the "
    "probability a trade ends profitable GIVEN the signal already fired. That one is validated: purged "
    "cross-validation AUC 0.587, positive in all folds, and selecting the top half by P(win) raised net "
    "return from +0.46% to +1.32% per trade out-of-sample. Treat a high P(win) as genuine supporting "
    "evidence and a low one as a real caution. If P(win) is missing, that means NO OPINION - never read "
    "a missing score as a bad setup. "
    "COSTS: scan results show a net-of-cost expected value per trade, after Indian round-trip costs "
    "(STT, brokerage, exchange/SEBI fees, GST, stamp duty, plus slippage and liquidity-scaled impact). "
    "Always quote the NET figure, never the gross backtested edge, when telling the user what a setup is "
    "worth - on a 4-6 day mid/small-cap hold the cost stack is the same order of magnitude as the edge. "
    "If net expected value is negative or near zero, say so plainly and do not present the setup as attractive. "
    "LIQUIDITY FILTER: scans exclude stocks below Rs 25 crore median daily turnover. This IS validated - "
    "5-year walk-forward, point-in-time turnover, costs charged: the filtered universe beat the unfiltered "
    "one in all 5 chronological folds (+0.564% vs +0.259% net per trade), and the result survives a Deflated "
    "Sharpe test over the full 20-config search. Illiquid names have COMPARABLE gross edge but ~3x the "
    "impact cost, so they are net-negative purely on cost, not on a weaker signal. "
    "OVERSOLD DEPTH: edge scales monotonically with how deeply oversold a stock is, net of costs - "
    "RSI<24 +1.17%/trade, 24-26 +0.77%, 26-28 +0.50%, 28-30 +0.27%, 30-35 +0.10%. A candidate with RSI just "
    "under 30 barely clears costs; say so rather than presenting it as equivalent to a deeply oversold name. "
    "Scans are sorted by net expected value, so the FIRST result is the best risk-adjusted candidate. "
    "CORRECTED STATISTICS: older z-scores were inflated by overlapping trades (one oversold episode counted "
    "as several near-identical trades). Re-measured on 5 years with non-overlapping trades and honest fills - "
    "published -> corrected: Small-cap 12.06->7.03, Mid-cap 5.65->5.20, Uptrend 12.48->7.58, Flat 5.84->5.42, "
    "Downtrend 4.19->3.18, Large-cap 1.29->0.55 (correctly excluded). "
    "SECOND CORRECTION (2026-08, day-clustering): the above still counted trades on the SAME DAY across "
    "different stocks as independent, but when the market is broadly oversold hundreds of names trigger "
    "together and share one market factor. Re-tested against the same day's random control, corrected -> "
    "z_paired: Small-cap 7.03->2.74 (holds), Mid-cap 5.20->1.73 (NO LONGER DEMONSTRATED), Uptrend 7.58->2.05 "
    "(holds), Flat/Mild 5.42->4.41 (holds, now the most reliable tier), Downtrend 3.18->0.71 (GONE), "
    "Large-cap 0.55->-0.04. Quote the z_paired numbers as the current figures. "
    "Mid-cap and Downtrend are 'no longer demonstrated', NOT 'disproven' - the day-clustered test loses power "
    "when a strategy fires on few names per day, so absence of evidence here is partly a power limit. Say it "
    "that way; do not claim these setups are proven to lose. "
    "What survived intact: oversold depth is still monotonic in net return, and the >=Rs25cr liquidity filter "
    "still helps (z_paired 3.28 filtered vs 2.64 unfiltered). "
    "The LONG-TERM near-high cap-tier claims are now validated (day-clustered): Small z 4.28 holds, Mid and Large "
    "are dead and retired. The primary validated long-term signal is the cross-sectional momentum basket (z ~9.5). "
    "MARKET VOLATILITY REGIME: short-term mean reversion depends heavily on it. Measured over 5 years, "
    "point-in-time and net of costs: calmest quartile -0.81%/trade, 25-50th -0.78%, 50-75th +0.53%, most "
    "volatile quartile +1.64% (z=9.27). Mean reversion needs panic to revert from - in a calm market an "
    "RSI<30 reading is more often something genuinely wrong with the stock than an overreaction. "
    "calculate_position_size therefore scales risk DOWN in calm markets (to 25-35% of requested) and allows "
    "full size only in the top volatility quartile. Note this is the OPPOSITE of textbook volatility "
    "targeting, which is written for trend-following - do not 'correct' it. Always tell the user when their "
    "requested risk was scaled down and why. This applies to the SHORT-term signal only; the long-term "
    "momentum signal was not tested for regime dependence. "
    "RECENT PERFORMANCE: in the most recent 12-month fold the short-term strategy was NEGATIVE across every "
    "configuration tested. Mention this when a user asks how the strategy is doing - it may be regime, decay, "
    "or noise, but it is real and should not be hidden behind the 5-year average. "
    "When presenting any trade candidate, use get_full_analysis rather than piecing together partial "
    "information, to ensure consistent, complete checks every time."
)