"""No-network checks for the isolated news feed. Run: python test_news_feed.py"""
import os
from datetime import datetime, timezone, timedelta
from time import gmtime, mktime

import news_feed as nf

IST = timezone(timedelta(hours=5, minutes=30))


def test_dedupe_drops_dupes_empties_and_old():
    fresh = gmtime()  # now
    raw = [
        {"title": "Nifty jumps 2%", "pub": fresh},
        {"title": "nifty jumps 2%", "pub": fresh},   # case-insensitive dup
        {"title": "", "pub": fresh},                 # empty
        {"title": "Old", "pub": gmtime(0)},          # 1970 -> outside window
        {"title": "Undated", "pub": None},           # kept
    ]
    assert [d["title"] for d in nf._dedupe_today(raw)] == ["Nifty jumps 2%", "Undated"]


def test_curate_splits_top_and_more_without_loss():
    items = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
    top, more = nf._curate(items, [{"i": 2, "importance": "high", "category": "Global", "why": "w"},
                                   {"i": 0, "importance": "low", "category": "bogus"}])
    assert [t["title"] for t in top] == ["C", "A"]     # selected, in LLM order
    assert [m["title"] for m in more] == ["B"]         # unselected -> collapsed tail
    assert top[0]["rank"] == 1 and top[0]["why"] == "w"
    assert top[1]["category"] == "Other"               # off-list category normalised
    assert len(top) + len(more) == 3                   # nothing lost or invented
    # bad/dup indices ignored, everything falls to `more`, no crash
    t2, m2 = nf._curate(items, [{"i": 99}, {"i": "x"}, {}, {"i": 1}, {"i": 1}])
    assert len(t2) == 1 and len(m2) == 2


def test_fallback_shows_all_untagged():
    items = [{"title": "A"}, {"title": "B"}]
    top, more = nf._fallback(items)
    assert len(top) == 2 and more == []
    assert top[0]["importance"] is None and top[0]["rank"] == 1


def test_extract_json_handles_fences_and_chatter():
    assert nf._extract_json('```json\n[{"i":1}]\n```') == [{"i": 1}]
    assert nf._extract_json('ok [{"i":0,"importance":"high"}] done') == [{"i": 0, "importance": "high"}]


def test_cache_round_trip():
    nf._save_cache({"date": "test", "items": [{"title": "x"}]})
    try:
        assert nf._load_cache()["date"] == "test"
    finally:
        os.remove(nf.CACHE_FILE)
    assert nf._load_cache() is None  # missing file -> None, not crash


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all news_feed tests passed")
