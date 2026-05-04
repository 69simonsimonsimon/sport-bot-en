"""
Clip Fetcher — Sport Bot EN
============================
3-phase search:
  Phase 1 — YouTube, player-specific (yt-dlp ytsearch5)
  Phase 2 — YouTube generic + Dailymotion API (no key needed)
  Phase 3 — Pexels Stock Video API (PEXELS_API_KEY in Railway)
No gradient fallback — better to abort job than post garbage.
"""

import json
import logging
import os
import random
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger("syncin")

# ── YouTube Cookie Support ────────────────────────────────────────────────────
_cookie_file: str | None = None

def _get_cookie_file() -> str | None:
    """Write YOUTUBE_COOKIES env var to a temp file once, return path."""
    global _cookie_file
    if _cookie_file and Path(_cookie_file).exists():
        return _cookie_file
    cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if not cookies:
        return None
    try:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="yt_cookies_", delete=False
        )
        f.write(cookies)
        f.close()
        _cookie_file = f.name
        logger.info(f"[clip] Cookie file written: {_cookie_file}")
    except Exception as e:
        logger.warning(f"[clip] Cookie file error: {e}")
        return None
    return _cookie_file

# ── Query Templates ───────────────────────────────────────────────────────────

# Phase 1 — Player-specific, low copyright risk
# Press conferences, training, interviews = club-owned content, rarely claimed
PLAYER_QUERIES = {
    "soccer": [
        "{player} soccer press conference",
        "{player} football training session",
        "{player} soccer interview 2025",
        "{player} football training ground",
        "{player} football media conference",
        "{player} soccer pre-match press conference",
        "{player} football post-match interview",
        "{player} soccer training footage",
    ],
    "nba": [
        "{player} NBA press conference",
        "{player} basketball postgame interview",
        "{player} NBA pregame interview",
        "{player} basketball media day",
        "{player} NBA practice footage",
        "{player} basketball interview 2025",
        "{player} NBA media session",
        "{player} basketball locker room interview",
    ],
    "nfl": [
        "{player} NFL press conference",
        "{player} football postgame press conference",
        "{player} NFL interview 2025",
        "{player} football practice footage",
        "{player} NFL media day",
        "{player} football training camp",
        "{player} NFL pregame interview",
        "{player} NFL media session",
    ],
}

# Phase 2 — Club/team level, still low copyright risk
GENERIC_YT_QUERIES = {
    "soccer": [
        "{player} club training session",
        "{player} team press conference",
        "soccer player interview 2025",
        "football training ground footage",
        "soccer pre-match press conference",
        "football manager press conference 2025",
        "soccer player media day",
        "football training session 2025",
    ],
    "nba": [
        "{player} team practice",
        "NBA player press conference 2025",
        "basketball player interview 2025",
        "NBA media day 2025",
        "basketball practice footage 2025",
        "NBA player postgame interview",
        "basketball player media session",
    ],
    "nfl": [
        "{player} team press conference",
        "NFL player interview 2025",
        "football player press conference",
        "NFL training camp footage 2025",
        "NFL media day 2025",
        "football player postgame interview",
    ],
}

# Dailymotion — lower risk content
DAILYMOTION_QUERIES = {
    "soccer": [
        "football press conference",
        "soccer player interview",
        "football training session",
        "soccer media day",
        "football manager interview",
    ],
    "nba": [
        "nba press conference",
        "basketball player interview",
        "nba media day",
        "basketball practice",
    ],
    "nfl": [
        "nfl press conference",
        "football player interview",
        "nfl training camp",
        "nfl media day",
    ],
}

PEXELS_QUERIES = {
    "soccer": [
        "soccer player running", "football match stadium", "soccer goal celebration",
        "soccer player dribbling", "football training ground", "soccer fans cheering",
        "football stadium crowd", "soccer referee game", "football skills training",
        "soccer match night", "football penalty kick", "soccer goalkeeper save",
        "football pitch aerial view", "soccer player kick ball", "football team warm up",
    ],
    "nba": [
        "basketball player", "basketball game", "basketball court", "basketball dunk",
        "basketball crowd", "basketball training", "basketball shooting",
        "basketball pass", "basketball arena", "nba court lights",
        "basketball player running", "basketball slam dunk", "indoor sport arena",
        "basketball warm up", "basketball fans cheering", "sport arena crowd",
        "basketball referee", "basketball defense", "basketball fast break",
    ],
    "nfl": [
        "american football", "football game", "football player", "football stadium",
        "american football crowd", "football training", "football helmet",
        "football tackle", "football touchdown", "sport stadium aerial",
        "football fans cheering", "football field lights", "american football team",
        "football warm up", "sport crowd stadium", "football quarterback",
        "american football action", "football coach", "sport arena night",
    ],
}

# ── Highlight queries — TikTok + Instagram (real game footage, high engagement)
PLAYER_QUERIES_HIGHLIGHTS = {
    "soccer": [
        "{player} goal 2025",
        "{player} goals today",
        "{player} best goal this season",
        "{player} hat trick 2025",
        "{player} free kick goal",
        "{player} volley goal",
        "{player} bicycle kick",
        "{player} match highlights today",
        "{player} incredible goal reaction",
        "{player} goal celebration 2025",
        "{player} vs match 2025",
        "{player} dribble goal assist 2025",
    ],
    "nba": [
        "{player} dunk 2025",
        "{player} dunk tonight",
        "{player} clutch shot game winner",
        "{player} best dunk this season",
        "{player} insane play 2025",
        "{player} triple double highlights",
        "{player} buzzer beater 2025",
        "{player} alley oop 2025",
        "{player} crossover layup",
        "{player} game winner reaction",
        "{player} huge dunk crowd reaction",
        "{player} highlights tonight",
    ],
    "nfl": [
        "{player} touchdown 2025",
        "{player} touchdown catch today",
        "{player} incredible run touchdown",
        "{player} highlight play this week",
        "{player} big play game 2025",
        "{player} best catch 2025",
        "{player} sack forced fumble 2025",
        "{player} long run touchdown",
        "{player} game winning play",
        "{player} crazy play reaction 2025",
        "{player} highlights week",
        "{player} clutch play playoffs",
    ],
}

GENERIC_YT_QUERIES_HIGHLIGHTS = {
    "soccer": [
        "best goals of the week football 2025",
        "premier league goals this week",
        "champions league goals 2025",
        "football goal of the season 2025",
        "insane football goal reaction",
        "best free kick goals 2025",
        "football amazing goal compilation week",
        "la liga goals this week 2025",
        "serie a best goals 2025",
        "soccer goal crowd reaction 2025",
    ],
    "nba": [
        "best NBA dunks this week 2025",
        "NBA insane play tonight",
        "top NBA plays of the night",
        "NBA game winner buzzer beater 2025",
        "best NBA highlights this week",
        "NBA clutch plays 2025",
        "nba crowd reaction best play",
        "nba alley oop dunks compilation",
    ],
    "nfl": [
        "best NFL touchdowns this week 2025",
        "NFL insane play this week",
        "top NFL plays week 2025",
        "NFL game winning touchdown",
        "best NFL catches 2025",
        "NFL crowd reaction big play",
        "nfl one handed catch 2025",
    ],
}

DAILYMOTION_QUERIES_HIGHLIGHTS = {
    "soccer": [
        "football goal 2025",
        "soccer goal this week",
        "football best goal match",
        "premier league goal highlights",
    ],
    "nba": [
        "nba dunk tonight",
        "basketball game winner",
        "nba best play",
    ],
    "nfl": [
        "nfl touchdown 2025",
        "football big play this week",
        "nfl highlight play",
    ],
}

# ── Reddit Config ─────────────────────────────────────────────────────────────

REDDIT_SUBREDDITS = {
    "soccer": ["soccer", "footballhighlights", "PremierLeague", "championsleague"],
    "nba":    ["nba", "nbahighlights"],
    "nfl":    ["nfl", "nflstreams"],
}

_REDDIT_VIDEO_DOMAINS = {
    "v.redd.it", "streamable.com", "youtu.be", "youtube.com",
    "clips.twitch.tv", "medal.tv", "streamff.com", "dubz.co",
    "clippituser.tv", "mixtape.moe", "gfycat.com",
}


# ── Download Helpers ──────────────────────────────────────────────────────────

def _ytdlp(query_or_url: str, output_dir: Path, before: set,
           is_search: bool = True, timeout: int = 90) -> Path | None:
    # Use ytsearch10 and pick a random result (1-6) to avoid always getting the same clip
    start = random.randint(1, 6) if is_search else 1
    inp = f"ytsearch10:{query_or_url}" if is_search else query_or_url
    logger.info(f"[clip] yt-dlp (start={start}): {inp[:80]}")
    cmd = [
        "yt-dlp", inp,
        "--match-filter", "duration < 360",
        "--format", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
        "--merge-output-format", "mp4",
        "-o", str(output_dir / "clip_%(id)s.%(ext)s"),
        "--no-playlist", "--quiet", "--no-warnings",
        "--max-downloads", "1",
        "--playlist-start", str(start),
        "--socket-timeout", "20",
        "--retries", "3",
        "--no-check-certificate",
    ]
    cookie_file = _get_cookie_file()
    if cookie_file:
        cmd += ["--cookies", cookie_file]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        after = set(output_dir.glob("clip_*.mp4"))
        new = after - before
        if new:
            clip = sorted(new, key=lambda f: f.stat().st_mtime)[-1]
            logger.info(f"[clip] Downloaded: {clip.name} ({clip.stat().st_size/1024/1024:.1f} MB)")
            return clip
    except Exception as e:
        logger.warning(f"[clip] yt-dlp error: {e}")
    return None


def _dailymotion(query: str, output_dir: Path, before: set) -> Path | None:
    """Dailymotion Public API — no key needed."""
    try:
        url = (
            "https://api.dailymotion.com/videos"
            f"?search={urllib.parse.quote(query)}"
            "&fields=id,url,duration"
            "&longer_than=20&shorter_than=300"
            "&limit=5&sort=relevance"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            videos = json.loads(resp.read()).get("list", [])
        for v in videos:
            video_url = v.get("url", "")
            if not video_url:
                continue
            logger.info(f"[clip] Dailymotion: {video_url}")
            clip = _ytdlp(video_url, output_dir, before, is_search=False, timeout=60)
            if clip:
                return clip
    except Exception as e:
        logger.warning(f"[clip] Dailymotion error: {e}")
    return None


def _pexels(query: str, output_dir: Path, before: set) -> Path | None:
    """Pexels Video API — needs PEXELS_API_KEY in Railway variables."""
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import requests, certifi
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": 10, "size": "medium"},
            timeout=15,
            verify=certifi.where(),
        )
        if not r.ok:
            logger.warning(f"[clip] Pexels HTTP {r.status_code}: {r.text[:120]}")
            return None
        videos = r.json().get("videos", [])

        random.shuffle(videos)
        for video in videos:
            files = sorted(
                [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4"],
                key=lambda f: abs(f.get("height", 0) - 720)
            )
            for f in files:
                if 360 <= f.get("height", 0) <= 1080:
                    dl_url = f["link"]
                    out = output_dir / f"clip_pexels_{video['id']}.mp4"
                    logger.info(f"[clip] Pexels download: {video['id']} ({f.get('height')}p)")
                    dl = requests.get(dl_url, timeout=90, stream=True, verify=certifi.where())
                    if not dl.ok:
                        continue
                    with open(out, "wb") as fh:
                        for chunk in dl.iter_content(chunk_size=1024 * 1024):
                            fh.write(chunk)
                    if out.stat().st_size > 500_000:
                        logger.info(f"[clip] Pexels OK: {out.name} ({out.stat().st_size/1024/1024:.1f} MB)")
                        return out
                    out.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"[clip] Pexels error: {e}")
    return None


# ── Reddit Highlights ─────────────────────────────────────────────────────────

def _reddit_token() -> str | None:
    """Get Reddit OAuth2 token via client credentials (no user login needed)."""
    import base64
    import requests as _rq
    client_id     = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    try:
        auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        r = _rq.post(
            "https://www.reddit.com/api/v1/access_token",
            headers={"Authorization": f"Basic {auth}",
                     "User-Agent": "SynCinSportBot/1.0"},
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        token = r.json().get("access_token")
        if token:
            logger.info("[clip] Reddit OAuth2 token OK")
        return token
    except Exception as e:
        logger.warning(f"[clip] Reddit OAuth2 error: {e}")
        return None


def _reddit(player: str, sport: str, output_dir: Path, before: set) -> Path | None:
    """
    Browse sport subreddits for player-specific highlight clips.
    Uses OAuth2 (oauth.reddit.com) when REDDIT_CLIENT_ID/SECRET are set —
    bypasses the 403 Railway IPs get on the anonymous endpoint.
    """
    import requests as _rq

    subs = REDDIT_SUBREDDITS.get(sport, ["sports"])

    # Match on last name — e.g. "Victor Wembanyama" → look for "wembanyama"
    player_words = [w.lower() for w in player.split() if len(w) > 3]
    match_words  = player_words[-1:] if player_words else player_words

    token    = _reddit_token()
    base_url = "https://oauth.reddit.com" if token else "https://www.reddit.com"
    headers  = {"User-Agent": "SynCinSportBot/1.0 highlight-fetcher"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def _fetch(url: str) -> list:
        r = _rq.get(url, headers=headers, timeout=12)
        return r.json().get("data", {}).get("children", [])

    def _try_posts(posts: list) -> Path | None:
        for post in posts:
            d        = post.get("data", {})
            title    = d.get("title", "").lower()
            post_url = d.get("url", "")
            domain   = d.get("domain", "")
            if not all(w in title for w in match_words):
                continue
            is_video = (
                d.get("is_video", False)
                or domain in _REDDIT_VIDEO_DOMAINS
                or any(dom in post_url for dom in _REDDIT_VIDEO_DOMAINS)
            )
            if not is_video:
                continue
            logger.info(f"[clip] Reddit '{d.get('title','')[:60]}'")
            clip = _ytdlp(post_url, output_dir, before, is_search=False, timeout=60)
            if clip:
                return clip
        return None

    for sub in subs:
        for sort in ["new", "hot"]:
            try:
                posts = _fetch(f"{base_url}/r/{sub}/{sort}.json?limit=100")
                clip  = _try_posts(posts)
                if clip:
                    return clip
            except Exception as e:
                logger.warning(f"[clip] Reddit r/{sub}/{sort} error: {e}")

    # Fallback: search
    try:
        query = urllib.parse.quote(f"{player} highlights")
        posts = _fetch(
            f"{base_url}/r/{subs[0]}/search.json"
            f"?q={query}&sort=new&t=month&restrict_sr=1&limit=25"
        )
        clip = _try_posts(posts)
        if clip:
            return clip
    except Exception as e:
        logger.warning(f"[clip] Reddit search fallback error: {e}")

    return None


# ── Main Function ─────────────────────────────────────────────────────────────

def fetch_clips(player: str, sport: str, output_dir: Path,
                duration_hint: float = 60.0, count: int = 3,
                mode: str = "youtube") -> list[Path]:
    """
    3-phase search — returns empty list if all phases fail.
    mode="youtube"     → press conference / training clips (low Content ID risk)
    mode="highlights"  → highlights / goals / skills clips (TikTok/IG only)
    No gradient fallback.
    """
    # Select query dicts based on mode
    if mode == "highlights":
        p_queries = PLAYER_QUERIES_HIGHLIGHTS
        g_queries = GENERIC_YT_QUERIES_HIGHLIGHTS
        d_queries = DAILYMOTION_QUERIES_HIGHLIGHTS
        fallback_sport = "soccer"
    else:
        p_queries = PLAYER_QUERIES
        g_queries = GENERIC_YT_QUERIES
        d_queries = DAILYMOTION_QUERIES
        fallback_sport = "soccer"

    output_dir.mkdir(exist_ok=True, parents=True)
    downloaded: list[Path] = []
    before = set(output_dir.glob("clip_*.mp4"))

    def _add(clip):
        if clip and clip not in downloaded:
            downloaded.append(clip)
            before.add(clip)

    # ── Phase 1: YouTube, player-specific ────────────────────────────────────
    if player and len(player.strip()) >= 3:
        templates = p_queries.get(sport, p_queries.get(fallback_sport, list(p_queries.values())[0]))
        queries = [t.format(player=player) for t in random.sample(templates, min(count + 1, len(templates)))]
        for q in queries:
            if len(downloaded) >= count:
                break
            _add(_ytdlp(q, output_dir, before))

    # ── Phase 1.5: Reddit player-specific highlights ──────────────────────────
    if len(downloaded) < count and player and len(player.strip()) >= 3:
        logger.info(f"[clip] Phase 1.5: Reddit search for '{player}'...")
        for _ in range(count - len(downloaded)):
            if len(downloaded) >= count:
                break
            _add(_reddit(player, sport, output_dir, before))

    # ── Phase 2: YouTube generic + Dailymotion ────────────────────────────────
    if len(downloaded) < count:
        logger.info(f"[clip] Phase 1.5: {len(downloaded)}/{count} — starting Phase 2 (YouTube generic + Dailymotion)...")

        raw_generic = g_queries.get(sport, g_queries.get(fallback_sport, list(g_queries.values())[0]))
        yt_generic = [t.format(player=player) if player else t
                      for t in random.sample(raw_generic, min(count - len(downloaded) + 1, len(raw_generic)))]
        for q in yt_generic:
            if len(downloaded) >= count:
                break
            _add(_ytdlp(q, output_dir, before))

        dm_pool = d_queries.get(sport, d_queries.get(fallback_sport, list(d_queries.values())[0]))
        dm_sample = random.sample(dm_pool, min(2, len(dm_pool)))
        for q in dm_sample:
            if len(downloaded) >= count:
                break
            _add(_dailymotion(q, output_dir, before))

    # ── Phase 3: Pexels Stock Video ───────────────────────────────────────────
    if len(downloaded) < count:
        logger.info(f"[clip] Phase 2: {len(downloaded)}/{count} — starting Phase 3 (Pexels)...")
        px_queries = PEXELS_QUERIES.get(sport, ["sports"])
        for q in random.sample(px_queries, min(2, len(px_queries))):
            if len(downloaded) >= count:
                break
            _add(_pexels(q, output_dir, before))

    if not downloaded:
        logger.error(f"[clip] All 3 phases failed for '{player}' ({sport}) mode={mode}")
    else:
        logger.info(f"[clip] {len(downloaded)} clip(s) found (mode={mode})")

    return downloaded[:count]


def fetch_clip(player: str, sport: str, output_dir: Path,
               duration_hint: float = 60.0, mode: str = "youtube") -> Path | None:
    clips = fetch_clips(player, sport, output_dir, duration_hint, count=1, mode=mode)
    return clips[0] if clips else None


def trim_clip(clip_path: Path, duration: float, output_path: Path) -> Path:
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)],
            capture_output=True, text=True, timeout=15,
        )
        clip_dur = float(probe.stdout.strip())
    except Exception:
        clip_dur = duration + 10

    max_start = max(0, clip_dur - duration - 2)
    start = random.uniform(0, max_start) if max_start > 0 else 0

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start), "-i", str(clip_path),
        "-t", str(duration),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an", "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        logger.warning(f"[clip] Trim error: {r.stderr[:200]}")
        import shutil
        shutil.copy(str(clip_path), str(output_path))
    logger.info(f"[clip] Trimmed: {output_path.name}")
    return output_path
