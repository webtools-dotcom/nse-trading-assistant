"""Home-page general-market news feed. ISOLATED from the trading path.

Nothing here is a trade signal, nothing is backtested, and the trading agent / backtests
import none of it. Flow: free Indian-market RSS -> the isolated news LLM ranks headlines
biggest->normal -> result cached once per day (same spirit as the VIX cache). If no news
key is set or the LLM call fails, it degrades gracefully to recency order.
"""

import os
import re
import json
import time
from datetime import datetime, timezone, timedelta

import feedparser
from openai import OpenAI
from dotenv import load_dotenv

from config import NEWS_PROVIDERS, ACTIVE_NEWS_PROVIDER, BASE_DIR, WATCHLIST

load_dotenv()  # Streamlit does not load .env on its own; the *_NEWS_API keys live there.

IST = timezone(timedelta(hours=5, minutes=30))
CACHE_FILE = os.path.join(BASE_DIR, "news_feed_cache.json")
# Freshness window: within this many minutes the cached curation is reused (no fetch, no API);
# past it the next load re-fetches + re-ranks, so intraday breaking news comes through without
# a manual refresh. ~1 API call per this interval, not per page load.
CACHE_TTL_MIN = 30

# Fixed display order for the curated categories. The LLM must tag each kept item with one
# of these exact strings; anything it returns off-list falls through to "Other".
CATEGORIES = ["Markets & Indices", "Macro & Policy", "Corporate & Earnings",
              "Global", "Commodities & FX", "Other"]

# Watchlist name-matching: match distinctive ticker roots (>=4 chars, word-boundary) against
# headline text, purely local, no LLM cost. ponytail: substring on ticker root, a short/common
# root could false-positive; length gate + word boundary keeps it acceptable for a display flag.
_WATCH_ROOTS = sorted({t.split(".")[0].upper() for t in WATCHLIST if len(t.split(".")[0]) >= 4})
_WATCH_RE = re.compile(r"\b(" + "|".join(re.escape(r) for r in _WATCH_ROOTS) + r")\b") \
    if _WATCH_ROOTS else None


def _watch_hit(title):
    if not _WATCH_RE:
        return None
    m = _WATCH_RE.search((title or "").upper())
    return m.group(1) if m else None

# Free, no-key Indian market RSS. Add/remove freely - a dead feed is skipped, not fatal.
RSS_FEEDS = [
    ("Moneycontrol Markets",     "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("Moneycontrol Business",    "https://www.moneycontrol.com/rss/business.xml"),
    ("Economic Times Markets",   "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Livemint Markets",         "https://www.livemint.com/rss/markets"),
    ("Business Standard Markets", "https://www.business-standard.com/rss/markets-106.rss"),
]

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text):
    return _TAG_RE.sub("", text or "").strip()


def fetch_headlines(max_per_feed=25, cap=60):
    """Recent headlines across the RSS sources, de-duped and sorted NEWEST-FIRST (network).
    Capped to the `cap` most-recent items so the LLM sees the latest news, not a backlog."""
    entries = []
    for source, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        for e in feed.entries[:max_per_feed]:
            entries.append({
                "title": _clean(e.get("title")),
                "source": source,
                "link": e.get("link", ""),
                "summary": _clean(e.get("summary"))[:280],
                "pub": e.get("published_parsed") or e.get("updated_parsed"),
            })
    now_ts = datetime.now(timezone.utc).timestamp()
    # undated RSS items are usually the freshest, so treat them as "now" for sorting
    entries.sort(key=lambda e: datetime(*e["pub"][:6], tzinfo=timezone.utc).timestamp()
                 if e.get("pub") else now_ts, reverse=True)
    return _dedupe_today(entries)[:cap]


def _dedupe_today(entries, now=None, max_age_hours=36):
    """Pure: drop empties, dupes (by lowercased title), and items older than max_age_hours.
    A rolling window (not a strict calendar day) so just-past-midnight still shows the
    previous evening's news. Undated items are kept - some feeds omit dates. `entries` items
    may carry a `pub` struct_time (UTC) which is dropped from the output."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    seen, out = set(), []
    for e in entries:
        title = (e.get("title") or "").strip()
        key = title.lower()
        if not title or key in seen:
            continue
        pub = e.get("pub")
        if pub:
            when = datetime(*pub[:6], tzinfo=timezone.utc)
            if when < cutoff:
                continue
        seen.add(key)
        out.append({"title": title, "source": e.get("source", ""),
                    "link": e.get("link", ""), "summary": e.get("summary", "")})
    return out


def _client():
    p = NEWS_PROVIDERS[ACTIVE_NEWS_PROVIDER]
    key = os.getenv(p["key_env"]) if p.get("key_env") else "local"
    if not key:
        return None, p
    return OpenAI(base_url=p["base_url"], api_key=key), p


def _extract_json(text):
    """Pull the first JSON array out of an LLM reply (may be fenced or chatty)."""
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array in reply")
    return json.loads(text[start:end + 1])


def _curate(items, selection):
    """Pure: split `items` into (top, more) using the LLM's `selection`.

    `selection` = list of {"i": idx, "importance": high|medium|low, "category": str,
    "why": str}. `top` = the selected items, in the LLM's order, enriched with those fields
    plus a `watch` flag; `more` = every item the LLM did NOT select (the dropped noise), in
    original order. Invalid/duplicate indices are ignored. top + more together still contain
    exactly the input items - nothing is dropped or invented, only sorted into shown/collapsed.
    """
    top, used = [], set()
    for o in selection:
        i = o.get("i")
        if not (isinstance(i, int) and 0 <= i < len(items) and i not in used):
            continue
        used.add(i)
        cat = o.get("category")
        top.append({**items[i],
                    "importance": o.get("importance"),
                    "category": cat if cat in CATEGORIES else "Other",
                    "why": (o.get("why") or "").strip(),
                    "watch": _watch_hit(items[i]["title"])})
    more = [{**it, "watch": _watch_hit(it["title"])}
            for i, it in enumerate(items) if i not in used]
    for n, it in enumerate(top, 1):
        it["rank"] = n
    return top, more


def _fallback(items):
    """No key / call failed: show everything in recency order, untagged."""
    top = [{**it, "importance": None, "category": "Other", "why": "",
            "watch": _watch_hit(it["title"]), "rank": n}
           for n, it in enumerate(items, 1)]
    return top, []


def curate_headlines(items, retries=3):
    """Curate today's headlines for an Indian equity investor via the isolated news LLM.
    Returns (top, more, ok): top = the newsworthy, tagged and ordered; more = dropped noise;
    ok = True if the LLM actually ran. Retries transient API errors (e.g. Gemini 503) a few
    times, then falls back to recency order (everything in `top`, untagged, ok=False)."""
    client, p = _client()
    if client is None or not items:
        top, more = _fallback(items)
        return top, more, False
    numbered = "\n".join(f"{i}. {it['title']}" for i, it in enumerate(items))
    prompt = (
        "You are the editor of a serious markets desk for an Indian equity investor. Below "
        "are the latest raw headlines from several feeds, numbered and already ordered "
        "NEWEST-FIRST. Most are noise: promotional blurbs, minor micro-cap items, generic "
        "opinion, listicles, repetitive coverage of the same story. Your job is to CURATE, "
        "not list everything.\n\n"
        "Return ONLY a JSON array of the genuinely market-relevant headlines, ordered from "
        "the single BIGGEST / most market-moving story down to the least. Each element: "
        "{\"i\": <number>, \"importance\": \"high\"|\"medium\"|\"low\", \"category\": one of "
        f"{CATEGORIES[:-1]}, \"why\": \"<max 12 words on why it matters to a trader>\"}}.\n\n"
        "Rules: (1) DROP routine/promotional/duplicate/micro items entirely - simply omit "
        "their numbers. (2) When several headlines cover the SAME story, keep only the single "
        "best one. (3) Reserve \"high\" for things that actually move the index or a large "
        "sector: RBI/policy, inflation/GDP prints, big-cap results & M&A, regulatory shocks, "
        "sharp global moves. (4) FAVOUR THE LATEST / BREAKING developments - when two stories "
        "are similarly important, rank the more recent one higher; a fresh market-moving item "
        "should lead. (5) Aim for roughly 12-20 items, fewer on a quiet day. Better to drop a "
        "marginal item than to include filler.\n\n" + numbered
    )
    # Try the primary model, then the provider's fallback_model (e.g. flash -> flash-lite),
    # retrying transient errors on each. Only a total failure drops to the recency fallback.
    models = [p["model"]] + ([p["fallback_model"]] if p.get("fallback_model") else [])
    for model in models:
        for attempt in range(retries):
            try:
                resp = client.chat.completions.create(
                    model=model, temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                top, more = _curate(items, _extract_json(resp.choices[0].message.content))
                return top, more, True
            except Exception:
                if attempt < retries - 1:
                    time.sleep(2)
    top, more = _fallback(items)
    return top, more, False


def _load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save_cache(payload):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _is_fresh(cached):
    """True if the cache is still within its freshness window. A successfully-curated cache
    lasts CACHE_TTL_MIN; a fallback (LLM was down) lasts only 5 min so it retries soon instead
    of serving the raw firehose for the full window."""
    try:
        gen = datetime.fromisoformat(cached["generated_at"])
        ttl = CACHE_TTL_MIN if cached.get("curated") else 5
        return (datetime.now(IST) - gen) < timedelta(minutes=ttl)
    except (KeyError, ValueError, TypeError):
        return False


def get_ranked_news(force=False):
    """Curated news, cached with a CACHE_TTL_MIN freshness window. Returns the payload dict:
    date, provider, generated_at, top (curated & tagged), more (dropped noise). Within the
    window the cache is reused (no fetch, no API); past it, or with force=True (Refresh button),
    it re-fetches + re-ranks. Never raises - returns empty lists on failure so the page renders."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if not force:
        cached = _load_cache()
        if cached and "top" in cached and _is_fresh(cached):
            return cached
    top, more, ok = curate_headlines(fetch_headlines())
    payload = {"date": today, "provider": ACTIVE_NEWS_PROVIDER, "curated": ok,
               "generated_at": datetime.now(IST).isoformat(), "top": top, "more": more}
    try:
        _save_cache(payload)
    except OSError:
        pass
    return payload


if __name__ == "__main__":
    # Self-check: pure logic only, no network. Verifies dedup, date filter, rank mapping,
    # JSON extraction and cache round-trip - the parts that break silently.
    from time import gmtime

    fresh = gmtime()  # now, UTC struct_time
    raw = [
        {"title": "Nifty jumps 2%", "pub": fresh, "source": "A", "link": "x", "summary": "s"},
        {"title": "nifty jumps 2%", "pub": fresh},               # dup (case-insensitive)
        {"title": "", "pub": fresh},                             # empty -> dropped
        {"title": "Old news", "pub": gmtime(0)},                 # 1970 -> dropped
        {"title": "Undated blurb", "pub": None},                 # kept
    ]
    deduped = _dedupe_today(raw)
    titles = [d["title"] for d in deduped]
    assert titles == ["Nifty jumps 2%", "Undated blurb"], titles

    items = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
    top, more = _curate(items, [{"i": 2, "importance": "high", "category": "Global", "why": "x"},
                                {"i": 0, "importance": "low", "category": "bogus"}])
    assert [t["title"] for t in top] == ["C", "A"]                      # ordered, B dropped
    assert [m["title"] for m in more] == ["B"]                          # B -> collapsed tail
    assert top[0]["rank"] == 1 and top[1]["category"] == "Other"        # off-list cat -> Other
    assert len(top) + len(more) == 3                                    # nothing lost/invented

    assert _extract_json('```json\n[{"i":1}]\n```') == [{"i": 1}]
    assert _extract_json('sure! [{"i":0,"importance":"high"}] done') == [{"i": 0, "importance": "high"}]

    _save_cache({"date": "test", "items": [{"title": "x"}]})
    assert _load_cache()["date"] == "test"
    os.remove(CACHE_FILE)

    print("news_feed self-check OK")
