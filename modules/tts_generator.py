"""
TTS Generator — Sport Bot EN
ElevenLabs (primär) → OpenAI Fallback
"""

import logging
import os
from pathlib import Path

import requests as _requests

logger = logging.getLogger("syncin")

# ElevenLabs: Adam — tief, autoritativ, gut für Sport-Kommentar
_EL_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
_EL_MODEL    = "eleven_multilingual_v2"


def _elevenlabs_tts(text: str, output_path: Path, api_key: str) -> Path:
    url  = f"https://api.elevenlabs.io/v1/text-to-speech/{_EL_VOICE_ID}"
    resp = _requests.post(
        url,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={
            "text":       text,
            "model_id":   _EL_MODEL,
            "voice_settings": {
                "stability":        0.45,
                "similarity_boost": 0.80,
                "style":            0.35,
                "use_speaker_boost": True,
            },
        },
        timeout=120,
    )
    resp.raise_for_status()
    output_path.parent.mkdir(exist_ok=True, parents=True)
    with open(str(output_path), "wb") as f:
        f.write(resp.content)
    logger.info(f"[tts] ElevenLabs audio saved: {output_path.name}")
    return output_path


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
