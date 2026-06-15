"""audio-separator: split source into instrumental + vocal stems in one pass.

docs/ARCHITECTURE.md step [2], DECISIONS D5/D6/D18. Both stems are produced
together so the guide-vocal option needs no re-separation. The model is chosen
by the caller (UI dropdown / CLI flag) before this runs.
"""

from __future__ import annotations

import contextlib
import importlib
import shutil
import subprocess
from pathlib import Path

from app import config


def _transcode(source: Path, dst: Path, what: str) -> Path:
    """Transcode any ffmpeg-readable audio to a 16-bit PCM wav at ``dst``."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source), "-c:a", "pcm_s16le", str(dst)],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        msg = e.stderr.decode("utf-8", "ignore")[-400:] if e.stderr else ""
        raise RuntimeError(f"Could not read the supplied {what} file: {msg}") from e
    if not dst.exists():
        raise RuntimeError(f"Supplied {what} produced no audio.")
    return dst


def import_instrumental(source: Path, work_dir: Path,
                        vocal_source: Path | None = None) -> dict:
    """Use a user-supplied instrumental instead of separating.

    Transcodes ``source`` to ``work_dir/instrumental.wav`` (keeping the downstream
    "instrumental.wav" invariant). When ``vocal_source`` is also given it becomes
    ``vocals.wav`` so guide-vocal mode works; otherwise there is no vocal stem and
    the job is instrumental-only.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    inst = _transcode(source, work_dir / "instrumental.wav", "instrumental")
    voc = _transcode(vocal_source, work_dir / "vocals.wav", "vocal") if vocal_source else None
    return {"instrumental": inst, "vocal": voc, "model": "user-supplied"}


def _resolve_model(model_key: str) -> str:
    spec = config.SEP_MODELS.get(model_key) or config.SEP_MODELS[config.DEFAULT_SEP_MODEL]
    return spec["filename"]


@contextlib.contextmanager
def _tqdm_progress(progress_cb, lo=0.2, hi=1.0):
    """Patch audio-separator's per-chunk tqdm so we can stream real progress.

    The separators iterate chunks under a tqdm bar; we subclass tqdm to forward
    n/total into ``progress_cb`` mapped onto the [lo, hi] band of the job stage.
    """
    if not progress_cb:
        yield
        return
    import tqdm as _t

    class _CB(_t.std.tqdm):
        def update(self, n=1):
            r = super().update(n)
            try:
                if self.total:
                    progress_cb(lo + (hi - lo) * min(1.0, self.n / self.total))
            except Exception:
                pass
            return r

    saved = []
    for name in ("mdxc_separator", "mdx_separator", "vr_separator"):
        try:
            m = importlib.import_module(f"audio_separator.separator.architectures.{name}")
            if hasattr(m, "tqdm"):
                saved.append((m, m.tqdm))
                m.tqdm = _CB
        except Exception:
            pass
    try:
        yield
    finally:
        for m, orig in saved:
            m.tqdm = orig


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
        progress_cb(0.2)

    with _tqdm_progress(progress_cb, lo=0.2, hi=0.99):
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
