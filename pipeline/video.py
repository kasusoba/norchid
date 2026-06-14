"""ffmpeg composition: burn ASS lyrics over a flat background + mux audio.

docs/ARCHITECTURE.md §4 / §4.3. Picks h264_nvenc when a CUDA GPU is present
(the 60fps render is the heavy step) and falls back to libx264.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app import config


def _escape_filter_path(p: str) -> str:
    """Escape a path for use inside an ffmpeg filtergraph argument."""
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _has_nvenc() -> bool:
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, check=True,
        ).stdout
        return "h264_nvenc" in out and config.use_gpu()
    except Exception:
        return False


def build_audio_track(
    instrumental: Path, vocal: Path | None, vocal_mode: str, out_path: Path,
    gain: float = config.GUIDE_VOCAL_GAIN,
) -> Path:
    """Produce the render's audio track.

    - "instrumental": copy the instrumental stem as-is.
    - "guide": amix instrumental + low-gain vocal for sing-along practice (D7).
    """
    if vocal_mode == "guide" and vocal and vocal.exists():
        cmd = [
            "ffmpeg", "-y", "-i", str(instrumental), "-i", str(vocal),
            "-filter_complex",
            f"[1:a]volume={gain}[v];[0:a][v]amix=inputs=2:duration=longest:normalize=0[a]",
            "-map", "[a]", "-c:a", "pcm_s16le", str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path
    return instrumental


def probe_duration(path: Path) -> float:
    """Duration in seconds via ffprobe (authoritative vs. yt-dlp metadata)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def compose_video(
    background: Path,
    audio: Path,
    ass_path: Path | None,
    out_path: Path,
    fps: int = config.FPS,
    fonts_dir: Path = config.FONTS_DIR,
    duration: float = 0.0,
    progress_cb=None,
) -> Path:
    """Burn the ASS subtitle over the still background and mux the audio.

    If ``ass_path`` is None (no lyrics found), the flat background is rendered
    with audio only. ``duration`` enables a live progress callback (0..1).
    """
    vf = None
    if ass_path is not None:
        vf = (
            f"ass={_escape_filter_path(str(ass_path))}"
            f":fontsdir={_escape_filter_path(str(fonts_dir))}"
        )
    if _has_nvenc():
        venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0"]
    else:
        venc = ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(background),
        "-i", str(audio),
        *(["-vf", vf] if vf else []),
        "-r", str(fps),
        *venc,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(out_path),
    ]
    _run_ffmpeg(cmd, duration=duration, progress_cb=progress_cb)
    return out_path


def _run_ffmpeg(cmd: list[str], duration: float = 0.0, progress_cb=None) -> None:
    """Run ffmpeg, parsing -progress for a live callback; surface stderr on fail."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.stdout is not None:
        for line in proc.stdout:
            if progress_cb and duration > 0 and line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                    progress_cb(min(0.999, (us / 1_000_000) / duration))
                except ValueError:
                    pass
    _, stderr = proc.communicate()
    if proc.returncode != 0:
        tail = "\n".join((stderr or "").strip().splitlines()[-25:])
        raise RuntimeError(f"ffmpeg failed:\n{tail}")


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH (need a build with libass).")
