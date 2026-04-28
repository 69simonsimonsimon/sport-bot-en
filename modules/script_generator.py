"""
Script Generator — Sport Bot EN
=================================
Generates viral sports commentary via Claude.
Two modes: News-Recap or Rage-Bait Opinion Piece.
"""

import logging
import os
import random
import re

import anthropic

logger = logging.getLogger("syncin")

_CLAUDE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")


def _llm_call(prompt: str, system: str = "", max_tokens: int = 900) -> str:
    """Call Anthropic Claude — falls back to OpenAI GPT-4o-mini if credits exhausted."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        try:
            client = anthropic.Anthropic(api_key=anthropic_key)
            kwargs = {"model": _CLAUDE_MODEL, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]}
            if system:
                kwargs["system"] = system
            msg = client.messages.create(**kwargs)
            return msg.content[0].text.strip()
        except anthropic.BadRequestError as e:
            if "credit balance" in str(e).lower():
                logger.warning("[llm] Anthropic credits exhausted — OpenAI fallback")
            else:
                raise
    import openai
    oai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not oai_key:
        raise RuntimeError("Neither Anthropic nor OpenAI API key available")
    oai = openai.OpenAI(api_key=oai_key)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = oai.chat.completions.create(model="gpt-4o-mini", max_tokens=max_tokens, messages=messages)
    return resp.choices[0].message.content.strip()


_SYSTEM_PROMPT = """You are a viral sports content creator for TikTok/YouTube Shorts.
Your style: direct, passionate, controversial, sometimes provocative.
You ALWAYS take a clear opinion — never neutral.
You address the audience directly.
You build tension and end with a call for opinions.
Write ONLY the spoken text, no stage directions or formatting."""


def generate_script(article: dict, mode: str = "auto") -> dict:
    """
    Generates a TTS script based on an article.

    mode: 'news' = factual news with a spin
          'rage' = full rage-bait opinion
          'auto' = random (40% rage, 60% news)

    Returns: {title, tts_text, player, sport, hashtags, caption, mode, source_url}
    """
    if mode == "auto":
        mode = random.choices(["news", "rage"], weights=[60, 40], k=1)[0]

    sport = article.get("sport", "soccer")

    sport_label = {"soccer": "SOCCER", "nba": "NBA", "nfl": "NFL"}.get(sport, "SPORTS")

    if mode == "rage":
        prompt = f"""Based on this sports news:
TITLE: {article['title']}
CONTENT: {article['summary']}
SPORT: {sport_label}

Write a CONTROVERSIAL TikTok voiceover script in English. The script MUST be exactly 120-150 words — count carefully.
Requirements:
1. Start with a SHOCKING statement (no question, straight opinion)
2. BRUTALLY criticize or defend the player/team
3. Include a rage-bait moment ("Nobody wants to admit it, but...")
4. End with "Drop your opinion in the comments!"

After the script, provide these metadata fields:
TITLE: (clickable YouTube title with emojis, max 60 chars)
PLAYER: (main person/team for clip search)
HASHTAGS: (6 relevant hashtags)
CAPTION: (1 sentence + hashtags)

Format your response EXACTLY like this:
SCRIPT: [your 120-150 word script here]
TITLE: ...
PLAYER: ...
HASHTAGS: ...
CAPTION: ..."""
    else:
        prompt = f"""Based on this sports news:
TITLE: {article['title']}
CONTENT: {article['summary']}
SPORT: {sport_label}

Write an ENGAGING TikTok voiceover script in English. The script MUST be exactly 120-150 words — count carefully.
Requirements:
1. Start with a strong HOOK that grabs viewers immediately
2. Explain key facts with a clear opinionated angle
3. Include a surprising take or bold prediction
4. End with "What do you think? Comment below!"

After the script, provide these metadata fields:
TITLE: (clickable YouTube title with emojis, max 60 chars)
PLAYER: (main person/team for clip search)
HASHTAGS: (6 relevant hashtags)
CAPTION: (1 sentence + hashtags)

Format your response EXACTLY like this:
SCRIPT: [your 120-150 word script here]
TITLE: ...
PLAYER: ...
HASHTAGS: ...
CAPTION: ..."""

    raw = _llm_call(prompt, system=_SYSTEM_PROMPT, max_tokens=900)
    logger.info(f"[script] Claude Response ({mode}): {raw[:100]}")

    def extract(key: str) -> str:
        m = re.search(rf"^{key}:\s*(.+)$", raw, re.MULTILINE | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    tts_text = extract("SCRIPT")
    if not tts_text:
        parts = raw.split("SCRIPT:")
        tts_text = parts[-1].strip() if len(parts) > 1 else raw

    title    = extract("TITLE") or article["title"][:60]
    player   = extract("PLAYER") or ""
    hashtags = extract("HASHTAGS") or "#sports #soccer #nba #nfl #fyp #shorts"
    caption  = extract("CAPTION") or f"{title}\n{hashtags}"

    word_count = len(tts_text.split())
    logger.info(f"[script] Script: {word_count} words, mode: {mode}, player: {player}")

    if word_count < 100:
        raise ValueError(f"Script too short ({word_count} words)")
    if word_count > 160:
        words = tts_text.split()[:155]
        tts_text = " ".join(words) + "."

    return {
        "title":      title,
        "tts_text":   tts_text,
        "player":     player,
        "sport":      sport,
        "hashtags":   hashtags,
        "caption":    caption,
        "mode":       mode,
        "source_url": article.get("link", ""),
    }
