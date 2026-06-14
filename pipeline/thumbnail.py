"""Cinematic thumbnail (Pillow) — matches the reference look (BRANDING.md §2).

Full-bleed darkened YouTube thumbnail; large clean white title (no glow), an
optional Japanese/secondary title beneath it (rendered in 「」), and a filled
"Instrumental" pill whose colour is sampled from the background, with a soft
drop shadow. Output 1280x720 PNG, no duration badge.
"""

from __future__ import annotations

import colorsys
import io
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app import config
from pipeline import artwork

W, H = config.THUMB_W, config.THUMB_H
UA = "norchid/0.1"


# --- fonts ----------------------------------------------------------------
def _has_cjk(text: str) -> bool:
    for ch in text or "":
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
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _fit(text, max_w, max_h, start_size, min_size=26):
    size = start_size
    while size > min_size:
        font = _font(size, text)
        lines = _wrap(text, font, max_w)
        lh = _measure("Ay", font)[1]
        if int(lh * 1.14 * len(lines)) <= max_h and \
                all(_measure(ln, font)[0] <= max_w for ln in lines):
            return font, lines, lh
        size -= 4
    font = _font(min_size, text)
    return font, _wrap(text, font, max_w), _measure("Ay", font)[1]


def _pill_color(yt_thumb: Path | None, bg_color) -> tuple[int, int, int]:
    """A muted mid-tone sampled from the background image (ref look)."""
    rgb = artwork.dominant_color(yt_thumb) if yt_thumb else tuple(bg_color)
    r, g, b = (x / 255 for x in rgb[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(s, 0.55)          # mute saturation
    v = 0.62                  # consistent mid brightness
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return tuple(round(c * 255) for c in (r, g, b))


def _image_canvas(img: Image.Image, blur: int = 0, brightness: float = 0.78) -> Image.Image:
    """Scale + center-crop to fill 16:9, darken (+ optional blur) for white text."""
    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)))
    left = (img.width - W) // 2
    top = (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    img = ImageEnhance.Brightness(img).enhance(brightness)
    # A stronger center band so the white title reads cleanly.
    overlay = Image.new("L", (1, H), 0)
    for y in range(H):
        d = 1 - abs((y - H * 0.5) / (H / 2))
        overlay.putpixel((0, y), int(120 * max(0, d)))
    overlay = overlay.resize((W, H))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(black, img, overlay).convert("RGBA")


def _yt_canvas(yt_thumb: Path) -> Image.Image:
    return _image_canvas(Image.open(yt_thumb).convert("RGB"))


def _cover_canvas(cover: Path) -> Image.Image:
    """Album cover blurred + extended to fill 16:9, as a background for the title."""
    return _image_canvas(Image.open(cover).convert("RGB"), blur=22, brightness=0.62)


def _cover_boxed_canvas(cover: Path) -> Image.Image:
    """Sharp album cover boxed in the centre over a blurred-extended version of
    itself; the centre is darkened so the cinematic title reads on top."""
    src = Image.open(cover).convert("RGB")
    canvas = _image_canvas(src, blur=30, brightness=0.5).convert("RGB")  # blurred bg
    box = int(H * 0.84)
    fg = src.copy(); fg.thumbnail((box, box))
    canvas.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    # Darken toward the centre so the white title/pill stay legible over the cover.
    overlay = Image.new("L", (1, H), 0)
    for y in range(H):
        d = 1 - abs((y - H * 0.5) / (H / 2))
        overlay.putpixel((0, y), int(150 * max(0, d) ** 0.7))
    canvas = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)),
                             canvas, overlay.resize((W, H)))
    return canvas.convert("RGBA")


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


# --- drawing --------------------------------------------------------------
def _draw_center_block(canvas, lines, font, lh, top, fill=(255, 255, 255, 255)):
    d = ImageDraw.Draw(canvas)
    y = top
    for ln in lines:
        d.text((W // 2, y), ln, font=font, fill=fill, anchor="ma")
        y += int(lh * 1.14)
    return y


def _pill(canvas, text, font, top, fill_rgb, pad=(34, 15)):
    tw, th = _measure(text, font)
    bw, bh = tw + pad[0] * 2, th + pad[1] * 2
    x = W / 2 - bw / 2
    y = top
    r = bh / 2
    # Soft drop shadow.
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x, y + 7, x + bw, y + bh + 7],
                                         radius=r, fill=(0, 0, 0, 150))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(9)))
    # Pill.
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([x, y, x + bw, y + bh], radius=r,
                                            fill=tuple(fill_rgb) + (255,))
    canvas.alpha_composite(layer)
    bbox = font.getbbox(text)
    ImageDraw.Draw(canvas).text((x + pad[0] - bbox[0], y + pad[1] - bbox[1]),
                                text, font=font, fill=(255, 255, 255, 255))
    return bh


def _bracket_jp(text: str) -> str:
    t = text.strip()
    if _has_cjk(t) and not (t.startswith("「") or t.startswith("『")):
        return f"「{t}」"
    return t


def make_cinematic(title: str, secondary: str | None, yt_thumb: Path | None,
                   bg_color, out: Path, title_size: int = config.THUMB_TITLE_SIZE,
                   cover: Path | None = None, bg_source: str = "youtube",
                   pill_size: int = config.THUMB_PILL_SIZE, pill_color=None,
                   pill_gap: int = config.THUMB_PILL_GAP) -> Path:
    # Background: YouTube thumbnail (default), cover blurred-fill, or cover boxed.
    have_cover = cover and Path(cover).exists()
    if bg_source == "cover_boxed" and have_cover:
        canvas, pill_src = _cover_boxed_canvas(cover), cover
    elif bg_source == "cover" and have_cover:
        canvas, pill_src = _cover_canvas(cover), cover
    elif yt_thumb:
        canvas, pill_src = _yt_canvas(yt_thumb), yt_thumb
    else:
        canvas, pill_src = Image.new("RGBA", (W, H), tuple(bg_color) + (255,)), None
    pill_rgb = tuple(pill_color) if pill_color else _pill_color(pill_src, bg_color)

    secondary = (secondary or "").strip()
    has_sec = bool(secondary)

    # Fit main title (and secondary) to width, starting from the chosen size.
    title_size = max(40, min(190, int(title_size or config.THUMB_TITLE_SIZE)))
    main_font, main_lines, main_lh = _fit(title, int(W * 0.86), int(H * 0.46),
                                          title_size, min_size=40)
    sec_font = sec_lines = None
    sec_h = 0
    if has_sec:
        sec_text = _bracket_jp(secondary)
        sec_size = max(34, int(main_font.size * 0.58))
        sec_font, sec_lines, sec_lh = _fit(sec_text, int(W * 0.86), int(H * 0.22), sec_size)
        sec_h = int(sec_lh * 1.14 * len(sec_lines)) + 8

    pill_size = max(20, min(80, int(pill_size or config.THUMB_PILL_SIZE)))
    pill_gap = max(0, min(160, int(pill_gap if pill_gap is not None else config.THUMB_PILL_GAP)))
    pill_font = _font(pill_size, "Instrumental")
    pill_h = _measure("Instrumental", pill_font)[1] + 30
    main_h = int(main_lh * 1.14 * len(main_lines))
    stack_h = main_h + sec_h + pill_gap + pill_h
    top = int(H * 0.50 - stack_h / 2)

    y = _draw_center_block(canvas, main_lines, main_font, main_lh, top)
    if has_sec:
        y = _draw_center_block(canvas, sec_lines, sec_font, sec_lh, y + 8,
                               fill=(244, 244, 246, 255))
    _pill(canvas, "Instrumental", pill_font, y + pill_gap, pill_rgb,
          pad=(round(pill_size * 0.9), round(pill_size * 0.4)))
    canvas.convert("RGB").save(out)
    return out


def make_thumbnail(meta: dict, work_dir: Path, bg_color, out: Path,
                   yt_thumb: Path | None = None, secondary: str | None = None,
                   title_size: int = config.THUMB_TITLE_SIZE,
                   cover: Path | None = None, bg_source: str = "youtube",
                   pill_size: int = config.THUMB_PILL_SIZE, pill_color=None,
                   title_main: str | None = None,
                   pill_gap: int = config.THUMB_PILL_GAP) -> Path:
    title = (title_main or "").strip() or meta.get("title") or "Untitled"
    if yt_thumb is None:
        yt_thumb = download_yt_thumb(meta.get("yt_thumbnail_url"), work_dir)
    sec = secondary if secondary is not None else meta.get("title_secondary")
    return make_cinematic(title, sec, yt_thumb, bg_color, out, title_size=title_size,
                          cover=cover, bg_source=bg_source, pill_size=pill_size,
                          pill_color=pill_color, pill_gap=pill_gap)
