"""
Video Creator — Sport Bot EN
Single-Pass: Video loop + filter + audio in ONE ffmpeg call.
Modern minimal design: clean overlay, no badge, text-stroke karaoke.
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

    # Single accent color per sport — used only for thin top line
    accent = {"soccer": "0x00AAFF", "nba": "0xFF6B00", "nfl": "0x00CC55"}.get(sport, "0xFFFFFF")

    font = ""
    for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
               "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]:
        if Path(fp).exists():
            font = fp
            break
    fa = f":fontfile={font}" if font else ""

    karaoke_y = H - 300

    # ── Karaoke word filters — text stroke, no box ─────────────────────────
    karaoke_filters = []
    if words:
        for w in words:
            wtext = _sanitize(str(w.get("word", "")).strip())
            if not wtext:
                continue
            t_start = float(w.get("start", 0))
            t_end   = float(w.get("end", t_start + 0.3))
            wlen    = len(wtext)
            fs      = 96 if wlen <= 8 else (78 if wlen <= 13 else (62 if wlen <= 18 else 48))
            karaoke_filters.append(
                f"drawtext=text='{wtext}'{fa}"
                f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
                f":fontsize={fs}:fontcolor=white"
                f":borderw=4:bordercolor=black@1.0"
                f":x=(w-text_w)/2:y={karaoke_y}"
            )
        logger.info(f"[video] Karaoke: {len(karaoke_filters)} word filters")

    vf_parts = [
        # Scale to portrait
        f"scale={W}:{H}:force_original_aspect_ratio=decrease",
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black",
        # Single clean dark overlay
        f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.40:t=fill",
        # Bottom gradient — just 2 layers for subtitle readability
        f"drawbox=x=0:y={int(H*0.50)}:w={W}:h={int(H*0.50)}:color=black@0.28:t=fill",
        f"drawbox=x=0:y={int(H*0.70)}:w={W}:h={int(H*0.30)}:color=black@0.20:t=fill",
        # Thin accent line at top only
        f"drawbox=x=0:y=0:w={W}:h=4:color={accent}@1.0:t=fill",
    ]
    vf_parts.extend(karaoke_filters)
    vf = ",".join(vf_parts)

    target_dur = audio_dur + 0.5
    loops = max(8, int(target_dur / max(clip_dur, 1)) + 4)

    list_file = output_path.with_name(f"_list_{output_path.stem}.txt")
    list_file.write_text(
        "\n".join(f"file '{clip_path.resolve()}'" for _ in range(loops)),
        encoding="utf-8"
    )

    logger.info(f"[video] Single-Pass → {output_path.name}")

    try:
        r = _run([
            "ffmpeg", "-y",
            "-fflags", "+genpts",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-i", str(audio_path),
            "-filter_complex", f"[0:v]{vf}[vout]",
            "-map", "[vout]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            "-r", "25", "-pix_fmt", "yuv420p",
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

    actual_dur = _get_duration(output_path)
    if actual_dur < 20.0:
        raise RuntimeError(f"Video too short ({actual_dur:.1f}s)")

    return output_path
