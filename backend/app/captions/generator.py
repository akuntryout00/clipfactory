"""Caption chunking (2–5 words, sync with voice) + ASS subtitle writer with TikTok safe zones (PRD §15, §36, §37)."""
from __future__ import annotations

import re
from pathlib import Path

from app.schemas.configs import CaptionStyleConfig
from app.schemas.pipeline import CaptionChunk, WordTiming

_STOPWORDS = {"the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "for", "is", "it", "you", "your",
              "this", "that", "with", "then", "like", "just", "are", "was", "be", "do", "did", "not", "its", "it's"}


def _ends_clause(word: str) -> bool:
    return bool(re.search(r"[.!?;:,]$", word))


def _pause_after(words: list[WordTiming], i: int) -> float:
    if i + 1 >= len(words):
        return 0.0
    return words[i + 1].start - words[i].end


def build_caption_chunks(words: list[WordTiming], style: CaptionStyleConfig) -> list[CaptionChunk]:
    """Group words into 2–5 word chunks at clause boundaries / pauses; max chars per line respected."""
    chunks: list[CaptionChunk] = []
    buf: list[WordTiming] = []
    max_w, min_w = style.max_words_per_chunk, style.min_words_per_chunk
    max_chars = style.max_chars_per_line * style.max_lines

    def flush():
        if not buf:
            return
        text = " ".join(w.word for w in buf)
        chunks.append(CaptionChunk(start=buf[0].start, end=buf[-1].end, text=text, emphasis_index=_emphasis(buf)))
        buf.clear()

    for i, w in enumerate(words):
        buf.append(w)
        chars = sum(len(x.word) for x in buf) + len(buf) - 1
        hard_break = _ends_clause(w.word) and len(buf) >= min_w
        long_pause = _pause_after(words, i) > 0.35 and len(buf) >= min_w
        if len(buf) >= max_w or hard_break or long_pause or chars >= max_chars:
            flush()
        elif _ends_clause(w.word) and re.search(r"[.!?]$", w.word):
            flush()  # sentence end always flushes, even if only 1 word
    flush()
    # extend each chunk to the start of the next one (no flicker), but never across a long pause
    for a, b in zip(chunks, chunks[1:]):
        gap = b.start - a.end
        a.end = round(b.start if gap < 0.5 else a.end + 0.25, 3)
    if chunks:
        chunks[-1].end = round(chunks[-1].end + 0.3, 3)
    return chunks


def _emphasis(buf: list[WordTiming]) -> int | None:
    if len(buf) < 2:
        return None
    cands = [(len(re.sub(r"[^A-Za-z0-9]", "", w.word)), i) for i, w in enumerate(buf)
             if re.sub(r"[^A-Za-z0-9]", "", w.word).lower() not in _STOPWORDS]
    if not cands:
        return None
    return max(cands)[1]


# ---------- ASS writer ----------

def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _wrap_words(words: list[str], max_chars: int, max_lines: int) -> list[list[int]]:
    """Greedy wrap on plain word lengths → list of lines, each a list of word indices."""
    lines: list[list[int]] = []
    cur: list[int] = []
    cur_len = 0
    for i, w in enumerate(words):
        if cur and cur_len + 1 + len(w) > max_chars:
            lines.append(cur)
            cur, cur_len = [i], len(w)
        else:
            cur.append(i)
            cur_len = cur_len + (1 if cur_len else 0) + len(w)
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:  # squeeze: merge remainder into the last allowed line
        lines = lines[:max_lines - 1] + [[i for line in lines[max_lines - 1:] for i in line]]
    return lines


def _wrap(text: str, max_chars: int, max_lines: int) -> str:
    words = text.split()
    return "\\N".join(" ".join(words[i] for i in line) for line in _wrap_words(words, max_chars, max_lines))


def _esc(text: str) -> str:
    return text.replace("{", "(").replace("}", ")")


def write_ass(chunks: list[CaptionChunk], overlays: list[tuple[float, float, str]], style: CaptionStyleConfig,
              out_path: Path, width: int = 1080, height: int = 1920) -> Path:
    sz = style.safe_zone
    margin_l = int(width * sz.left)
    margin_r = int(width * sz.right)
    # caption vertical anchor: alignment 2 (bottom-center) with MarginV measured from bottom
    cap_margin_v = int(height * (1.0 - style.vertical_anchor_ratio))
    cap_margin_v = max(cap_margin_v, int(height * sz.bottom) + 10)
    ov = style.overlay
    ov_margin_v = int(height * ov.vertical_anchor_ratio)  # alignment 8 (top-center), MarginV from top
    ov_margin_v = max(ov_margin_v, int(height * sz.top) + 10)
    bold = -1 if style.bold else 0
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{style.font_name},{style.font_size},{style.primary_color},{style.emphasis_color},{style.outline_color},&H80000000,{bold},0,0,0,100,100,0,0,1,{style.outline},{style.shadow},2,{margin_l},{margin_r},{cap_margin_v},1",
        f"Style: Overlay,{ov.font_name},{ov.font_size},{ov.primary_color},{ov.primary_color},{ov.outline_color},&H80000000,{-1 if ov.bold else 0},0,0,0,100,100,1,0,1,{ov.outline},1,8,{margin_l},{margin_r},{ov_margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    pop = ""
    if style.animation == "pop":
        d = style.pop_duration_ms
        pop = f"{{\\fscx80\\fscy80\\t(0,{d},\\fscx100\\fscy100)}}"
    elif style.animation == "fade":
        pop = f"{{\\fad({style.pop_duration_ms},0)}}"
    for c in chunks:
        words = [_esc(w) for w in c.text.split()]
        wrapped = _wrap_words(words, style.max_chars_per_line, style.max_lines)
        if c.emphasis_index is not None and 0 <= c.emphasis_index < len(words):
            w = words[c.emphasis_index]
            words[c.emphasis_index] = f"{{\\1c{style.emphasis_color}}}{w}{{\\1c{style.primary_color}}}"
        text = "\\N".join(" ".join(words[i] for i in line) for line in wrapped)
        lines.append(f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},Caption,,0,0,0,,{pop}{text}")
    for start, end, text in overlays:
        fade = f"{{\\fad({ov.fade_ms},{ov.fade_ms})}}"
        wrapped = _wrap(_esc(text), ov.max_chars_per_line, 3)
        lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Overlay,,0,0,0,,{fade}{wrapped}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
