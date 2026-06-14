"""LRC -> ASS subtitle (Spotify-style windowed scrolling highlight).

The renderer is norchid's highest-risk piece (Phase 0). It converts line-level
LRC timestamps into an ASS file where, for each lyric line, we emit one Dialogue
event holding a *window* of nearby lines centered on screen (\\an5). The active
line is full-opacity white; neighbors are dimmed. As the active line advances the
window shifts, producing the scroll. libass + a CJK font do the rest.

See docs/ARCHITECTURE.md §4 and docs/DECISIONS.md D8/D10/D14.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Style constants (docs/BRANDING.md, DECISIONS D10/D11/D14) -------------
LYRIC_FONT = "Noto Sans CJK JP"  # full CJK: Latin/romaji + kana/kanji + Hangul
FONT_SIZE = 64
WINDOW_RADIUS = 2  # lines shown above/below the active line (5-line window)
# ASS \alpha: &H00& = opaque, &HFF& = transparent. Opacity 45% -> ~&H8C&.
ALPHA_ACTIVE = "&H00&"
ALPHA_INACTIVE = "&H8C&"
FADE_MS = 120  # \fad in/out per event

# LRC timestamp:  [mm:ss.xx] or [mm:ss.xxx] or [mm:ss]
_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


@dataclass
class LyricLine:
    t: float  # start time in seconds (offset already applied)
    text: str


def parse_lrc(lrc: str, offset_ms: int = 0) -> list[LyricLine]:
    """Parse LRC text into time-sorted lyric lines, applying a global offset.

    - Supports multiple timestamps per line (expanded into separate lines).
    - Drops metadata-only tags ([ar:], [ti:], [length:], ...) and empty lines.
    - A negative offset can push times earlier; results are clamped at >= 0.
    """
    out: list[LyricLine] = []
    offset = offset_ms / 1000.0
    for raw in lrc.splitlines():
        stamps = list(_LRC_TIME.finditer(raw))
        if not stamps:
            continue
        text = _LRC_TIME.sub("", raw).strip()
        if not text:
            continue  # purely a timing line with no words
        for m in stamps:
            mm, ss, frac = m.group(1), m.group(2), m.group(3)
            t = int(mm) * 60 + int(ss)
            if frac:
                t += int(frac.ljust(3, "0")) / 1000.0
            t = max(0.0, t + offset)
            out.append(LyricLine(t=t, text=text))
    out.sort(key=lambda x: x.t)
    return out


def _ass_time(seconds: float) -> str:
    """Format seconds as ASS H:MM:SS.cc (centiseconds)."""
    seconds = max(0.0, seconds)
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    """Escape characters special to ASS so lyric text renders literally."""
    return text.replace("\\", "\\​").replace("{", "(").replace("}", ")")


def build_ass(
    lines: list[LyricLine],
    duration: float,
    width: int = 1920,
    height: int = 1080,
    font: str = LYRIC_FONT,
    font_size: int = FONT_SIZE,
) -> str:
    """Build a full ASS document with the windowed-highlight scroll effect.

    `duration` is the song/instrumental length in seconds; the final lyric line
    is held until then.
    """
    header = f"""[Script Info]
; norchid scrolling-lyrics render
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lyric,{font},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,0,2,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    n = len(lines)
    for i, line in enumerate(lines):
        start = line.t
        end = lines[i + 1].t if i + 1 < n else duration
        if end <= start:
            end = start + 0.1  # guard against zero/negative-length events
        events.append(_event(lines, i, start, end))
    return header + "\n".join(events) + "\n"


def _event(lines: list[LyricLine], i: int, start: float, end: float) -> str:
    """One Dialogue event: a centered window of lines with the active one bright."""
    n = len(lines)
    segments: list[str] = []
    for slot, idx in enumerate(range(i - WINDOW_RADIUS, i + WINDOW_RADIUS + 1)):
        text = _escape(lines[idx].text) if 0 <= idx < n else ""
        alpha = ALPHA_ACTIVE if idx == i else ALPHA_INACTIVE
        if slot == 0:
            # First segment carries the line-wide tags (alignment + fade).
            segments.append(f"{{\\an5\\fad({FADE_MS},{FADE_MS})\\alpha{alpha}}}{text}")
        else:
            segments.append(f"{{\\alpha{alpha}}}{text}")
    body = "\\N".join(segments)
    return (
        f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Lyric,,0,0,0,,{body}"
    )


def write_ass(
    lrc: str,
    out_path: str,
    duration: float,
    offset_ms: int = 0,
    width: int = 1920,
    height: int = 1080,
    font: str = LYRIC_FONT,
    font_size: int = FONT_SIZE,
) -> list[LyricLine]:
    """Convenience: parse LRC -> build ASS -> write file. Returns parsed lines."""
    lines = parse_lrc(lrc, offset_ms=offset_ms)
    if not lines:
        raise ValueError("No timed lyric lines parsed from LRC input.")
    ass = build_ass(lines, duration, width, height, font, font_size)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ass)
    return lines
