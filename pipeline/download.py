"""yt-dlp: download best audio + metadata for a YouTube URL.

docs/ARCHITECTURE.md step [1]. Produces a wav in the job workspace and a meta
dict (title, artist, duration, yt_thumbnail_url) used downstream for lyrics,
cover-art lookup and the cinematic thumbnail.
"""

from __future__ import annotations

import re
from pathlib import Path

from yt_dlp import YoutubeDL


def _split_artist_title(info: dict) -> tuple[str, str]:
    """Best-effort artist/title from yt-dlp's (often messy) metadata."""
    title = (info.get("track") or "").strip()
    artist = (info.get("artist") or info.get("creator") or "").strip()
    if title and artist:
        return artist, title

    raw = (info.get("title") or "").strip()
    # Strip common noise: "(Official Video)", "[MV]", "feat." kept.
    cleaned = re.sub(r"\s*[\(\[][^)\]]*(official|video|audio|mv|lyric|m/?v)[^)\]]*[\)\]]",
                     "", raw, flags=re.I).strip()
    # "Artist - Title" / "Artist / Title" pattern.
    m = re.match(r"^(.*?)\s*[-–—/]\s*(.*)$", cleaned)
    if m:
        a, t = m.group(1).strip(), m.group(2).strip()
        artist, title = (artist or a), (title or t)
    else:
        artist, title = (artist or info.get("uploader", "").strip()), (title or cleaned or raw)

    # Drop a redundant leading "Artist / " or "Artist - " from the title.
    if artist:
        title = re.sub(rf"^{re.escape(artist)}\s*[-–—/]\s*", "", title, flags=re.I).strip()
    return artist, title or cleaned or raw


def download(url: str, work_dir: Path, progress_cb=None) -> dict:
    """Download audio to ``work_dir/source.wav`` and return a metadata dict."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(work_dir / "source.%(ext)s")

    def _hook(d):
        if progress_cb and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                progress_cb(done / total)

    opts = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "wav"},
        ],
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    artist, title = _split_artist_title(info)
    source = work_dir / "source.wav"
    if not source.exists():  # postprocessor names it source.wav; guard anyway
        cands = list(work_dir.glob("source.*"))
        source = cands[0] if cands else source

    return {
        "title": title,
        "artist": artist,
        "duration": float(info.get("duration") or 0.0),
        "yt_thumbnail_url": info.get("thumbnail"),
        "source_path": str(source),
        "webpage_url": info.get("webpage_url", url),
    }
