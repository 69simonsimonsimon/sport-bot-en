"""
TTS Generator — Sport Bot EN
OpenAI TTS
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("syncin")


def _openai_tts(text: str, output_path: Path, voice: str = "echo",
                speed: float = 1.05) -> Path:
    import openai
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
        speed=speed,
    )
    output_path.parent.mkdir(exist_ok=True, parents=True)
    with open(str(output_path), "wb") as f:
        f.write(response.content)
    logger.info(f"[tts] OpenAI audio saved: {output_path.name}")
    return output_path



# Sport → (voice, speed) — energetic commentary voices per sport type
_SPORT_VOICE: dict[str, tuple[str, float]] = {
    "soccer": ("onyx",    1.05),  # deep, authoritative commentary
    "nba":    ("echo",    1.10),  # energetic, fast-paced for basketball
    "nfl":    ("fable",   1.03),  # dramatic storytelling for NFL
}


def generate_tts(text: str, output_path: Path, voice: str = "echo",
                 sport: str = "") -> Path:
    """
    OpenAI TTS with sport-adapted voice + speed.
    sport: 'soccer' | 'nba' | 'nfl' | ''
    """
    words = text.split()
    if len(words) > 155:
        text = " ".join(words[:155]) + "."
        logger.warning("[tts] Text auf 155 Wörter gekürzt")

    logger.info(f"[tts] TTS: {len(words)} Wörter")

    # Sport-based voice overrides the passed-in voice
    if sport and sport in _SPORT_VOICE:
        voice, speed = _SPORT_VOICE[sport]
    else:
        speed = 1.05
    logger.info(f"[tts] voice={voice} speed={speed}x")
    return _openai_tts(text, output_path, voice, speed=speed)
