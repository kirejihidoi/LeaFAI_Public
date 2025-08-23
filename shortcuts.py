import os, re

SHORTCUTS_ENABLED = os.getenv("SHORTCUTS_ENABLED", "1") == "1"

PATTERNS = [
    (re.compile(r"^(ありがと(う|ー)?|thx|thanks)[!！]*$", re.I), "どういたしまして。"),
    (re.compile(r"^(草|w+)$"), "草"),
    (re.compile(r"^(おはよ|おはよう)$"), "おはよう。"),
    (re.compile(r"^(おやすみ|寝る)$"), "おやすみ。"),
]

def shortcut_reply(text: str) -> str | None:
    if not SHORTCUTS_ENABLED:
        return None
    t = (text or "").strip()
    if len(t) > 16:
        return None
    if "?" in t or "？" in t:
        return None
    for pat, resp in PATTERNS:
        if pat.search(t):
            return resp
    return None
