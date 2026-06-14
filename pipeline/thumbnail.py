"""Thumbnail generation (Pillow) — two layouts (BRANDING.md §2, DECISIONS D12).

- "cinematic": full-bleed YouTube thumbnail, darkened, centered title + label.
- "album": blurred-extended album cover, top-left tag, artist + title stacked.

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


def _text_size(draw, text, font):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def _wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if _text_size(draw, trial, font)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_title(draw, text, max_w, max_h, start_size):
    """Shrink the title font until wrapped lines fit the box."""
    size = start_size
    while size > 24:
        font = _font(size, text)
        lines = _wrap(draw, text, font, max_w)
        line_h = _text_size(draw, "Ay", font)[1]
        total_h = int(line_h * 1.18 * len(lines))
        if total_h <= max_h and all(_text_size(draw, ln, font)[0] <= max_w for ln in lines):
            return font, lines, line_h
        size -= 4
    font = _font(size, text)
    return font, _wrap(draw, text, font, max_w), _text_size(draw, "Ay", font)[1]


def _draw_centered_block(draw, lines, font, line_h, cx, top, fill="white"):
    y = top
    for ln in lines:
        w, _ = _text_size(draw, ln, font)
        draw.text((cx - w / 2, y), ln, font=font, fill=fill,
                  stroke_width=2, stroke_fill=(0, 0, 0, 160))
        y += int(line_h * 1.18)
    return y


def _cover_to_canvas(cover: Path) -> Image.Image:
    """Blurred-extended 16:9 fill with the cover readable on top (album layout)."""
    src = Image.open(cover).convert("RGB")
    # Blurred background: scale to cover the canvas, then blur + darken.
    bg = src.copy()
    scale = max(W / bg.width, H / bg.height) * 1.1
    bg = bg.resize((int(bg.width * scale), int(bg.height * scale)))
    left = (bg.width - W) // 2
    top = (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(28))
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    # Sharp cover centered.
    fg = src.copy()
    fg_size = int(H * 0.82)
    fg.thumbnail((fg_size, fg_size))
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return bg


def _yt_canvas(yt_thumb: Path) -> Image.Image:
    img = Image.open(yt_thumb).convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)))
    left = (img.width - W) // 2
    top = (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    # Darken with a vertical gradient (stronger at center for text legibility).
    overlay = Image.new("L", (1, H), 0)
    for y in range(H):
        # darkest in the vertical middle band
        d = 1 - abs((y - H / 2) / (H / 2))
        overlay.putpixel((0, y), int(120 * d + 40))
    overlay = overlay.resize((W, H))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(black, img, overlay)


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


def make_cinematic(title: str, yt_thumb: Path | None, bg_color, out: Path) -> Path:
    canvas = _yt_canvas(yt_thumb) if yt_thumb else Image.new("RGB", (W, H), tuple(bg_color))
    draw = ImageDraw.Draw(canvas)
    font, lines, line_h = _fit_title(draw, title, int(W * 0.86), int(H * 0.5), 110)
    block_h = int(line_h * 1.18 * len(lines))
    top = int(H * 0.42) - block_h // 2
    end_y = _draw_centered_block(draw, lines, font, line_h, W / 2, top)
    # "Instrumental" label centered under the title.
    label_font = _font(46, "Instrumental")
    lw, lh = _text_size(draw, "Instrumental", label_font)
    draw.text(((W - lw) / 2, end_y + 18), "Instrumental", font=label_font,
              fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 160))
    canvas.save(out)
    return out


def make_album(artist: str, title: str, cover: Path | None, bg_color, out: Path) -> Path:
    canvas = _cover_to_canvas(cover) if cover else Image.new("RGB", (W, H), tuple(bg_color))
    draw = ImageDraw.Draw(canvas)

    # Top-left "instrumental" tag.
    tag_font = _font(34, "instrumental")
    tw, th = _text_size(draw, "instrumental", tag_font)
    pad = 16
    draw.rectangle([40, 40, 40 + tw + pad * 2, 40 + th + pad * 2], fill=(0, 0, 0, 180))
    draw.text((40 + pad, 40 + pad), "instrumental", font=tag_font, fill="white")

    # Bottom-left stacked artist + title.
    title_font, title_lines, line_h = _fit_title(draw, title, int(W * 0.9), int(H * 0.4), 88)
    artist_font = _font(40, artist or " ")
    block_h = int(line_h * 1.18 * len(title_lines))
    base_y = H - 56 - block_h
    if artist:
        aw, ah = _text_size(draw, artist, artist_font)
        draw.text((56, base_y - ah - 12), artist, font=artist_font,
                  fill=(235, 235, 235), stroke_width=2, stroke_fill=(0, 0, 0, 160))
    y = base_y
    for ln in title_lines:
        draw.text((56, y), ln, font=title_font, fill="white",
                  stroke_width=2, stroke_fill=(0, 0, 0, 160))
        y += int(line_h * 1.18)
    canvas.save(out)
    return out


def make_thumbnail(layout: str, meta: dict, work_dir: Path,
                   cover: Path | None, bg_color, out: Path) -> Path:
    title = meta.get("title") or "Untitled"
    artist = meta.get("artist") or ""
    if layout == "album":
        return make_album(artist, title, cover, bg_color, out)
    yt = download_yt_thumb(meta.get("yt_thumbnail_url"), work_dir)
    return make_cinematic(title, yt, bg_color, out)
