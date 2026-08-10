import os
import json
from tools import TOOL_DEFINITIONS, execute_tool
from openai import OpenAI
from dotenv import load_dotenv
from config import PROVIDERS, ACTIVE_PROVIDER, SHARED_RULES

load_dotenv()

_provider = PROVIDERS[ACTIVE_PROVIDER]
_api_key = os.getenv(_provider["key_env"]) if _provider["key_env"] else "not-needed"

client = OpenAI(base_url=_provider["base_url"], api_key=_api_key)
MODEL_NAME_ACTIVE = _provider["model"]

SYSTEM_PROMPT = SHARED_RULES

MAX_TOOL_ROUNDS = 12  # safety limit so it can't loop forever

# How many recent user turns get sent to the model. This was 3, sized for Qwen's 8000 TPM
# free-tier limit on Groq. That provider is no longer used - Gemini Flash Lite has orders of
# magnitude more headroom - and a 3-turn window actively hurt multi-turn conversations, where
# the user builds context across several short messages (especially from Telegram). Lower it
# again only if you move to a genuinely token-constrained provider.
MAX_HISTORY_TURNS = 12


def build_trimmed_history(full_history, max_turns=MAX_HISTORY_TURNS):
    """Sends the system prompt + the last N user turns to the API, so a long session cannot grow
    the request without bound. Full history is still saved and displayed; only what goes to the
    model each call is trimmed."""
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