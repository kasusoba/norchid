"""Cover art + Spotify-style background color.

docs/ARCHITECTURE.md §4.2 / BRANDING.md. Fetch the album cover (iTunes, then
Deezer), compute a dominant color, apply the luma/saturation clamp so white
lyrics stay legible, and emit a flat 1920x1080 background PNG.
"""

from __future__ import annotations

import colorsys
import io
from pathlib import Path

import httpx
from PIL import Image

from app import config

UA = "norchid/0.1"


def fetch_cover(artist: str, title: str, work_dir: Path) -> tuple[Path | None, str | None]:
    """Download album cover to work_dir/cover.jpg. Returns (path, source_url)."""
    url = _itunes_cover(artist, title) or _deezer_cover(artist, title)
    if not url:
        return None, None
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=20.0) as c:
            data = c.get(url).content
        path = work_dir / "cover.jpg"
        Image.open(io.BytesIO(data)).convert("RGB").save(path, "JPEG", quality=92)
        return path, url
    except Exception:
        return None, None


def _itunes_cover(artist: str, title: str) -> str | None:
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=20.0) as c:
            r = c.get("https://itunes.apple.com/search",
                      params={"term": f"{artist} {title}".strip(),
                              "entity": "song", "limit": 3})
            results = r.json().get("results", [])
        if not results:
            return None
        art = results[0].get("artworkUrl100")
        # Upgrade the thumbnail to a large render.
        return art.replace("100x100bb", "1000x1000bb") if art else None
    except Exception:
        return None


def _deezer_cover(artist: str, title: str) -> str | None:
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=20.0) as c:
            r = c.get("https://api.deezer.com/search",
                      params={"q": f"{artist} {title}".strip()})
            data = r.json().get("data", [])
        if not data:
            return None
        album = data[0].get("album", {})
        return album.get("cover_xl") or album.get("cover_big")
    except Exception:
        return None


def dominant_color(cover_path: Path) -> tuple[int, int, int]:
    """Most prominent non-extreme color of the cover (quantized)."""
    img = Image.open(cover_path).convert("RGB")
    img.thumbnail((128, 128))
    quant = img.quantize(colors=8, method=Image.Quantize.FASTOCTREE).convert("RGB")
    colors = quant.getcolors(maxcolors=128) or []
    colors.sort(reverse=True)  # by count
    for count, rgb in colors:
        L = _luma(rgb)
        if 0.06 < L < 0.95:  # skip near-black / near-white swatches
            return rgb
    # Fallback: plain average.
    avg = img.resize((1, 1)).getpixel((0, 0))
    return avg[:3]


def _luma(rgb) -> float:
    r, g, b = rgb[:3]
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def clamp_color(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Luma/saturation clamp for legible white text (BRANDING §4)."""
    r, g, b = (x / 255.0 for x in rgb[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    # Mute extreme saturation.
    if s > 0.8:
        s *= 0.8

    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    L = 0.299 * r + 0.587 * g + 0.114 * b
    # Too light -> darken toward a calm mid-dark field.
    if L > 0.55:
        scale = 0.40 / max(L, 1e-3)
        r, g, b = r * scale, g * scale, b * scale
    # Too dark -> lift slightly off pure black.
    elif L < 0.10:
        lift = 0.12
        r, g, b = r + lift, g + lift, b + lift
    return tuple(min(255, max(0, round(c * 255))) for c in (r, g, b))


def make_flat_background(rgb, path: Path,
                         width: int = config.WIDTH, height: int = config.HEIGHT) -> Path:
    Image.new("RGB", (width, height), tuple(rgb)).save(path)
    return path


def _fill(img: Image.Image, width: int, height: int) -> Image.Image:
    """Scale + center-crop an image to exactly cover width x height."""
    scale = max(width / img.width, height / img.height)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))
    left = (img.width - width) // 2
    top = (img.height - height) // 2
    return img.crop((left, top, left + width, top + height))


def make_cover_background(cover: Path, path: Path, rgb=(20, 20, 28),
                         width: int = config.WIDTH, height: int = config.HEIGHT) -> Path:
    """Album cover scaled to fill 16:9, heavily blurred + darkened (Spotify look)."""
    from PIL import ImageEnhance, ImageFilter
    img = _fill(Image.open(cover).convert("RGB"), width, height)
    img = img.filter(ImageFilter.GaussianBlur(48))
    img = ImageEnhance.Brightness(img).enhance(0.5)
    img = ImageEnhance.Color(img).enhance(0.9)
    # Slight dark vignette toward the edges keeps centered text crisp.
    img = Image.blend(img, Image.new("RGB", (width, height), tuple(rgb)), 0.18)
    img.save(path)
    return path


def make_image_background(src: Path, path: Path,
                          width: int = config.WIDTH, height: int = config.HEIGHT) -> Path:
    """A 16:9 source image (e.g. YouTube thumbnail) darkened for white text."""
    from PIL import ImageEnhance, ImageFilter
    img = _fill(Image.open(src).convert("RGB"), width, height)
    img = img.filter(ImageFilter.GaussianBlur(6))
    img = ImageEnhance.Brightness(img).enhance(0.45)
    img.save(path)
    return path


def background_for(artist: str, title: str, work_dir: Path) -> dict:
    """Full step: cover -> dominant -> clamp -> flat bg PNG.

    Returns {"cover": Path|None, "cover_url": str|None,
             "bg_color": (r,g,b), "background": Path}.
    """
    cover, url = fetch_cover(artist, title, work_dir)
    if cover:
        rgb = clamp_color(dominant_color(cover))
    else:
        rgb = (38, 48, 66)  # neutral fallback field
    bg = make_flat_background(rgb, work_dir / "background.png")
    return {"cover": cover, "cover_url": url, "bg_color": rgb, "background": bg}
