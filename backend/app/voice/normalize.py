"""Text → speech normalisation: what the TTS should *say* (display text stays in script/captions/overlays)."""
from __future__ import annotations

import re

_REPLACEMENTS = [
    (r"^\s*POV\s*:?\s*", ""),                   # "POV:" is a visual convention, never spoken
    (r"\bvs\.?\s", "versus "),
    (r"\s&\s", " and "),
    (r"\be\.g\.\s*", "for example "),
    (r"\bi\.e\.\s*", "that is "),
    (r"\betc\.", "et cetera."),
    (r"\bw/\s", "with "),
]


def speech_text(text: str) -> str:
    out = text
    for pat, rep in _REPLACEMENTS:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()
