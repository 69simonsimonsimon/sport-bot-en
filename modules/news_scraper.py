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


def fetch_news(sport: str = None) -> dict:
    """
    Fetches a suitable sports article.
    sport: 'soccer', 'nba', 'nfl' or None (random by weight)
    Returns: {title, summary, link, sport}
    """
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

    if not sport:
        sports = list(SPORT_WEIGHTS.keys())
        weights = [SPORT_WEIGHTS[s] for s in sports]
        sport = random.choices(sports, weights=weights, k=1)[0]

    used = _load_used()
    feed_urls = FEEDS.get(sport, FEEDS["soccer"])
    random.shuffle(feed_urls)

    candidates = []
    for url in feed_urls:
        entries = _fetch_feed(url)
        for e in entries:
            link = e.get("link", "")
            if link in used:
                continue
            title = e.get("title", "").strip()
            summary = e.get("summary", e.get("description", "")).strip()
            # Strip HTML tags
            summary = re.sub(r"<[^>]+>", " ", summary).strip()
            summary = re.sub(r"\s+", " ", summary)[:500]
            if not title or len(title) < 10:
                continue
            score = _score_article(title, summary)
            candidates.append({"title": title, "summary": summary, "link": link,
                                "sport": sport, "score": score})

    if not candidates:
        logger.warning(f"[news] No new articles for {sport} — retrying with fallback")
        # Fallback: ignore used list
        for url in feed_urls:
            entries = _fetch_feed(url)
            for e in entries:
                title = e.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", " ",
                                  e.get("summary", e.get("description", ""))).strip()
                summary = re.sub(r"\s+", " ", summary)[:500]
                if title and len(title) >= 10:
                    candidates.append({"title": title, "summary": summary,
                                       "link": e.get("link", ""), "sport": sport, "score": 0})

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
