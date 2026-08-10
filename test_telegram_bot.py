"""Offline checks for the Telegram front-end (no network, no bot token needed)."""
import notify
import telegram_bot as tb


class FakeAgent:
    def __init__(self):
        self.asked = []

    def ask(self, q):
        self.asked.append(q)
        return "AGENT:" + q

    def reset(self):
        self.asked.append("RESET")


def _capture():
    sent = []
    notify._post = lambda method, **p: sent.append(p.get('text', '')) or {}
    return sent


def test_long_messages_split_without_losing_lines():
    """Scan output routinely exceeds Telegram's 4096 cap. Dropping or truncating a line here
    could hide a stop-loss level, so every line must survive the split."""
    sent = _capture()
    big = "\n".join(f"line {i} " + "x" * 80 for i in range(200))
    tb.send(1, big)
    assert len(sent) > 1, "should have split"
    assert all(len(c) <= tb.TG_LIMIT for c in sent)
    assert "\n".join(sent).count("line ") == big.count("line ")


def test_unsplittable_text_still_fits():
    sent = _capture()
    tb.send(1, "y" * (tb.TG_LIMIT * 2 + 7))   # no newline to split on
    assert all(len(c) <= tb.TG_LIMIT for c in sent)
    assert sum(len(c) for c in sent) == tb.TG_LIMIT * 2 + 7


def test_empty_response_is_not_dropped():
    sent = _capture()
    tb.send(1, "")
    assert sent and sent[0], "Telegram rejects empty text - must send a placeholder"


def test_shortcuts_bypass_the_model():
    """The figures checked most often must not pass through an LLM that could paraphrase them,
    and should not cost an API call."""
    a = FakeAgent()
    for cmd in ("/exits", "/positions", "/scan"):
        tb.handle(a, 1, cmd)
    assert a.asked == [], f"shortcut leaked to the model: {a.asked}"


def test_free_text_reaches_the_agent():
    a = FakeAgent()
    assert tb.handle(a, 1, "thoughts on IRFC at 130?") == "AGENT:thoughts on IRFC at 130?"
    assert tb.handle(a, 1, "/reset") == "Conversation memory cleared."
    assert a.asked == ["thoughts on IRFC at 130?", "RESET"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("telegram bot: OK")
