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
LYRIC_FONT = "Noto Sans CJK JP"   # full CJK: Latin/romaji + kana/kanji + Hangul
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


def use_gpu() -> bool:
    """Whether a CUDA GPU should be used for separation."""
    if os.environ.get("NORCHID_FORCE_CPU"):
        return False
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False
