import os
import json
from tools import TOOL_DEFINITIONS, execute_tool
from openai import OpenAI
from dotenv import load_dotenv
from config import PROVIDERS, ACTIVE_PROVIDER

load_dotenv()

_provider = PROVIDERS[ACTIVE_PROVIDER]
_api_key = os.getenv(_provider["key_env"]) if _provider["key_env"] else "not-needed"

client = OpenAI(base_url=_provider["base_url"], api_key=_api_key)
MODEL_NAME_ACTIVE = _provider["model"]

SYSTEM_PROMPT = ("You are a trading assistant for Indian NSE stocks supporting TWO distinct, independently "
                  "backtested strategies. Determine which one the user means: "
                  "\n\nSHORT-TERM (4-6 days, default if unspecified): RSI < 30 + ATR-based stops (z-score 8.08). "
                  "Use get_snapshot_text_short, scan_watchlist_text_short. "
                  "\n\nLONG-TERM (~1 month): near 52-week high + confirmed uptrend, momentum-based (z-score 9.69). "
                  "Buy strength, not weakness - do NOT recommend oversold dips for this horizon. "
                  "Use get_snapshot_text_long, scan_watchlist_text_long, and check get_fundamentals_text since "
                  "fundamentals matter more here. "
                  "\n\nIf horizon is ambiguous, ASK the user rather than guessing. For calculate_position_size, "
                  "always pass the matching term ('short' or 'long'). Both share get_institutional_activity_text "
                  "and check_upcoming_results. Always mention stop loss and target clearly. Model signals are weak "
                  "in both cases. Never state with confidence what will happen. "
                  "Whenever you identify a candidate stock to present as a recommendation, ALWAYS use get_full_analysis "
                  "(not individual tools) to guarantee every check runs consistently every time. "
                  "If the user hasn't specified capital or risk %, use the defaults (₹50,000, 2% risk) automatically "
                  "to complete the position sizing calculation, and clearly state you used defaults so the user can correct them. "
                  "Never leave a recommendation unfinished just to wait for these numbers. "
                  "If calculate_position_size returns 'blocked': true, do NOT retry silently - explicitly show the user "
                  "the reason, ask if they want to proceed anyway, and only call the tool again with confirmed='true' "
                  "if they clearly say yes. Never auto-confirm on their behalf. "
                  "NEVER state specific facts about a company (what it makes, its history, its products) unless that exact "
                  "information came from a tool result in this conversation. If you don't have a verified business description "
                  "from get_fundamentals_text, say so explicitly rather than inferring or guessing from the company name or ticker. "
                  "This applies to news headlines too - only reference headlines exactly as returned by the tools, never paraphrase "
                  "or embellish specific claims within them. "
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
                  "For long-term scans, results are sorted with Small-cap first since backtesting showed the strongest edge "
                  "there (z=14.52), but Mid and Large-cap results are still valid and shown too (z=2.88 and z=2.28 respectively - "
                  "weaker but statistically real). When discussing a candidate, mention its cap segment and be honest that "
                  "Large-cap picks carry a meaningfully weaker proven edge than Small-cap ones, even though both are legitimate."
                  "If the user asks 'where should I invest' or gives                           capital/risk without naming a specific stock, "
                  "you MUST scan first (scan_watchlist_text_short or _long) to find a real candidate before calling "
                  "calculate_position_size - never call it with an empty or missing ticker.")

MAX_TOOL_ROUNDS = 12  # safety limit so it can't loop forever


def build_trimmed_history(full_history, max_turns=3):
    """Sends only the system prompt + last few user turns to the API - keeps requests under
    Qwen's small 8000 TPM free-tier limit. Full history is still saved/displayed in full;
    only what's actually sent to the model each call is trimmed."""
    system_msg = full_history[0]
    rest = full_history[1:]
    user_indices = [i for i, m in enumerate(rest) if m.get('role') == 'user']
    if len(user_indices) <= max_turns:
        return full_history
    start_idx = user_indices[-max_turns]
    return [system_msg] + rest[start_idx:]


class TradingAgent:
    def __init__(self):
        self.conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def reset(self):
        self.conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]
        print("Conversation reset!")

    def ask(self, user_question):
        self.conversation_history.append({"role": "user", "content": user_question})

        for round_num in range(MAX_TOOL_ROUNDS):
            trimmed_messages = build_trimmed_history(self.conversation_history)
            response = client.chat.completions.create(
                model=MODEL_NAME_ACTIVE,
                messages=trimmed_messages,
                tools=TOOL_DEFINITIONS,
                max_tokens=3000
            )
            response_message = response.choices[0].message

            if not response_message.tool_calls:
                self.conversation_history.append(response_message.model_dump(exclude_none=True))
                return response_message.content

            self.conversation_history.append(response_message.model_dump(exclude_none=True))
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                print(f"[Round {round_num + 1}: calling {function_name}({function_args})]")
                result_text = execute_tool(function_name, function_args)
                self.conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_text
                })

        return "I gathered a lot of data but couldn't finalize an answer within the step limit. Try asking a more specific question."