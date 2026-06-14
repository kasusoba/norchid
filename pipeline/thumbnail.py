"""Thumbnail generation (Pillow) — two layouts (BRANDING.md §2, DECISIONS D12).

Matches the reference look: white text with a **soft glow** (not a hard stroke)
and the Instrumental tag in a **rounded pill**.

- "cinematic" (ref: Mela!): full-bleed darkened YouTube thumbnail, centered
  title with an outline "Instrumental" pill beneath it.
- "album" (ref: One Day): blurred-extended album cover with the cover readable,
  a filled "instrumental" pill top-left, artist + title stacked bottom-left.

Titles use Montserrat ExtraBold, falling back to Noto Sans CJK for CJK text.
Output is 1280x720 PNG with no duration badge.
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app import config

W, H = config.THUMB_W, config.THUMB_H
UA = "norchid/0.1"


# --- fonts ----------------------------------------------------------------
def _has_cjk(text: str) -> bool:
    for ch in text:
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF
                or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF):
            return True
    return False


def _font(size: int, text: str) -> ImageFont.FreeTypeFont:
    path = config.NOTO_CJK_PATH if _has_cjk(text) else config.MONTSERRAT_PATH
    return ImageFont.truetype(str(path), size)


def _measure(text, font):
    l, t, r, b = font.getbbox(text)
    return r - l, b - t


def _wrap(text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if _measure(trial, font)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _fit_title(text, max_w, max_h, start_size):
    size = start_size
    while size > 26:
        font = _font(size, text)
        lines = _wrap(text, font, max_w)
        line_h = _measure("Ay", font)[1]
        total_h = int(line_h * 1.16 * len(lines))
        if total_h <= max_h and all(_measure(ln, font)[0] <= max_w for ln in lines):
            return font, lines, line_h
        size -= 4
    font = _font(size, text)
    return font, _wrap(text, font, max_w), _measure("Ay", font)[1]


# --- soft-glow text -------------------------------------------------------
def _glow_text(canvas: Image.Image, xy, text, font, fill=(255, 255, 255, 255),
               anchor="la", glow=(0, 0, 0, 200), radius=12, passes=2):
    """Draw text with a soft dark glow for legibility (RGBA canvas)."""
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text(xy, text, font=font, fill=glow, anchor=anchor)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius))
    for _ in range(passes):
        canvas.alpha_composite(shadow)
    ImageDraw.Draw(canvas).text(xy, text, font=font, fill=fill, anchor=anchor)


def _glow_block(canvas, lines, font, line_h, x, top, align="left",
                fill=(255, 255, 255, 255), radius=12):
    y = top
    for ln in lines:
        if align == "center":
            _glow_text(canvas, (x, y), ln, font, fill=fill, anchor="ma", radius=radius)
        else:
            _glow_text(canvas, (x, y), ln, font, fill=fill, anchor="la", radius=radius)
        y += int(line_h * 1.16)
    return y


def _pill(canvas, text, font, xy, anchor="la", pad=(20, 11),
          fill=None, outline=None, ow=2, text_fill=(255, 255, 255, 255), radius=999):
    """Rounded-pill label. anchor 'la' = top-left at xy, 'ma' = top-center at xy."""
    tw, th = _measure(text, font)
    bw, bh = tw + pad[0] * 2, th + pad[1] * 2
    x = xy[0] - bw / 2 if anchor == "ma" else xy[0]
    y = xy[1]
    box = [x, y, x + bw, y + bh]
    r = min(radius, bh / 2)
    # Draw the (semi-transparent) pill on its own layer so alpha is respected
    # — drawing directly on the RGBA canvas would overwrite the alpha channel.
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=r, fill=fill,
                                            outline=outline, width=ow)
    canvas.alpha_composite(layer)
    # Center text in the pill (account for glyph bbox offset).
    bbox = font.getbbox(text)
    ImageDraw.Draw(canvas).text((x + pad[0] - bbox[0], y + pad[1] - bbox[1]),
                                text, font=font, fill=text_fill)
    return box


# --- backgrounds ----------------------------------------------------------
def _cover_to_canvas(cover: Path) -> Image.Image:
    src = Image.open(cover).convert("RGB")
    bg = src.copy()
    scale = max(W / bg.width, H / bg.height) * 1.1
    bg = bg.resize((int(bg.width * scale), int(bg.height * scale)))
    left = (bg.width - W) // 2
    top = (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(30))
    bg = ImageEnhance.Brightness(bg).enhance(0.5)
    fg = src.copy()
    fg_size = int(H * 0.84)
    fg.thumbnail((fg_size, fg_size))
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return bg.convert("RGBA")


def _yt_canvas(yt_thumb: Path) -> Image.Image:
    img = Image.open(yt_thumb).convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)))
    left = (img.width - W) // 2
    top = (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    # Darken with a center-weighted gradient for title legibility.
    overlay = Image.new("L", (1, H), 0)
    for y in range(H):
        d = 1 - abs((y - H * 0.52) / (H / 2))
        overlay.putpixel((0, y), int(150 * max(0, d) + 55))
    overlay = overlay.resize((W, H))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(black, img, overlay).convert("RGBA")


def download_yt_thumb(url: str | None, work_dir: Path) -> Path | None:
    if not url:
        return None
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=20.0) as c:
            data = c.get(url).content
        path = work_dir / "yt_thumb.jpg"
        Image.open(io.BytesIO(data)).convert("RGB").save(path, "JPEG", quality=92)
        return path
    except Exception:
        return None


# --- layouts --------------------------------------------------------------
def make_cinematic(title: str, yt_thumb: Path | None, bg_color, out: Path) -> Path:
    canvas = _yt_canvas(yt_thumb) if yt_thumb else \
        Image.new("RGBA", (W, H), tuple(bg_color) + (255,))
    font, lines, line_h = _fit_title(title, int(W * 0.84), int(H * 0.46), 118)
    block_h = int(line_h * 1.16 * len(lines))
    top = int(H * 0.40) - block_h // 2
    end_y = _glow_block(canvas, lines, font, line_h, W // 2, top, align="center", radius=16)

    label_font = _font(38, "INSTRUMENTAL")
    _pill(canvas, "INSTRUMENTAL", label_font, (W // 2, end_y + 26), anchor="ma",
          pad=(26, 12), outline=(255, 255, 255, 210), ow=3, fill=(255, 255, 255, 26))
    canvas.convert("RGB").save(out)
    return out


def make_album(artist: str, title: str, cover: Path | None, bg_color, out: Path) -> Path:
    canvas = _cover_to_canvas(cover) if cover else \
        Image.new("RGBA", (W, H), tuple(bg_color) + (255,))

    # Top-left filled pill.
    tag_font = _font(32, "instrumental")
    _pill(canvas, "instrumental", tag_font, (44, 44), anchor="la",
          pad=(18, 10), fill=(0, 0, 0, 150))

    # Bottom-left stacked artist + title.
    title_font, title_lines, line_h = _fit_title(title, int(W * 0.9), int(H * 0.4), 92)
    block_h = int(line_h * 1.16 * len(title_lines))
    base_y = H - 58 - block_h
    if artist:
        artist_font = _font(42, artist)
        ah = _measure(artist, artist_font)[1]
        _glow_text(canvas, (58, base_y - ah - 14), artist, artist_font,
                   fill=(238, 238, 240, 255), anchor="la", radius=10)
    _glow_block(canvas, title_lines, title_font, line_h, 58, base_y, align="left", radius=14)
    canvas.convert("RGB").save(out)
    return out


def make_thumbnail(layout: str, meta: dict, work_dir: Path,
                   cover: Path | None, bg_color, out: Path) -> Path:
    title = meta.get("title") or "Untitled"
    artist = meta.get("artist") or ""
    if layout == "album":
        return make_album(artist, title, cover, bg_color, out)
    yt = download_yt_thumb(meta.get("yt_thumbnail_url"), work_dir)
    return make_cinematic(title, yt, bg_color, out)
