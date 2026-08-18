from typing import Optional
import json
from mcp.server.fastmcp import FastMCP
from tools import (
    scan_watchlist_text_breakout, scan_watchlist_text_short, scan_watchlist_text_long, scan_watchlist_text_long_momentum, get_full_analysis,
    calculate_position_size, get_exit_check_text, get_similar_past_trades,
    record_trade_entry, record_trade_exit, get_significant_announcements_scan,
    get_upcoming_catalysts_scan, get_market_regime_text, get_open_positions,
    get_fundamentals_text, get_institutional_activity_text, check_upcoming_results,
    get_recent_announcements_text, get_announcement_reaction_text, get_catalyst_scan_text,
    get_snapshot_text_short, get_snapshot_text_long, get_snapshot_text_breakout, get_live_price_text,
    evaluate_user_trade,
)
from trade_journal import get_strategy_health
from config import SHARED_RULES, DEFAULT_CAPITAL, DEFAULT_RISK_PCT

mcp = FastMCP("NSE Trading Assistant", instructions=SHARED_RULES)


@mcp.tool()
def scan_short_term(rsi_threshold: int = 30, limit: int = 30) -> str:
    """Scans the NSE watchlist for 4-6 day swing setups using the backtested RSI<30 strategy (z-score 8.08, day-clustered Small z 2.74). Automatically excludes large-cap stocks, which showed no reliable edge."""
    return scan_watchlist_text_short(limit, rsi_threshold)


@mcp.tool()
def scan_breakout_swings(limit: int = 10) -> str:
    """EXPERIMENTAL / UNVALIDATED scan for Momentum Breakout setups (VCP / High Tight Base) in Mid/Small caps. 5-year backtest failed to demonstrate edge (z_paired < 2.0 across all cap tiers). Informational only, not a validated buy signal."""
    return scan_watchlist_text_breakout(limit)


@mcp.tool()
def scan_long_term(limit: int = 15) -> str:
    """Long-term (~1 month) MOMENTUM scan: ranks the liquid Mid/Small universe by 12-month momentum and surfaces the VALIDATED top quartile as a diversified BASKET (day-clustered z ~9.5 out-of-sample, net ~+1.5%/trade). Buy strength. WARNING: momentum crashes periodically - hold several names, rebalance ~monthly, size small; not a single pick."""
    return scan_watchlist_text_long_momentum(limit)


@mcp.tool()
def full_analysis(ticker: str, term: str = "short") -> str:
    """Runs the complete forced checklist for one NSE stock: market regime, technical snapshot, fundamentals, institutional activity, upcoming results, and recent corporate announcements. term can be 'short', 'long', or 'breakout'."""
    return get_full_analysis(ticker, term)


@mcp.tool()
def evaluate_my_trade(ticker: str, entry_price: Optional[float] = None,
                      shares: Optional[float] = None) -> str:
    """Use whenever the user names a stock THEY chose or already bought, rather than one the scan surfaced - e.g. 'I bought 5 shares of XYZ at 400', 'thoughts on ABC?', 'is RELIANCE a good buy?'. Works for any NSE ticker, including ones outside the 748-stock universe. Pass entry_price and shares whenever the user mentions them; stop, targets and P&L are then computed against THEIR entry. States explicitly whether the backtested edge applies - when it says no edge applies, relay that plainly and do not quote strategy statistics as if they covered the trade."""
    return evaluate_user_trade(ticker, entry_price, shares)


@mcp.tool()
def position_size(ticker: str, total_capital: float = DEFAULT_CAPITAL, risk_pct: float = DEFAULT_RISK_PCT, term: str = "short", confirmed: bool = False) -> str:
    """Calculates exact share count for a trade given capital and risk %. Blocks and requires explicit confirmed=true if risk_pct exceeds 2% or the stock shows a parabolic move flag."""
    return json.dumps(calculate_position_size(ticker, total_capital, risk_pct, term, confirmed), indent=2)


@mcp.tool()
def check_exits() -> str:
    """Checks all currently open logged positions against the validated stop-loss/target/time-exit rule, plus VIX and momentum-reversal context."""
    return get_exit_check_text()


@mcp.tool()
def past_trades(term: str, validated_setup: Optional[bool] = None) -> str:
    """Retrieves the user's own real past closed trades matching a profile, with honest win rate and sample-size caveats. term must be 'short' or 'long'."""
    return get_similar_past_trades(term, validated_setup)


@mcp.tool()
def log_entry(ticker: str, term: str, shares: int, capital_used: float, risk_pct: float, entry_price: Optional[float] = None) -> str:
    """Logs a real trade entry, freezing the current signal snapshot permanently. Call only when the user says they've actually entered a real position."""
    return record_trade_entry(ticker, term, shares, capital_used, risk_pct, entry_price)


@mcp.tool()
def log_exit(ticker: str, exit_price: float) -> str:
    """Logs a real trade exit and computes the actual return. Call only when the user says they've actually sold a position."""
    return record_trade_exit(ticker, exit_price)


@mcp.tool()
def strategy_health(term: str = "short") -> str:
    """Compares the user's real closed trades against the backtested expectation and runs a CUSUM decay alarm. Use when asked how the strategy is performing or whether it still works."""
    return get_strategy_health(term)


@mcp.tool()
def open_positions() -> str:
    """Lists all currently open logged trades."""
    return get_open_positions()


@mcp.tool()
def significant_announcements() -> str:
    """Scans the whole watchlist for significant recent corporate announcements (management changes, M&A, takeover disclosures) from the last 5 days. Informational only, not a validated signal."""
    return get_significant_announcements_scan()


@mcp.tool()
def upcoming_catalysts(days_ahead: int = 7) -> str:
    """Scans the whole watchlist for stocks with results or board meetings coming in the next N days, with sector momentum context."""
    return get_upcoming_catalysts_scan(days_ahead)


@mcp.tool()
def market_regime() -> str:
    """Gets overall market breadth, Nifty trend, and India VIX context."""
    return get_market_regime_text()


@mcp.tool()
def snapshot(ticker: str, term: str = "short") -> str:
    """Gets current price, RSI, stop-loss, target, and technical snapshot for ONE stock. Use this whenever the user asks for a current price or quick technical read."""
    return get_snapshot_text_short(ticker) if term == "short" else get_snapshot_text_long(ticker)


@mcp.tool()
def live_price(ticker: str) -> str:
    """Gets the exact current live market price for ONE stock, bypassing any cache lag. Use when the user specifically wants just the current price, nothing else."""
    return get_live_price_text(ticker)


@mcp.tool()
def fundamentals(ticker: str) -> str:
    """Gets P/E, growth, margins, ROE, debt and a verified business description for ONE stock. Especially relevant for long-term picks."""
    return get_fundamentals_text(ticker)


@mcp.tool()
def institutional_activity(ticker: str) -> str:
    """Gets 30-day delivery % trend and recent bulk/block deals for ONE stock - institutional footprint context."""
    return get_institutional_activity_text(ticker)


@mcp.tool()
def upcoming_results(ticker: str) -> str:
    """Checks whether ONE stock has upcoming earnings/board meetings scheduled."""
    return check_upcoming_results(ticker)


@mcp.tool()
def recent_announcements(ticker: str) -> str:
    """Gets all recent corporate announcements for ONE stock, with the real NSE filing detail text."""
    return get_recent_announcements_text(ticker)


@mcp.tool()
def announcement_reaction(ticker: str) -> str:
    """Gets the real observed price move since ONE stock's most recent corporate announcement."""
    return get_announcement_reaction_text(ticker)


@mcp.tool()
def catalyst_scan(limit: int = 20) -> str:
    """UNVALIDATED: scans the whole watchlist for unusual volume spikes, informational only - not a backtested edge."""
    return get_catalyst_scan_text(limit)


if __name__ == "__main__":
    mcp.run()  # stdio transport - local only, connects to Claude Desktop
