"""Learn / Glossary page: plain-English education for new traders.
Static, zero-risk guide explaining daily routines, key metrics, honest empirical lessons, and risk discipline.
"""

from datetime import datetime
import streamlit as st

from ui_common import inject_theme, render_nav, IST

st.set_page_config(
    page_title="Learn & Glossary",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)
inject_theme()
render_nav("learn")

# Hide sidebar CSS
st.markdown("""
<style>
section[data-testid="stSidebar"],
[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] {
    display: none !important;
}
.block-container { max-width: 1100px !important; }

.learn-card {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 16px 20px;
    margin: 12px 0 20px 0;
}
.learn-term-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--accent-amber);
    margin-bottom: 6px;
}
.learn-what {
    font-size: 0.88rem;
    color: var(--text-primary);
    line-height: 1.5;
    margin-bottom: 6px;
}
.learn-why {
    font-size: 0.82rem;
    color: var(--text-secondary);
    line-height: 1.45;
}
.learn-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 3px;
    background: var(--accent-amber-subtle);
    color: var(--accent-amber);
    border: 1px solid var(--accent-amber-border);
    margin-right: 6px;
}
.step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--accent-amber);
    color: #0C0D10;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    margin-right: 8px;
}
</style>
""", unsafe_allow_html=True)

# Terminal Header
now = datetime.now(IST)
st.markdown(f"""
<div class="terminal-header"><div class="terminal-title-row">
  <div class="terminal-title"><span class="terminal-logo">📚</span> TRADING SYSTEM PLAYBOOK &amp; GLOSSARY</div>
  <div class="terminal-eod-pill">● {now.strftime('%d %b %Y · %I:%M %p IST')}</div>
</div><div class="terminal-sub">Plain-English guide to market concepts, backtested reality, and daily trading routines</div></div>
""", unsafe_allow_html=True)

st.markdown('<div class="news-group">🗓️ 1. How to Use This Suite Every Day</div>', unsafe_allow_html=True)

st.markdown("""
<div class="learn-card">
  <p><span class="step-num">1</span><b>Open Home — Read the Market Mood &amp; News</b><br>
  Start your routine on the Home page. Check the top market strip and market mood gauge to see whether the broader tape is risk-on or risk-off. Review curated, prioritized news headlines to spot major corporate events, earnings releases, or regulatory filings affecting your watchlist.</p>
  
  <p><span class="step-num">2</span><b>Open Recap — Inspect Today's Market Action</b><br>
  Switch to the Recap tab to see index breadth (how many stocks are above their 200-day average), top gainers/losers, most active stocks by volume, and sector leadership. Check institutional vs retail flows to see who provided liquidity today.</p>
  
  <p><span class="step-num">3</span><b>Check Watchlist — Monitor Your Candidate Pool</b><br>
  Review the personal watchlist for stocks showing extreme oversold RSI levels (&lt;30) or strong 1-year momentum trends. Add newly discovered companies or prune tickers that no longer fit your criteria.</p>
  
  <p><span class="step-num">4</span><b>Use Assistant — Perform Deep Quantitative Analysis</b><br>
  Click through to the Assistant tab for any specific stock you want to trade. The Assistant forces a rigorous checklist: 200-day trend tier, oversold depth, valuation sanity, institutional delivery patterns, and upcoming corporate catalysts.</p>
  
  <p><span class="step-num">5</span><b>Log Trades in Journal — Track Real Execution &amp; Health</b><br>
  Whenever you enter or exit a real position, record it in the Journal. Over time, the journal measures your true execution edge, checks for psychological pitfalls (like revenge trades), and alerts you if market conditions decay.</p>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="news-group">📖 2. Core Concepts &amp; Glossary</div>', unsafe_allow_html=True)

terms = [
    ("RSI (Relative Strength Index) & RSI < 30",
     "RSI measures the speed and magnitude of recent price changes on a scale of 0 to 100. When RSI drops below 30, a stock is statistically oversold.",
     "The system's core 4–6 day swing strategy is built on RSI < 30 in Mid/Small-cap stocks. It bets on mean-reversion — that extreme panic selling has temporarily pushed the price below fair value."),

    ("India VIX (Volatility Index)",
     "VIX measures the stock market's expectation of volatility over the next 30 days based on Nifty option prices. High VIX (e.g. >18) means market fear; low VIX means calm complacency.",
     "Mean-reversion needs panic to revert from. Backtests over 5 years show the RSI < 30 strategy is most profitable during high-volatility regimes and loses money in ultra-calm markets."),

    ("Market Breadth (% Above 200-day SMA)",
     "Breadth measures the percentage of all stocks in the universe currently trading above their 200-day simple moving average.",
     "It tells you whether a market rally is broad-based across hundreds of stocks or narrow (driven by only 2–3 mega-caps). High breadth (>60%) confirms healthy market participation."),

    ("200-Day SMA & Trend Tiers (Uptrend, Flat, Downtrend)",
     "The 200-day Simple Moving Average is the average closing price over the past year (~252 trading days). Stocks are stratified into Uptrend (>+20% 1yr change), Flat/Mild (-20% to +20%), and Downtrend (<-20%).",
     "Trend context matters. Uptrend stocks yield the highest return per trade (+1.33% net), Flat/Mild is the most statistically reliable (z=4.41), while Downtrend stocks showed no demonstrable edge over random entry."),

    ("ATR (Average True Range) & ATR Stops",
     "ATR measures the typical daily price volatility of a stock in rupees. A high-ATR stock moves heavily each day; a low-ATR stock moves gently.",
     "Instead of fixed percentage stops, the system uses ATR-based stops (4× ATR for swings). This prevents noisy stocks from prematurely stopping you out on normal daily fluctuations."),

    ("RVOL (Relative Volume)",
     "RVOL compares today's trading volume to the 20-day average volume (e.g., 2.5x RVOL means 250% of normal volume).",
     "Volume spikes confirm that institutional buyers or sellers are actively participating, giving conviction to breakouts or capitulation bottoms."),

    ("Momentum (60-day & 12-month)",
     "Momentum measures the percentage change in price over a trailing period (e.g., 60 days or 252 days).",
     "At long horizons (~1 month), momentum outperforms mean-reversion. Buying the top quartile basket of liquid momentum leaders beat the random control with z ≈ 9.5 out-of-sample."),

    ("52-Week High & Low Distance",
     "The percentage distance between a stock's current price and its highest or lowest price in the last 252 trading days.",
     "Used for informational context: stocks within 2% of 52-week highs show strong institutional sponsorship, while stocks near 52-week lows may be facing structural distress."),

    ("Mean-Reversion",
     "The financial theory that asset prices and historical returns eventually return to their long-term average over time.",
     "Short-term swings exploit overextended moves: when panic pushes a quality small-cap too low too fast, buyers step in to restore balance."),

    ("Participant Flows (FPI vs Retail)",
     "NSE's official breakdown of daily cash market net buying and selling in ₹ crores across Foreign Portfolio Investors (FPI), Mutual Funds (DII), and Retail traders.",
     "Shows who is providing liquidity and where institutional capital is flowing. Note: published with approximately one session reporting lag."),

    ("Market Cap Buckets (Large, Mid, Small)",
     "Large-cap = Top 100 stocks; Mid-cap = Next 150; Small-cap = Ranks 251–750.",
     "Different edges exist in different segments. Large-caps are hyper-efficient (RSI < 30 has 0% edge). Mid and Small caps have retail mispricings where statistical edge actually exists."),

    ("P&L Realized vs Unrealized",
     "Realized P&L is profit or loss locked in after closing a trade. Unrealized P&L is floating paper profit/loss on currently open positions.",
     "Your equity curve and strategy health are evaluated on realized trades, while open trades must be strictly monitored against exit rules."),

    ("Win Rate vs Risk/Reward",
     "Win rate is the percentage of closed trades that were profitable (e.g., 55%). Risk/Reward is the ratio of average win size to average loss size.",
     "A 50% win rate can be extremely profitable if your winners earn 2× to 3× what your losers cost. Discipline and risk control beat high win rates every time.")
]

for title, what, why in terms:
    st.markdown(f"""
    <div class="learn-card">
      <div class="learn-term-title"><span class="learn-badge">CONCEPT</span>{title}</div>
      <div class="learn-what"><b>What it is:</b> {what}</div>
      <div class="learn-why"><b>Why it matters:</b> {why}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<div class="news-group">⚖️ 3. The One Honest Lesson of This Project</div>', unsafe_allow_html=True)

st.markdown("""
<div class="learn-card">
  <p style="font-size:0.92rem;line-height:1.55;color:var(--text-primary);">
    <b>Every claim in this project is rigorously measured against reality.</b>
  </p>
  <p style="font-size:0.86rem;line-height:1.5;color:var(--text-secondary);">
    In financial markets, most "obvious" trading ideas (such as buying news headlines, trading moving average crossovers, or buying breakouts) fail completely when tested against a random-entry control with transaction costs deducted.
  </p>
  <p style="font-size:0.86rem;line-height:1.5;color:var(--text-secondary);">
    This codebase was built on three hard-learned statistical truths:
  </p>
  <ul style="font-size:0.84rem;color:var(--text-secondary);line-height:1.6;">
    <li><b>Overlapping trades inflate optimism:</b> When a stock stays oversold for 3 days, it isn't 3 separate winning trades; it's 1 episode. Standard errors must account for sample uniqueness.</li>
    <li><b>Day-clustering matters:</b> When the whole market crashes, 50 stocks trigger together. They share one market factor and are not 50 independent bets.</li>
    <li><b>Indian costs are significant:</b> STT, exchange fees, brokerage, GST, and slippage on small-caps eat ~0.40% to 0.90% round-trip. A strategy with +0.50% gross edge is break-even after real friction.</li>
  </ul>
  <p style="font-size:0.84rem;color:var(--accent-amber);margin-top:8px;">
    <b>Rule:</b> Never trust a trading number unless you know exactly how it was measured. When someone says "this clearly works," that is usually the exact moment data proves it wrong.
  </p>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="news-group">🛡️ 4. Risk Discipline &amp; Non-Advisory Notice</div>', unsafe_allow_html=True)

st.markdown("""
<div class="learn-card">
  <p style="font-size:0.88rem;line-height:1.5;color:var(--text-primary);">
    <b>1. Position Sizing Protects Capital</b><br>
    The system allows you to calculate position sizing based on risk per trade (e.g. 1–2% of capital), but it will never assume your net worth or force you into a size. Never risk more than you can afford to lose.
  </p>
  <p style="font-size:0.88rem;line-height:1.5;color:var(--text-primary);">
    <b>2. Stop-Losses Are Mandatory</b><br>
    Every validated setup comes with an ATR-based stop-loss. In quantitative trading, a stop is not an admission of defeat; it is the price of doing business to stay alive for the next 100 trades.
  </p>
  <p style="font-size:0.88rem;line-height:1.5;color:var(--text-primary);">
    <b>3. One Setup Is Never a Guarantee</b><br>
    Even a strategy with a 60% win rate will occasionally lose 5 times in a row. Edge is realized across a large sample of disciplined trades, not on any single ticker.
  </p>
  <hr style="border-color:var(--border-subtle);margin:12px 0;">
  <p style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0;">
    <b>⚠️ Non-Advisory Educational Disclaimer:</b> This suite is a personal quantitative research and decision-support tool. It is not SEBI-registered financial or investment advice. All analysis is for informational and educational purposes only.
  </p>
</div>
""", unsafe_allow_html=True)
