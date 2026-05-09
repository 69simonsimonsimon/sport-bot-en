"""
News Scraper — Sport Bot EN
============================
Fetches sports news via RSS feeds for Soccer, NBA, NFL.
Tracks used articles to avoid duplicates.
"""

import json
import logging
import os
import random
import re
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import feedparser
import requests

logger = logging.getLogger("syncin")

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(ROOT / "output")))

USED_ARTICLES_FILE = OUTPUT_DIR / "used_articles.json"
MAX_USED = 500

# RSS Feeds — English sports news
FEEDS = {
    "soccer": [
        "https://news.google.com/rss/search?q=soccer+premier+league&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=soccer+champions+league&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=soccer+transfer+news&hl=en&gl=US&ceid=US:en",
    ],
    "nba": [
        "https://news.google.com/rss/search?q=NBA+basketball&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=NBA+highlights&hl=en&gl=US&ceid=US:en",
    ],
    "nfl": [
        "https://news.google.com/rss/search?q=NFL+football&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=NFL+touchdown+highlights&hl=en&gl=US&ceid=US:en",
    ],
}

# Sport weights for random selection (soccer/nba/nfl)
SPORT_WEIGHTS = {"soccer": 40, "nba": 35, "nfl": 25}

# Trend cache: refreshed every 60 minutes
_trend_cache = {"weights": None, "ts": 0}


def _get_trending_weights() -> dict:
    """
    Returns sport weights boosted by Google Trends and recent article counts.
    Falls back to SPORT_WEIGHTS on any error. Caches result for 60 minutes.
    """
    global _trend_cache
    now = time.time()
    if _trend_cache["weights"] is not None and now - _trend_cache["ts"] < 3600:
        return _trend_cache["weights"]

    weights = dict(SPORT_WEIGHTS)

    try:
        # ── Step 1: Google Trends daily RSS boost ──────────────────────────
        trends_url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
        req = urllib.request.Request(trends_url, headers={"User-Agent": "Mozilla/5.0 (compatible; SportBot/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            trends_xml = resp.read().decode("utf-8", errors="replace").lower()

        soccer_keywords = ["soccer", "football", "premier league", "champions league"]
        nba_keywords = ["nba", "basketball"]
        nfl_keywords = ["nfl"]

        for kw in soccer_keywords:
            if kw in trends_xml:
                weights["soccer"] = weights.get("soccer", 0) + 15
                logger.info(f"[news] Trends boost: soccer +15 ({kw})")
                break
        for kw in nba_keywords:
            if kw in trends_xml:
                weights["nba"] = weights.get("nba", 0) + 15
                logger.info(f"[news] Trends boost: nba +15 ({kw})")
                break
        for kw in nfl_keywords:
            if kw in trends_xml:
                weights["nfl"] = weights.get("nfl", 0) + 15
                logger.info(f"[news] Trends boost: nfl +15 ({kw})")
                break

    except Exception as e:
        logger.warning(f"[news] Trends fetch failed: {e}")

    try:
        # ── Step 2: Recent article count bonus (up to +10 per sport) ───────
        cutoff = datetime.utcnow() - timedelta(hours=48)
        for sport, feed_list in FEEDS.items():
            if not feed_list:
                continue
            first_url = feed_list[0]
            try:
                headers = {"User-Agent": "Mozilla/5.0 (compatible; SportBot/1.0)"}
                resp = requests.get(first_url, headers=headers, timeout=8)
                feed = feedparser.parse(resp.content)
                recent_count = 0
                for entry in feed.entries:
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    if published:
                        pub_dt = datetime(*published[:6])
                        if pub_dt >= cutoff:
                            recent_count += 1
                bonus = min(recent_count, 10)
                if bonus > 0:
                    weights[sport] = weights.get(sport, 0) + bonus
                    logger.info(f"[news] Recent-articles bonus: {sport} +{bonus} ({recent_count} articles < 48h)")
            except Exception as e:
                logger.debug(f"[news] Recent-articles check failed for {sport}: {e}")

    except Exception as e:
        logger.warning(f"[news] Recent-articles bonus failed: {e}")

    _trend_cache["weights"] = weights
    _trend_cache["ts"] = now
    return weights

# "Spicy" keywords that increase article score for rage-bait potential
SPICY_KEYWORDS = [
    "fired", "trade", "injury", "controversy", "criticism", "benched", "released",
    "slammed", "blasted", "furious", "drama", "feud", "clash", "crisis",
    "demand", "quit", "suspend", "ban", "fine", "arrest", "scandal",
    "betrayed", "disrespect", "overpaid", "flop", "worst",
    "eliminated", "upset", "shocking", "stunner", "collapse",
]


def _load_used() -> set:
    try:
        return set(json.loads(USED_ARTICLES_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_used(used: set):
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
    lst = list(used)[-MAX_USED:]
    USED_ARTICLES_FILE.write_text(json.dumps(lst, ensure_ascii=False), encoding="utf-8")


def _score_article(title: str, summary: str) -> int:
    text = (title + " " + summary).lower()
    score = 0
    for kw in SPICY_KEYWORDS:
        if kw in text:
            score += 1
    return score


def _fetch_feed(url: str, timeout: int = 10) -> list:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SportBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=timeout)
        feed = feedparser.parse(resp.content)
        return feed.entries if feed.entries else []
    except Exception as e:
        logger.warning(f"[news] Feed-Fehler {url}: {e}")
        return []


def _fetch_article_text(url: str, max_chars: int = 800) -> str:
    """
    Fetches the actual article body text from a URL.
    Used when the RSS summary is too short (< 120 chars).
    Returns empty string on failure.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        text = resp.text
        # Remove scripts, styles, nav, etc.
        text = re.sub(r"<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>",
                      " ", text, flags=re.DOTALL | re.IGNORECASE)
        # Remove all HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 80:
            return ""
        return text[:max_chars]
    except Exception as e:
        logger.debug(f"[news] Article fetch failed ({url[:60]}): {e}")
        return ""


def fetch_news(sport: str = None) -> dict:
    """
    Fetches a suitable sports article.
    sport: 'soccer', 'nba', 'nfl' or None (random by weight)
    Returns: {title, summary, link, sport}
    """
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

    if not sport:
        w = _get_trending_weights()
        sports = list(w.keys())
        weights = list(w.values())
        sport = random.choices(sports, weights=weights, k=1)[0]
        logger.info(f"[news] Dynamic weights: {w} → picked {sport}")

    used = _load_used()
    feed_urls = FEEDS.get(sport, FEEDS["soccer"])
    random.shuffle(feed_urls)

    def _build_candidate(e: dict, sport: str) -> dict | None:
        link = e.get("link", "")
        title = e.get("title", "").strip()
        summary = e.get("summary", e.get("description", "")).strip()
        summary = re.sub(r"<[^>]+>", " ", summary).strip()
        summary = re.sub(r"\s+", " ", summary)[:500]
        if not title or len(title) < 10:
            return None
        # Fetch full article text if summary is too short
        if len(summary) < 120 and link:
            fetched = _fetch_article_text(link)
            if fetched:
                logger.debug(f"[news] Short summary ({len(summary)}ch) → fetched article ({len(fetched)}ch)")
                summary = fetched
        # Skip articles that are still empty after fetch
        if len(summary.strip()) < 50:
            logger.debug(f"[news] Skipping empty article: '{title[:50]}'")
            return None
        score = _score_article(title, summary)
        return {"title": title, "summary": summary, "link": link, "sport": sport, "score": score}

    candidates = []
    for url in feed_urls:
        entries = _fetch_feed(url)
        for e in entries:
            link = e.get("link", "")
            if link in used:
                continue
            candidate = _build_candidate(e, sport)
            if candidate:
                candidates.append(candidate)

    if not candidates:
        logger.warning(f"[news] No new articles for {sport} — retrying with fallback")
        # Fallback: ignore used list
        for url in feed_urls:
            entries = _fetch_feed(url)
            for e in entries:
                candidate = _build_candidate(e, sport)
                if candidate:
                    candidates.append(candidate)

    if not candidates:
        raise RuntimeError(f"No articles found for sport: {sport}")

    # Sort: top scorers first (50%), rest random
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:max(3, len(candidates) // 3)]
    article = random.choice(top)

    used.add(article["link"])
    _save_used(used)

    logger.info(f"[news] Selected: {article['title'][:70]} (score={article['score']})")
    return article
