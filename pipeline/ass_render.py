"""LRC -> ASS subtitle: smooth Spotify-style scrolling lyrics.

Each lyric line is its own positioned event. Within an inter-line interval the
line **holds** centered, then over the last TRANSITION_MS it **scrolls up one
slot** (via \\move) while the highlight hands off to the next line (\\t on
\\alpha). Because consecutive events share identical positions at their shared
boundary, the motion is continuous — a true scroll, not a per-line redraw.

The scroll geometry (font size, line spacing, transition, opacity) lives in
``app.config.SCROLL`` and is shared with the browser preview so they match.
See docs/ARCHITECTURE.md §4 and docs/DECISIONS.md D8/D10/D14.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app import config

LYRIC_FONT = "Noto Sans CJK JP"  # full CJK: Latin/romaji + kana/kanji + Hangul

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


def _alpha_tag(opacity_transparent: float) -> str:
    """ASS \\alpha hex from a 0..1 transparency (0 = opaque)."""
    return f"&H{max(0, min(255, round(opacity_transparent * 255))):02X}&"


def build_ass(
    lines: list[LyricLine],
    duration: float,
    width: int = config.WIDTH,
    height: int = config.HEIGHT,
    font: str = LYRIC_FONT,
    scroll: dict | None = None,
) -> str:
    """Build a full ASS document with the smooth scrolling-highlight effect."""
    s = scroll or config.SCROLL
    font_size = s["font_size"]
    L = s["line_spacing"]
    vr = s["visible_radius"]
    tw_ms = s["transition_ms"]
    a_active = _alpha_tag(s["alpha_active"])
    a_inact = _alpha_tag(s["alpha_inactive"])

    cx = width // 2
    mid = height / 2

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
Style: Lyric,{font},{font_size},&H00FFFFFF,&H00FFFFFF,&H96000000,&H64000000,-1,0,0,0,100,100,0,0,1,1.4,0,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    n = len(lines)
    events: list[str] = []
    for i in range(n):
        t0 = lines[i].t
        last = (i + 1 >= n)
        t1 = duration if last else lines[i + 1].t
        if t1 <= t0:
            t1 = t0 + 0.05
        d_ms = int(round((t1 - t0) * 1000))
        tw = 0 if last else min(tw_ms, d_ms)
        move_start = d_ms - tw

        for j in range(i - vr, i + vr + 1):
            if not (0 <= j < n):
                continue
            y0 = mid + (j - i) * L
            y1 = y0 if last else y0 - L
            ev = _line_event(
                lines[j].text, j, i, last, cx, y0, y1, move_start, d_ms,
                a_active, a_inact, _ass_time(t0), _ass_time(t1))
            events.append(ev)
    return header + "\n".join(events) + "\n"


def _line_event(text, j, i, last, cx, y0, y1, move_start, d_ms,
                a_active, a_inact, start_s, end_s) -> str:
    """One Dialogue: line j during the interval starting at line i."""
    body = _escape(text)
    # Position: hold at y0, then scroll to y1 between move_start..d_ms.
    if y1 == y0:
        pos = f"\\pos({cx},{y0:.0f})"
    else:
        pos = f"\\move({cx},{y0:.0f},{cx},{y1:.0f},{move_start},{d_ms})"

    if last:
        alpha = a_active if j == i else a_inact
        tags = f"{{\\an5{pos}\\alpha{alpha}}}"
    elif j == i:        # active now -> dims as it scrolls up
        tags = (f"{{\\an5{pos}\\alpha{a_active}"
                f"\\t({move_start},{d_ms},\\alpha{a_inact})}}")
    elif j == i + 1:    # next line -> brightens into the center
        tags = (f"{{\\an5{pos}\\alpha{a_inact}"
                f"\\t({move_start},{d_ms},\\alpha{a_active})}}")
    else:               # neighbor -> stays dim while scrolling
        tags = f"{{\\an5{pos}\\alpha{a_inact}}}"

    return f"Dialogue: 0,{start_s},{end_s},Lyric,,0,0,0,,{tags}{body}"


def write_ass(
    lrc: str,
    out_path: str,
    duration: float,
    offset_ms: int = 0,
    width: int = config.WIDTH,
    height: int = config.HEIGHT,
    font: str = LYRIC_FONT,
    scroll: dict | None = None,
) -> list[LyricLine]:
    """Convenience: parse LRC -> build ASS -> write file. Returns parsed lines."""
    lines = parse_lrc(lrc, offset_ms=offset_ms)
    if not lines:
        raise ValueError("No timed lyric lines parsed from LRC input.")
    ass = build_ass(lines, duration, width, height, font, scroll)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ass)
    return lines
