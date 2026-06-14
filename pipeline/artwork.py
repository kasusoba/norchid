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


def itunes_lookup(artist: str, title: str, country: str | None = None) -> dict | None:
    """First iTunes song result for artist+title (cover + native trackName)."""
    params = {"term": f"{artist} {title}".strip(), "entity": "song", "limit": 3}
    if country:
        params["country"] = country
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=20.0) as c:
            results = c.get("https://itunes.apple.com/search", params=params).json().get("results", [])
        return results[0] if results else None
    except Exception:
        return None


def _itunes_cover(artist: str, title: str) -> str | None:
    res = itunes_lookup(artist, title)
    art = res.get("artworkUrl100") if res else None
    return art.replace("100x100bb", "1000x1000bb") if art else None


def _has_cjk(text: str) -> bool:
    for ch in text or "":
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF
                or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF):
            return True
    return False


def native_title(artist: str, title: str) -> str | None:
    """A CJK 'native' track title from iTunes' JP store, if it differs from
    ``title``. Returned as an editable suggestion (the user can fix/clear it)."""
    res = itunes_lookup(artist, title, country="JP")
    if not res:
        return None
    name = (res.get("trackName") or "").strip()
    if name and _has_cjk(name) and name.lower() != (title or "").strip().lower():
        return name
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


def _sat(rgb) -> float:
    return colorsys.rgb_to_hsv(*(x / 255 for x in rgb[:3]))[1]


def _far(rgb, existing, thresh=46) -> bool:
    return all(sum((a - b) ** 2 for a, b in zip(rgb, e)) ** 0.5 > thresh for e in existing)


def palette(cover_path: Path, n: int = 6) -> list[tuple[int, int, int]]:
    """Prominent distinct colours from the cover — the muted dominant *and* the
    vibrant accents, so the user can pick one the auto-pick would skip."""
    img = Image.open(cover_path).convert("RGB")
    img.thumbnail((180, 180))
    quant = img.quantize(colors=16, method=Image.Quantize.MEDIANCUT).convert("RGB")
    colors = sorted(quant.getcolors(maxcolors=4096) or [], reverse=True)  # by count
    if not colors:
        return [dominant_color(cover_path)]
    out: list[tuple] = [dominant_color(cover_path)]
    # Inject the most saturated prominent colour (the accent) near the front.
    vivid = max(colors, key=lambda c: _sat(c[1]) * (c[0] ** 0.4))[1]
    if _far(vivid, out):
        out.append(vivid)
    for _, rgb in colors:
        if len(out) >= n:
            break
        if _far(rgb, out):
            out.append(rgb)
    return out[:n]


def mute_for_pill(rgb) -> tuple[int, int, int]:
    """A muted mid-tone of a colour for the 'Instrumental' pill."""
    h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in rgb[:3]))
    s = min(s, 0.6)
    v = 0.62
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s, v))


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
    pal = palette(cover) if cover else [(38, 48, 66)]
    rgb = clamp_color(pal[0]) if cover else (38, 48, 66)
    bg = make_flat_background(rgb, work_dir / "background.png")
    return {"cover": cover, "cover_url": url, "bg_color": rgb, "background": bg,
            "palette": pal}
