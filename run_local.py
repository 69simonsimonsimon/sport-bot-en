#!/usr/bin/env python3
"""
Sport Bot EN — Lokaler Video-Generator
=======================================
Generiert 2 Videos pro Lauf und lädt sie in die Bunny-Queue:
  en_{stamp}.mp4     → Highlights  → TikTok + Instagram
  en_yt_{stamp}.mp4  → Pressekonferenz/Training → YouTube (dediziertes Profil)

GitHub Actions postet sie automatisch nach Schedule.

Usage:
  python run_local.py              # zufälliger Sport
  python run_local.py soccer
  python run_local.py nba
  python run_local.py nfl
  python run_local.py nba 3        # 3 Durchläufe (= 6 Videos)
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=True)
sys.path.insert(0, str(ROOT / "modules"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sportbot")

OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
(OUTPUT_DIR / "clips").mkdir(exist_ok=True)


def _bunny_upload(video_path: Path, filename: str, meta: dict) -> str:
    """Upload video + JSON metadata to Bunny queue/. Returns CDN URL."""
    import certifi, requests as rq
    password = os.environ["BUNNY_STORAGE_PASSWORD"]
    zone     = os.environ.get("BUNNY_STORAGE_NAME", "syncin")
    cdn_url  = os.environ.get("BUNNY_CDN_URL", "https://syncin.b-cdn.net")
    hostname = os.environ.get("BUNNY_STORAGE_HOSTNAME", "storage.bunnycdn.com")

    with open(str(video_path), "rb") as f:
        r = rq.put(
            f"https://{hostname}/{zone}/queue/{filename}",
            headers={"AccessKey": password, "Content-Type": "video/mp4"},
            data=f, verify=certifi.where(), timeout=300,
        )
    r.raise_for_status()

    meta["cdn_url"] = f"{cdn_url}/queue/{filename}"
    rq.put(
        f"https://{hostname}/{zone}/queue/{filename.replace('.mp4', '.json')}",
        headers={"AccessKey": password, "Content-Type": "application/json"},
        data=json.dumps(meta, ensure_ascii=False).encode(),
        verify=certifi.where(), timeout=30,
    ).raise_for_status()

    return meta["cdn_url"]


def _fetch_trim_render(player: str, sport: str, stamp: str, mode: str,
                       audio_path: Path, audio_duration: float,
                       tts_words: list, script: dict) -> Path | None:
    """
    Fetch clips (mode='highlights' or 'youtube'), trim, combine, render video.
    Returns path to rendered video, or None if no clips found.
    """
    from clip_fetcher import fetch_clips, trim_clip
    from video_creator import create_video

    clip_dir = OUTPUT_DIR / "clips" / mode
    clip_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"🎬  Fetching {mode} clips: {player}...")
    raw_clips = fetch_clips(player, sport, clip_dir, audio_duration, count=7, mode=mode)

    if not raw_clips:
        logger.warning(f"    No {mode} clips found — skipping")
        return None

    logger.info(f"    → {len(raw_clips)} clip(s) found")

    # Trim
    seg_dur = max(10.0, audio_duration / len(raw_clips))
    trimmed = []
    for i, rc in enumerate(raw_clips):
        t = clip_dir / f"trimmed_{stamp}_{i}.mp4"
        trim_clip(rc, seg_dur, t)
        trimmed.append(t)
        rc.unlink(missing_ok=True)

    # Combine
    if len(trimmed) == 1:
        combined = trimmed[0]
    else:
        combined = clip_dir / f"combined_{stamp}.mp4"
        list_file = clip_dir / f"list_{stamp}.txt"
        list_file.write_text("\n".join(f"file '{str(t.resolve())}'" for t in trimmed))
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(list_file), "-c", "copy", str(combined)],
            capture_output=True, timeout=120,
        )
        list_file.unlink(missing_ok=True)
        for t in trimmed:
            t.unlink(missing_ok=True)

    # Render
    logger.info(f"🎞️   Rendering {mode} video...")
    video_path = OUTPUT_DIR / f"video_{mode}_{stamp}.mp4"
    create_video(combined, audio_path, script["title"], video_path,
                 script["sport"], words=tts_words)
    combined.unlink(missing_ok=True)

    mb = video_path.stat().st_size / 1024 / 1024
    logger.info(f"    → {video_path.name} ({mb:.1f} MB)")
    return video_path


def generate_and_queue(sport: str = None) -> bool:
    from news_scraper import fetch_news
    from script_generator import generate_script
    from tts_generator import generate_tts

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]

    # 1. News
    logger.info("📰  Fetching news...")
    article = fetch_news(sport)
    logger.info(f"    → {article['title'][:70]}")

    # 2. Script
    logger.info("✍️   Generating script...")
    script = generate_script(article)
    logger.info(f"    → {script['title'][:60]}  [{script['sport']} / {script['mode']}]")

    # 3. TTS
    logger.info("🎙️   Generating voiceover...")
    audio_path = OUTPUT_DIR / f"audio_{stamp}.mp3"
    generate_tts(script["tts_text"], audio_path, voice="echo")

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True, timeout=15,
    )
    audio_duration = float(probe.stdout.strip()) if probe.stdout.strip() else 60.0
    logger.info(f"    → {audio_duration:.1f}s audio")

    # 3b. Whisper karaoke timestamps
    logger.info("📝  Transcribing for karaoke...")
    tts_words = []
    try:
        import openai
        wc = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        with open(str(audio_path), "rb") as af:
            tr = wc.audio.transcriptions.create(
                model="whisper-1", file=af,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )
        tts_words = [{"word": w.word, "start": w.start, "end": w.end}
                     for w in (tr.words or [])]
        logger.info(f"    → {len(tts_words)} words")
    except Exception as e:
        logger.warning(f"    Whisper failed (no karaoke): {e}")

    meta_base = {
        "title":   script["title"],
        "caption": script["caption"],
        "sport":   script["sport"],
        "player":  script["player"],
    }

    success_count = 0

    # ── Video A: Highlights → TikTok + Instagram (en_<stamp>) ─────────────────
    logger.info("\n── Video A: Highlights (TikTok + Instagram) ──────────────────")
    video_hl = _fetch_trim_render(
        script["player"], script["sport"], stamp,
        mode="highlights",
        audio_path=audio_path,
        audio_duration=audio_duration,
        tts_words=tts_words,
        script=script,
    )
    if video_hl:
        filename_hl = f"en_{stamp}.mp4"
        cdn = _bunny_upload(video_hl, filename_hl, dict(meta_base))
        video_hl.unlink(missing_ok=True)
        logger.info(f"✅  Queued: {filename_hl}  ({cdn})")
        success_count += 1
    else:
        logger.warning("⚠️   Highlights video skipped — no clips")

    # ── Video B: Press conference/training → YouTube only (en_yt_<stamp>) ─────
    logger.info("\n── Video B: Press conference (YouTube) ───────────────────────")
    video_yt = _fetch_trim_render(
        script["player"], script["sport"], f"{stamp}_yt",
        mode="youtube",
        audio_path=audio_path,
        audio_duration=audio_duration,
        tts_words=tts_words,
        script=script,
    )
    if video_yt:
        filename_yt = f"en_yt_{stamp}.mp4"
        cdn = _bunny_upload(video_yt, filename_yt, dict(meta_base))
        video_yt.unlink(missing_ok=True)
        logger.info(f"✅  Queued: {filename_yt}  ({cdn})")
        success_count += 1
    else:
        logger.warning("⚠️   YouTube video skipped — no clips")

    # Cleanup audio
    audio_path.unlink(missing_ok=True)

    logger.info(f"\n🏁  {success_count}/2 videos queued for '{script['title'][:50]}'")
    return success_count > 0


if __name__ == "__main__":
    import concurrent.futures
    sport   = sys.argv[1] if len(sys.argv) > 1 else None
    count   = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    workers = min(count, int(sys.argv[3]) if len(sys.argv) > 3 else 2)

    done = []

    def _task(i):
        if count > 1:
            logger.info(f"\n{'='*50}\nRun {i+1}/{count}\n{'='*50}")
        if generate_and_queue(sport):
            done.append(1)

    if workers > 1 and count > 1:
        logger.info(f"🚀  Parallel: {count} runs × {workers} workers")
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_task, range(count)))
    else:
        for i in range(count):
            _task(i)

    logger.info(f"\n🏁  Done: {len(done)}/{count} runs completed")
