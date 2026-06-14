"""LRC -> ASS subtitle: smooth Spotify-style scrolling lyrics.

Each lyric line is its own positioned event. Within an inter-line interval the
line holds, then over the last TRANSITION_MS it scrolls up one slot (\\move)
while the highlight hands off to the next line. Three states (Spotify): the
current line is bright (active), already-sung lines above are mid (passed), and
not-yet-reached lines below are dim (upcoming). An optional romaji/romanization
line rides in a smaller font under each line.

Geometry + opacity live in ``app.config.SCROLL`` and are shared with the browser
preview (via /api/render-config) so they match. See docs/ARCHITECTURE.md §4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app import config

LYRIC_FONT = "Noto Sans CJK JP Black"  # full CJK: Latin/romaji + kana/kanji + Hangul

_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")

# Placeholder shown for an instrumental break (an empty timed LRC line). The
# highlight rests here instead of staying on the last sung line.
INSTRUMENTAL_GLYPH = "♪"
# Only show the placeholder when the instrumental gap is at least this long.
INSTRUMENTAL_MIN_GAP = 2.5


@dataclass
class LyricLine:
    t: float
    text: str
    instrumental: bool = False


def parse_lrc(lrc: str, offset_ms: int = 0) -> list[LyricLine]:
    """Parse LRC text into time-sorted lyric lines, applying a global offset.

    Empty timed lines (LRCLIB's instrumental markers) are kept as instrumental
    placeholders rather than dropped, so the highlight rests on a ♪ during long
    breaks. Trivial gaps and consecutive markers are collapsed.
    """
    out: list[LyricLine] = []
    offset = offset_ms / 1000.0
    for raw in lrc.splitlines():
        stamps = list(_LRC_TIME.finditer(raw))
        if not stamps:
            continue
        text = _LRC_TIME.sub("", raw).strip()
        for m in stamps:
            mm, ss, frac = m.group(1), m.group(2), m.group(3)
            t = int(mm) * 60 + int(ss)
            if frac:
                t += int(frac.ljust(3, "0")) / 1000.0
            out.append(LyricLine(t=max(0.0, t + offset), text=text,
                                 instrumental=not text))
    out.sort(key=lambda x: x.t)
    return _clean_instrumentals(out)


def _clean_instrumentals(lines: list[LyricLine]) -> list[LyricLine]:
    """Drop instrumental markers with a trivial gap, and collapse consecutive
    ones. A leading instrumental marker is dropped (the intro already shows the
    upcoming lines)."""
    out: list[LyricLine] = []
    n = len(lines)
    for k, ln in enumerate(lines):
        if ln.instrumental:
            if not out:                       # leading marker -> intro handles it
                continue
            if out[-1].instrumental:          # collapse consecutive
                continue
            nxt = lines[k + 1].t if k + 1 < n else None
            if nxt is not None and nxt - ln.t < INSTRUMENTAL_MIN_GAP:
                continue                      # gap too short to bother
        out.append(ln)
    return out


def align_romaji(native: list[LyricLine], romaji_text: str | None,
                 offset_ms: int = 0) -> list[str]:
    """Build a romaji string per native line. Accepts a romaji LRC (matched by
    nearest timestamp) or plain lines in order (matched by index)."""
    n = len(native)
    if not romaji_text or not romaji_text.strip():
        return [""] * n
    timed = [r for r in parse_lrc(romaji_text, offset_ms=offset_ms) if not r.instrumental]
    if timed:
        out = []
        for nl in native:
            if nl.instrumental:
                out.append(""); continue
            best = min(timed, key=lambda r: abs(r.t - nl.t))
            out.append(best.text if abs(best.t - nl.t) < 0.45 else "")
        return out
    # Plain lines, matched by order — instrumental placeholders consume no romaji.
    plain = [ln.strip() for ln in romaji_text.splitlines() if ln.strip()]
    out, idx = [], 0
    for nl in native:
        if nl.instrumental:
            out.append("")
        else:
            out.append(plain[idx] if idx < len(plain) else "")
            idx += 1
    return out


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\​").replace("{", "(").replace("}", ")")


def _atag(opacity_transparent: float) -> str:
    return f"&H{max(0, min(255, round(opacity_transparent * 255))):02X}&"


def build_ass(
    lines: list[LyricLine],
    duration: float,
    romaji: list[str] | None = None,
    width: int = config.WIDTH,
    height: int = config.HEIGHT,
    font: str = LYRIC_FONT,
    scroll: dict | None = None,
) -> str:
    s = scroll or config.SCROLL
    fs = s["font_size"]
    romaji = romaji or [""] * len(lines)
    has_romaji = any(romaji)

    gap_ratio = s["line_gap_ratio_romaji"] if has_romaji else s["line_gap_ratio"]
    L = round(fs * gap_ratio)
    romaji_size = round(fs * s["romaji_size_ratio"])
    romaji_dy = round(fs * s["romaji_offset_ratio"])
    vr = s["visible_radius"]
    tw_ms = s["transition_ms"]
    a_active, a_passed, a_upcoming = (
        _atag(s["alpha_active"]), _atag(s["alpha_passed"]), _atag(s["alpha_upcoming"]))

    ass_fs = round(fs * config.CJK_LIBASS_SCALE)
    ass_romaji_fs = round(romaji_size * config.CJK_LIBASS_SCALE)

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
Style: Lyric,{font},{ass_fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1
Style: Romaji,{font},{ass_romaji_fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    n = len(lines)
    events: list[str] = []

    def disp(ln):
        return INSTRUMENTAL_GLYPH if ln.instrumental else ln.text

    def emit(text, style, y0, y1, move_start, d_ms, alpha_frag, start_s, end_s):
        if not text:
            return
        if y1 == y0:
            pos = f"\\pos({cx},{y0:.0f})"
        else:
            pos = f"\\move({cx},{y0:.0f},{cx},{y1:.0f},{move_start},{d_ms})"
        events.append(
            f"Dialogue: 0,{start_s},{end_s},{style},,0,0,0,,"
            f"{{\\an5{pos}{alpha_frag}}}{_escape(text)}")

    def alpha_frag(j, i, last, move_start, d_ms):
        if last:
            a = a_active if j == i else (a_passed if j < i else a_upcoming)
            return f"\\alpha{a}"
        if j < i:
            return f"\\alpha{a_passed}"
        if j == i:
            return f"\\alpha{a_active}\\t({move_start},{d_ms},\\alpha{a_passed})"
        if j == i + 1:
            return f"\\alpha{a_upcoming}\\t({move_start},{d_ms},\\alpha{a_active})"
        return f"\\alpha{a_upcoming}"

    # Intro: opening window, all DIM (upcoming) — nothing highlighted until reached.
    if lines and lines[0].t > 0.05:
        s0, e0 = _ass_time(0), _ass_time(lines[0].t)
        for j in range(0, vr + 1):
            if j >= n:
                break
            y = mid + j * L
            frag = f"\\alpha{a_upcoming}"
            emit(disp(lines[j]), "Lyric", y, y, 0, 1, frag, s0, e0)
            emit(romaji[j], "Romaji", y + romaji_dy, y + romaji_dy, 0, 1, frag, s0, e0)

    for i in range(n):
        t0 = lines[i].t
        last = (i + 1 >= n)
        t1 = duration if last else lines[i + 1].t
        if t1 <= t0:
            t1 = t0 + 0.05
        d_ms = int(round((t1 - t0) * 1000))
        tw = 0 if last else min(tw_ms, d_ms)
        move_start = d_ms - tw
        s0, e0 = _ass_time(t0), _ass_time(t1)

        for j in range(i - vr, i + vr + 1):
            if not (0 <= j < n):
                continue
            y0 = mid + (j - i) * L
            y1 = y0 if last else y0 - L
            frag = alpha_frag(j, i, last, move_start, d_ms)
            emit(disp(lines[j]), "Lyric", y0, y1, move_start, d_ms, frag, s0, e0)
            emit(romaji[j], "Romaji", y0 + romaji_dy, y1 + romaji_dy,
                 move_start, d_ms, frag, s0, e0)

    return header + "\n".join(events) + "\n"


def write_ass(
    lrc: str,
    out_path: str,
    duration: float,
    offset_ms: int = 0,
    romaji: str | None = None,
    width: int = config.WIDTH,
    height: int = config.HEIGHT,
    font: str = LYRIC_FONT,
    scroll: dict | None = None,
) -> list[LyricLine]:
    """Parse LRC (+ optional romaji) -> build ASS -> write file. Returns lines."""
    lines = parse_lrc(lrc, offset_ms=offset_ms)
    if not lines:
        raise ValueError("No timed lyric lines parsed from LRC input.")
    romaji_texts = align_romaji(lines, romaji, offset_ms=offset_ms)
    ass = build_ass(lines, duration, romaji_texts, width, height, font, scroll)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ass)
    return lines
