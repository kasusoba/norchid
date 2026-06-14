"""Shared paths and tunables for norchid."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS_DIR = ASSETS / "fonts"
WORKSPACE = ROOT / "workspace"
OUTPUTS = ROOT / "outputs"

# Font family names (must match the vendored files; see assets/fonts/).
LYRIC_FONT = "Noto Sans CJK JP Black"   # heavy CJK face for lyrics (not skinny)
TITLE_FONT = "Montserrat ExtraBold"
TITLE_FONT_CJK = "Noto Sans CJK JP"  # thumbnail title fallback for CJK text

# Vendored font file paths (used by Pillow for thumbnails).
NOTO_CJK_PATH = FONTS_DIR / "NotoSansCJKjp-Bold.otf"
MONTSERRAT_PATH = FONTS_DIR / "Montserrat-ExtraBold.ttf"

# Render settings (docs/DECISIONS.md D14).
WIDTH = 1920
HEIGHT = 1080
FPS = 60
THUMB_W = 1280
THUMB_H = 720
THUMB_TITLE_SIZE = 110   # default cinematic title start size (px), tunable in review

# Scrolling-lyrics model — shared by the ASS renderer AND the browser preview
# (served via /api/render-config) so they look the same. Spotify-style: lines
# hold centered, then scroll up one slot over TRANSITION_MS at each line change.
SCROLL = {
    "font_size": 60,        # px (PlayResY space)
    "line_spacing": 104,    # px between line centers
    "visible_radius": 6,    # lines emitted above/below active (covers 1080 + off-screen)
    "transition_ms": 240,   # scroll/handoff duration at each line change (snappy)
    "alpha_active": 0.0,    # 0 = opaque
    "alpha_inactive": 0.55, # 0.55 transparent == 45% opacity (D10)
}

# Video background modes (review step). "color" = flat album color (default),
# "cover" = album art blurred+darkened, "thumbnail" = YouTube thumb darkened.
BG_MODES = {
    "color": "Flat album color",
    "cover": "Album cover (blurred)",
    "thumbnail": "Video thumbnail (dark)",
}
DEFAULT_BG_MODE = "color"

# Separation models exposed in the UI dropdown (docs/DECISIONS.md D5/D18).
# Default = BS-Roformer ep_317 (Viperx-1297), the top-SDR general Roformer; it
# emits both Vocals + Instrumental in one pass (needed for guide-vocal, D6).
SEP_MODELS = {
    "roformer": {
        "label": "BS-Roformer (best quality, slower)",
        "filename": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    },
    "roformer_inst": {
        "label": "MelBand Roformer Inst (cleanest instrumental)",
        "filename": "melband_roformer_inst_v2.ckpt",
    },
    "mdxnet": {
        "label": "MDX-NET Inst HQ (faster draft)",
        "filename": "UVR-MDX-NET-Inst_HQ_3.onnx",
    },
}
DEFAULT_SEP_MODEL = "roformer"

# Guide-vocal mix gain (docs/DECISIONS.md D7).
GUIDE_VOCAL_GAIN = 0.15


def scroll_for(font_size: int | None) -> dict:
    """Scroll geometry for a chosen lyric font size (line spacing scales with it)."""
    base = SCROLL
    if not font_size:
        return base
    fs = max(28, min(110, int(font_size)))
    ratio = base["line_spacing"] / base["font_size"]
    return {**base, "font_size": fs, "line_spacing": round(fs * ratio)}


def use_gpu() -> bool:
    """Whether a CUDA GPU should be used for separation."""
    if os.environ.get("NORCHID_FORCE_CPU"):
        return False
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False
