"""audio-separator: split source into instrumental + vocal stems in one pass.

docs/ARCHITECTURE.md step [2], DECISIONS D5/D6/D18. Both stems are produced
together so the guide-vocal option needs no re-separation. The model is chosen
by the caller (UI dropdown / CLI flag) before this runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app import config


def _resolve_model(model_key: str) -> str:
    spec = config.SEP_MODELS.get(model_key) or config.SEP_MODELS[config.DEFAULT_SEP_MODEL]
    return spec["filename"]


def separate(source: Path, work_dir: Path, model_key: str = config.DEFAULT_SEP_MODEL,
             progress_cb=None) -> dict:
    """Separate ``source`` -> instrumental.wav + vocals.wav in ``work_dir``.

    Returns {"instrumental": Path, "vocal": Path, "model": filename}.
    """
    from audio_separator.separator import Separator

    model_file = _resolve_model(model_key)
    model_cache = config.ROOT / "models"
    model_cache.mkdir(exist_ok=True)
    sep_out = work_dir / "_sep"
    sep_out.mkdir(parents=True, exist_ok=True)

    separator = Separator(
        output_dir=str(sep_out),
        model_file_dir=str(model_cache),
        use_autocast=config.use_gpu(),
        output_format="WAV",
    )
    if progress_cb:
        progress_cb(0.05)
    separator.load_model(model_filename=model_file)
    if progress_cb:
        progress_cb(0.15)

    outputs = separator.separate(str(source))
    out_paths = [sep_out / o if not Path(o).is_absolute() else Path(o) for o in outputs]

    instrumental = _pick(out_paths, ("instrumental", "no vocals", "music", "accompaniment"))
    vocal = _pick(out_paths, ("vocals", "vocal"))

    dst_inst = work_dir / "instrumental.wav"
    dst_voc = work_dir / "vocals.wav"
    if instrumental:
        shutil.move(str(instrumental), dst_inst)
    if vocal:
        shutil.move(str(vocal), dst_voc)
    shutil.rmtree(sep_out, ignore_errors=True)

    if not dst_inst.exists():
        raise RuntimeError(f"Separation produced no instrumental stem: {outputs}")
    if progress_cb:
        progress_cb(1.0)
    return {
        "instrumental": dst_inst,
        "vocal": dst_voc if dst_voc.exists() else None,
        "model": model_file,
    }


def _pick(paths: list[Path], needles: tuple[str, ...]) -> Path | None:
    for p in paths:
        low = p.name.lower()
        if any(n in low for n in needles):
            return p
    return None
