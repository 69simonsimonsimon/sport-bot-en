"""
SynCinSportEN Dashboard — FastAPI Backend
Sport News Bot: Soccer, NBA, NFL
Posts 4x daily current sports news with rage-bait on TikTok, YouTube, Instagram.
"""

import json
import logging
import os
import random
import sys
import threading
import time
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "modules"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

IS_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"))

# ── Logging ───────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(ROOT / "output")))
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
LOG_DIR = OUTPUT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

_handler = RotatingFileHandler(str(LOG_DIR / "bot.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
logger = logging.getLogger("syncin")
logger.setLevel(logging.INFO)
logger.addHandler(_handler)
logger.addHandler(logging.StreamHandler())

# ── Telegram ──────────────────────────────────────────────────────────────────
def _tg_credentials():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()

def notify(title: str, message: str):
    try:
        import urllib.request as _ur, json as _j
        token, chat_id = _tg_credentials()
        if not token or not chat_id:
            return
        body = _j.dumps({"chat_id": chat_id, "text": f"<b>{title}</b>\n{message}", "parse_mode": "HTML"}).encode()
        req = _ur.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                          data=body, headers={"Content-Type": "application/json"})
        _ur.urlopen(req, timeout=10)
    except Exception:
        pass

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="SynCinSportEN")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

jobs: dict = {}
_schedule_lock = threading.Lock()
_scheduler_thread = None

# ── Schedule ──────────────────────────────────────────────────────────────────
DEFAULT_SCHEDULE = [
    {"time": "11:00", "sport": None},
    {"time": "16:30", "sport": None},
    {"time": "21:30", "sport": None},
    {"time": "04:00", "sport": None},
]

_schedule_file = OUTPUT_DIR / "schedule.json"

def _load_schedule() -> list:
    try:
        return json.loads(_schedule_file.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_SCHEDULE

def _save_schedule(slots: list):
    _schedule_file.write_text(json.dumps(slots, ensure_ascii=False, indent=2), encoding="utf-8")

# ── Bunny Queue Upload ────────────────────────────────────────────────────────
def _bunny_upload(video_path, filename: str, meta: dict) -> bool:
    import certifi, requests as _rq
    password = os.environ.get("BUNNY_STORAGE_PASSWORD", "").strip()
    hostname = os.environ.get("BUNNY_STORAGE_HOSTNAME", "storage.bunnycdn.com")
    zone     = os.environ.get("BUNNY_STORAGE_NAME", "syncin")
    cdn_url  = os.environ.get("BUNNY_CDN_URL", "https://syncin.b-cdn.net")
    if not password:
        logger.error("[upload] BUNNY_STORAGE_PASSWORD not set")
        return False
    try:
        with open(str(video_path), "rb") as f:
            _rq.put(f"https://{hostname}/{zone}/queue/{filename}",
                    headers={"AccessKey": password, "Content-Type": "video/mp4"},
                    data=f, verify=certifi.where(), timeout=300).raise_for_status()
        meta["cdn_url"] = f"{cdn_url}/queue/{filename}"
        import json as _j
        _rq.put(f"https://{hostname}/{zone}/queue/{filename.replace('.mp4', '.json')}",
                headers={"AccessKey": password, "Content-Type": "application/json"},
                data=_j.dumps(meta, ensure_ascii=False).encode(),
                verify=certifi.where(), timeout=30).raise_for_status()
        logger.info(f"[upload] ✅ Bunny Queue: {filename}")
        return True
    except Exception as e:
        logger.error(f"[upload] Bunny upload failed: {e}")
        return False


def _fetch_trim_render(player, sport, stamp, mode, audio_path, audio_duration, tts_words, script):
    """Fetch clips (mode='highlights'|'youtube'), trim, combine, render. Returns video Path or None."""
    from clip_fetcher  import fetch_clips, trim_clip
    from video_creator import create_video
    clip_dir = OUTPUT_DIR / "clips" / mode
    clip_dir.mkdir(parents=True, exist_ok=True)
    raw_clips = fetch_clips(player, sport, clip_dir, audio_duration, count=3, mode=mode)
    if not raw_clips:
        logger.warning(f"[gen] No {mode} clips — skipping")
        return None
    seg_dur = max(10.0, audio_duration / len(raw_clips))
    trimmed = []
    for i, rc in enumerate(raw_clips):
        t = clip_dir / f"trimmed_{stamp}_{i}.mp4"
        trim_clip(rc, seg_dur, t)
        trimmed.append(t)
        rc.unlink(missing_ok=True)
    if len(trimmed) == 1:
        combined = trimmed[0]
    else:
        combined = clip_dir / f"combined_{stamp}.mp4"
        lf = clip_dir / f"list_{stamp}.txt"
        lf.write_text("\n".join(f"file '{str(t.resolve())}'" for t in trimmed))
        import subprocess as _sp
        _sp.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(lf), "-c", "copy", str(combined)],
                capture_output=True, timeout=120)
        lf.unlink(missing_ok=True)
        for t in trimmed:
            t.unlink(missing_ok=True)
    video_path = OUTPUT_DIR / f"video_{mode}_{stamp}.mp4"
    create_video(combined, audio_path, script["title"], video_path, script["sport"], words=tts_words)
    combined.unlink(missing_ok=True)
    mb = video_path.stat().st_size / 1024 / 1024
    logger.info(f"[gen] {mode} video: {video_path.name} ({mb:.1f} MB)")
    return video_path


# ── Video Generation ──────────────────────────────────────────────────────────
def _run_generation(job_id: str, sport: str = None):
    from news_scraper     import fetch_news
    from script_generator import generate_script
    from tts_generator    import generate_tts

    def upd(msg, pct=None):
        j = jobs.setdefault(job_id, {})
        j["message"] = msg
        if pct is not None:
            j["progress"] = pct
        logger.info(f"[job:{job_id}] {msg}")

    jobs[job_id] = {"status": "running", "progress": 0, "message": "Starting...", "video": None}

    try:
        # 1. Fetch news
        upd("Fetching latest sports news...", 10)
        article = fetch_news(sport)
        logger.info(f"[gen] Article: {article['title'][:70]}")

        # 2. Generate script
        upd("Generating script...", 20)
        script = generate_script(article)
        logger.info(f"[gen] Script ({script['mode']}): {script['title'][:60]}")

        # 3. TTS
        upd("Creating voiceover...", 35)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_path = OUTPUT_DIR / f"audio_{stamp}.mp3"
        generate_tts(script["tts_text"], audio_path, voice="echo")

        # Get audio duration
        import subprocess
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=15,
        )
        audio_duration = float(probe.stdout.strip()) if probe.stdout.strip() else 60.0

        # 3b. Whisper word timestamps for karaoke subtitles
        upd("Transcribing for karaoke subtitles...", 40)
        tts_words = []
        try:
            import openai as _oai
            _wc = _oai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            with open(str(audio_path), "rb") as _af:
                _tr = _wc.audio.transcriptions.create(
                    model="whisper-1",
                    file=_af,
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                )
            tts_words = [
                {"word": w.word, "start": w.start, "end": w.end}
                for w in (_tr.words or [])
            ]
            logger.info(f"[gen] Whisper: {len(tts_words)} words")
        except Exception as _e:
            logger.warning(f"[gen] Whisper failed (no karaoke): {_e}")

        meta_base = {
            "title":   script["title"],
            "caption": script["caption"],
            "sport":   script["sport"],
            "player":  script["player"],
        }

        queued = []

        # 4a. Highlights video → TikTok + Instagram (en_<stamp>)
        upd(f"Fetching highlight clips: {script['player']}...", 50)
        video_hl = _fetch_trim_render(script["player"], script["sport"], stamp,
                                      "highlights", audio_path, audio_duration, tts_words, script)
        if video_hl:
            upd("Uploading highlights to Bunny...", 65)
            if _bunny_upload(video_hl, f"en_{stamp}.mp4", dict(meta_base)):
                queued.append(f"en_{stamp}.mp4")
            video_hl.unlink(missing_ok=True)

        # 4b. Press conference video → YouTube only (en_yt_<stamp>)
        upd(f"Fetching press conference clips: {script['player']}...", 72)
        video_yt = _fetch_trim_render(script["player"], script["sport"], f"{stamp}_yt",
                                      "youtube", audio_path, audio_duration, tts_words, script)
        if video_yt:
            upd("Uploading YouTube video to Bunny...", 87)
            if _bunny_upload(video_yt, f"en_yt_{stamp}.mp4", dict(meta_base)):
                queued.append(f"en_yt_{stamp}.mp4")
            video_yt.unlink(missing_ok=True)

        audio_path.unlink(missing_ok=True)

        if queued:
            notify("🏆 Sport Bot EN", f"✅ {script['title'][:55]}\n📦 Queued: {', '.join(queued)}")
        else:
            notify("Sport Bot EN", f"⚠️ No clips found — nothing queued: {script['title'][:50]}")

        jobs[job_id].update({"status": "done", "progress": 100,
                              "message": f"Done: {len(queued)}/2 queued — {script['title'][:40]}",
                              "video": queued[0] if queued else None})

    except Exception as e:
        logger.error(f"[job:{job_id}] Error: {e}", exc_info=True)
        jobs[job_id].update({"status": "error", "message": str(e)})
        notify("Sport Bot EN", f"❌ Error: {str(e)[:80]}")


# ── Scheduler ─────────────────────────────────────────────────────────────────
_paused = False

def _run_scheduler():
    logger.info("[scheduler] Started")
    while True:
        if not _paused:
            now = datetime.utcnow()
            slots = _load_schedule()
            for slot in slots:
                t = slot.get("time", "")
                h, m = map(int, t.split(":")) if ":" in t else (0, 0)
                if now.hour == h and now.minute == m:
                    jitter = random.randint(0, 720)
                    if jitter:
                        time.sleep(jitter)
                    job_id = uuid.uuid4().hex[:8]
                    sport = slot.get("sport") or None
                    logger.info(f"[scheduler] Slot {t} — Sport: {sport or 'random'}")
                    t_gen = threading.Thread(target=_run_generation, args=(job_id, sport), daemon=True)
                    t_gen.start()
                    time.sleep(61)
                    break
        time.sleep(30)


# ── API Endpoints ─────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    global _scheduler_thread
    _scheduler_thread = threading.Thread(target=_run_scheduler, daemon=True)
    _scheduler_thread.start()
    logger.info("[startup] SynCinSportEN Bot started")

@app.get("/health")
def health():
    return {"status": "ok", "bot": "sport-en"}

@app.post("/api/generate")
def generate(body: dict = Body(...)):
    job_id = uuid.uuid4().hex[:8]
    sport = body.get("sport") or None
    t = threading.Thread(target=_run_generation, args=(job_id, sport), daemon=True)
    t.start()
    return {"job_id": job_id}

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return jobs.get(job_id, {"status": "not_found"})

@app.get("/api/schedule")
def get_schedule():
    return _load_schedule()

@app.post("/api/schedule")
def set_schedule(slots: list = Body(...)):
    _save_schedule(slots)
    return {"status": "ok"}

@app.post("/api/schedule/pause")
def pause_schedule(body: dict = Body({})):
    global _paused
    _paused = body.get("paused", not _paused)
    return {"paused": _paused}

@app.get("/api/videos")
def list_videos():
    videos = []
    for f in sorted(OUTPUT_DIR.glob("video_*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
        meta_f = f.with_suffix(".json")
        meta = {}
        if meta_f.exists():
            try:
                meta = json.loads(meta_f.read_text(encoding="utf-8"))
            except Exception:
                pass
        videos.append({
            "filename": f.name,
            "size_mb":  round(f.stat().st_size / 1024 / 1024, 1),
            "created":  datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
            "title":    meta.get("title", f.stem),
            "sport":    meta.get("sport", ""),
            "uploaded": meta.get("uploaded", False),
        })
    return videos

@app.get("/")
def dashboard():
    html = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>SynCinSportEN Dashboard</title>
<style>
  body { font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; background: #0a0a1a; color: #eee; }
  h1 { color: #00c8ff; }
  .card { background: #141428; border-radius: 12px; padding: 20px; margin: 16px 0; border: 1px solid #222; }
  button { background: #008cff; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; margin: 5px; }
  button:hover { background: #0066cc; }
  select { background: #1a1a2e; color: #eee; border: 1px solid #333; padding: 8px; border-radius: 6px; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; margin: 2px; }
  .soccer { background: #005a9e; } .nba { background: #c84b00; } .nfl { background: #004400; }
  #log { background: #0a0a0a; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 13px; max-height: 200px; overflow-y: auto; }
</style></head>
<body>
<h1>🏆 SynCinSportEN Dashboard</h1>
<div class="card">
  <h3>Generate Video</h3>
  <select id="sport">
    <option value="">🎲 Random</option>
    <option value="soccer">⚽ Soccer</option>
    <option value="nba">🏀 NBA</option>
    <option value="nfl">🏈 NFL</option>
  </select>
  <button onclick="generate()">▶ Generate & Upload</button>
  <div id="log">Ready.</div>
</div>
<div class="card">
  <h3>Recent Videos</h3>
  <div id="videos">Loading...</div>
</div>
<script>
async function generate() {
  const sport = document.getElementById('sport').value;
  document.getElementById('log').textContent = 'Starting generation...';
  const r = await fetch('/api/generate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sport: sport || null})});
  const d = await r.json();
  pollJob(d.job_id);
}
async function pollJob(id) {
  const r = await fetch('/api/jobs/' + id);
  const d = await r.json();
  document.getElementById('log').textContent = `[${d.progress||0}%] ${d.message || d.status}`;
  if (d.status === 'running') setTimeout(() => pollJob(id), 3000);
  else if (d.status === 'done') { document.getElementById('log').textContent = '✅ ' + d.message; loadVideos(); }
  else document.getElementById('log').textContent = '❌ ' + d.message;
}
async function loadVideos() {
  const r = await fetch('/api/videos');
  const vs = await r.json();
  document.getElementById('videos').innerHTML = vs.map(v =>
    `<div style="padding:10px;border-bottom:1px solid #222">
      <b>${v.title}</b>
      <span class="badge ${v.sport}">${v.sport?.toUpperCase()}</span>
      ${v.uploaded ? '✅' : '⏳'}
      <small style="color:#888">${v.created} · ${v.size_mb}MB</small>
    </div>`
  ).join('') || 'No videos';
}
loadVideos();
</script>
</body></html>"""
    return HTMLResponse(html)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
