"""
AI Quality Check — Claude Haiku
================================
Evaluates story/script content for TikTok viral potential.
Returns (approved: bool, reason: str).

NOTE: This checks the CONTENT (title + story text), not background videos.
Background videos are auto-selected by topic keyword — they are not AI-evaluated.
"""

import os


def quality_check(title: str, content: str, context: str = "", lang: str = "en") -> tuple[bool, str]:
    """
    Ask Claude Haiku to evaluate viral potential of the given content.

    Args:
        title:   Video title / headline
        content: Main story or script text (first 500 chars used)
        context: Optional extra context (e.g. subreddit, sport type)
        lang:    "en" or "de" — controls prompt language

    Returns:
        (approved, reason_string)
        approved=True  → proceed with rendering
        approved=False → skip/delete this video
        On any API error → fail open (approved=True)
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return True, "QC skipped (no ANTHROPIC_API_KEY)"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        snippet = content[:500].strip()

        if lang == "de":
            prompt = (
                "Du bist ein TikTok-Viral-Content-Experte. Bewerte kurz ob dieses Video gut performen wird.\n\n"
                + (f"Kontext: {context}\n" if context else "")
                + f"Titel: {title}\n"
                + f"Inhalt: {snippet}\n\n"
                "Hat das virales Potenzial? Bewerte:\n"
                "- Erzeugt der Titel sofort Neugier oder eine emotionale Reaktion?\n"
                "- Ist der Inhalt überraschend, nahbar oder emotional aufgeladen?\n"
                "- Werden Leute kommentieren, teilen oder anderen zeigen?\n\n"
                "Antworte mit GENAU einer dieser Optionen (nichts anderes):\n"
                "APPROVED - [Grund in max 10 Wörtern]\n"
                "REJECTED - [Grund in max 10 Wörtern]\n\n"
                "Sei streng. Nur wirklich starke Inhalte sollen APPROVED bekommen."
            )
        else:
            prompt = (
                "You are a TikTok viral content expert. Quickly evaluate if this video will perform well.\n\n"
                + (f"Context: {context}\n" if context else "")
                + f"Title: {title}\n"
                + f"Content: {snippet}\n\n"
                "Does this have viral potential? Consider:\n"
                "- Does the title create instant curiosity or emotional response?\n"
                "- Is the content surprising, relatable, or emotionally charged?\n"
                "- Will people comment, share, or show others?\n\n"
                "Reply with EXACTLY one of (nothing else):\n"
                "APPROVED - [reason in max 10 words]\n"
                "REJECTED - [reason in max 10 words]\n\n"
                "Be strict. Only truly strong content should be APPROVED."
            )

        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        approved = text.upper().startswith("APPROVED")
        return approved, text

    except Exception as e:
        # Fail open: network issues / quota should not block generation
        return True, f"QC error (auto-approved): {e}"
