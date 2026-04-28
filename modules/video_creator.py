"""
Video Creator — Sport Bot EN
Single-Pass: Video loop + filter + audio in ONE ffmpeg call.
No tmp file, no PTS issues, no duration bug.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("syncin")
W, H = 1080, 1920


def _get_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        val = r.stdout.strip()
        return float(val) if val else 60.0
    except Exception:
        return 60.0


def _run(cmd, timeout=480):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.stderr:
        logger.debug(f"[ffmpeg] stderr: {r.stderr[-400:]}")
    return r


def _sanitize(text: str) -> str:
    """Strip emoji and chars that break ffmpeg filter parsing."""
    text = text.encode("ascii", "ignore").decode("ascii")
    for ch in ["'", '"', "\\", ":", "[", "]", "=", ";", "%", ","]:
        text = text.replace(ch, "")
    return " ".join(text.split()).strip()


def create_video(clip_path: Path, audio_path: Path, title: str,
                 output_path: Path, sport: str = "soccer",
                 words: list = None) -> Path:

    audio_dur = _get_duration(audio_path)
    clip_dur  = _get_duration(clip_path)
    logger.info(f"[video] Audio: {audio_dur:.1f}s | Clip: {clip_dur:.1f}s")

    accent = {"soccer": "0x00AAFF", "nba": "0xFF6B00", "nfl": "0x00CC55"}.get(sport, "0x00AAFF")
    label  = {"soccer": "SOCCER", "nba": "NBA", "nfl": "NFL"}.get(sport, "SPORTS")

    font = ""
    for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
               "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]:
        if Path(fp).exists():
            font = fp
            break
    fa = f":fontfile={font}" if font else ""

    badge_y   = 44
    handle_y  = H - 58
    karaoke_y = H - 320
    g = [int(H * t) for t in (0.52, 0.62, 0.70, 0.78, 0.87)]

    # ── Build karaoke word filters ────────────────────────────────────────────
    karaoke_filters = []
    if words:
        for w in words:
            wtext = _sanitize(str(w.get("word", "")).strip())
            if not wtext:
                continue
            t_start = float(w.get("start", 0))
            t_end   = float(w.get("end", t_start + 0.3))
            # Dynamic font size — shrink for long words so they never overflow
            wlen = len(wtext)
            fs = 90 if wlen <= 8 else (74 if wlen <= 13 else (58 if wlen <= 18 else 46))
            karaoke_filters.append(
                f"drawtext=text='{wtext}'{fa}"
                f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
                f":fontsize={fs}:fontcolor=yellow"
                f":box=1:boxcolor=black@0.78:boxborderw=14"
                f":borderw=3:bordercolor=black@0.95"
                f":x=(w-text_w)/2:y={karaoke_y}"
            )
        logger.info(f"[video] Karaoke: {len(karaoke_filters)} word filters")

    vf_parts = [
        # ── Letterbox scaling (no stretch) ───────────────────────────────────
        f"scale={W}:{H}:force_original_aspect_ratio=decrease",
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black",
        # ── Subtle dark vignette ─────────────────────────────────────────────
        f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.12:t=fill",
        # ── Bottom gradient for subtitle readability ─────────────────────────
        f"drawbox=x=0:y={g[0]}:w={W}:h={H-g[0]}:color=black@0.18:t=fill",
        f"drawbox=x=0:y={g[1]}:w={W}:h={H-g[1]}:color=black@0.26:t=fill",
        f"drawbox=x=0:y={g[2]}:w={W}:h={H-g[2]}:color=black@0.34:t=fill",
        f"drawbox=x=0:y={g[3]}:w={W}:h={H-g[3]}:color=black@0.42:t=fill",
        f"drawbox=x=0:y={g[4]}:w={W}:h={H-g[4]}:color=black@0.50:t=fill",
        # ── Top accent line ──────────────────────────────────────────────────
        f"drawbox=x=0:y=0:w={W}:h=8:color={accent}@1.0:t=fill",
        # ── Sport badge (top left) ───────────────────────────────────────────
        f"drawbox=x=28:y={badge_y}:w=220:h=68:color=black@0.60:t=fill",
        f"drawbox=x=28:y={badge_y}:w=7:h=68:color={accent}@1.0:t=fill",
        f"drawtext=text='{label}'{fa}:fontsize=32:fontcolor={accent}:x=50:y={badge_y+18}",
        # ── Bottom accent line ───────────────────────────────────────────────
        f"drawbox=x=0:y={H-10}:w={W}:h=10:color={accent}@1.0:t=fill",
        # ── Handle ──────────────────────────────────────────────────────────
        f"drawtext=text='SynCinSportUS'{fa}:fontsize=24:fontcolor=white@0.55"
        f":x=(w-text_w)/2:y={handle_y}",
    ]

    # Append karaoke word-by-word filters
    vf_parts.extend(karaoke_filters)
    vf = ",".join(vf_parts)

    target_dur = audio_dur + 0.5
    # Loop enough times to cover target_dur — use at least 8 to handle short clips
    loops = max(8, int(target_dur / max(clip_dur, 1)) + 4)

    list_file = output_path.with_name(f"_list_{output_path.stem}.txt")
    list_file.write_text(
        "\n".join(f"file '{clip_path.resolve()}'" for _ in range(loops)),
        encoding="utf-8"
    )

    logger.info(f"[video] Single-Pass: concat x{loops} → filter → encode+audio → {output_path.name}")

    try:
        r = _run([
            "ffmpeg", "-y",
            # +genpts regenerates timestamps — fixes broken pts from -c copy concat
            "-fflags", "+genpts",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-i", str(audio_path),
            "-filter_complex", f"[0:v]{vf}[vout]",
            "-map", "[vout]",
            "-map", "1:a",
            "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            "-r", "25",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(target_dur),
            str(output_path),
        ], timeout=480)

        if r.returncode != 0:
            logger.error(f"[video] ffmpeg error:\n{r.stderr[-800:]}")
            raise RuntimeError(f"ffmpeg failed: {r.stderr[-200:]}")

    finally:
        list_file.unlink(missing_ok=True)

    mb = output_path.stat().st_size / 1024 / 1024
    logger.info(f"[video] Done: {output_path.name} ({mb:.1f} MB)")

    # Check duration, not file size (static clips are legitimately small)
    actual_dur = _get_duration(output_path)
    if actual_dur < 20.0:
        logger.error(f"[video] Output too short ({actual_dur:.1f}s, {mb:.1f} MB) — ffmpeg stderr: {r.stderr[-400:]}")
        raise RuntimeError(f"Video too short ({actual_dur:.1f}s) — encoding failed")

    return output_path
