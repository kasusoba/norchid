"""End-to-end pipeline, split into the two halves the review step sits between.

`prepare`  : download -> separate -> lyrics -> cover/bg  (up to awaiting_review)
`finalize` : render ASS -> compose video -> thumbnail -> collect outputs

Both halves take small callbacks (log / stage / progress) so the CLI and the
FastAPI worker can drive the same code. See docs/ARCHITECTURE.md §2.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from app import config
from pipeline import ass_render, artwork, download, lyrics, separate, thumbnail, video

Log = Callable[[str], None]
Stage = Callable[[str], None]
Progress = Callable[[float], None]


def _noop(*_a, **_k):
    pass


def prepare(url: str, work_dir: Path, sep_model: str = config.DEFAULT_SEP_MODEL,
            instrumental_path: Path | None = None, vocal_path: Path | None = None,
            log: Log = _noop, stage: Stage = _noop, progress: Progress = _noop) -> dict:
    """Run everything up to (and excluding) the render. Returns review context.

    When ``instrumental_path`` is given the slow separation step is skipped and
    that file is used as the instrumental. An optional ``vocal_path`` is used as
    the vocal stem (enabling guide-vocal mode); without it the job is
    instrumental-only. The YouTube URL is still downloaded for metadata, cover
    art and the thumbnail.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    stage("downloading"); progress(0.0)
    log(f"Downloading audio: {url}")
    meta = download.download(url, work_dir, progress_cb=progress)
    log(f"  title='{meta['title']}' artist='{meta['artist']}'")
    source = Path(meta["source_path"])

    stage("separating"); progress(0.0)
    if instrumental_path:
        log(f"Using supplied instrumental ({Path(instrumental_path).name}) — "
            f"skipping separation." +
            (f" + vocal ({Path(vocal_path).name})" if vocal_path else ""))
        sep = separate.import_instrumental(
            Path(instrumental_path), work_dir,
            vocal_source=Path(vocal_path) if vocal_path else None)
        progress(1.0)
    else:
        if not config.use_gpu():
            log("⚠ No CUDA GPU detected — separation will run on CPU (much slower).")
        log(f"Separating stems (model={sep_model}) — this is the slow step…")
        sep = separate.separate(source, work_dir, sep_model, progress_cb=progress)
    log(f"  instrumental={sep['instrumental'].name} vocal="
        f"{sep['vocal'].name if sep['vocal'] else 'none'}")

    duration = video.probe_duration(sep["instrumental"]) or meta["duration"]

    stage("fetching_lyrics"); progress(0.0)
    log("Fetching synced lyrics (LRCLIB) + cover art…")
    candidates = lyrics.search(meta["artist"], meta["title"], duration)
    lrc = lyrics.best_lrc(candidates)
    log(f"  {len(candidates)} lyric candidate(s); synced match="
        f"{'yes' if lrc else 'no'}")

    art = artwork.background_for(meta["artist"], meta["title"], work_dir)
    log(f"  bg_color={art['bg_color']} cover="
        f"{'yes' if art['cover'] else 'fallback'}")

    # Suggest a Japanese/native title for the thumbnail (iTunes), editable later.
    meta["title_secondary"] = artwork.native_title(meta["artist"], meta["title"]) or ""
    if meta["title_secondary"]:
        log(f"  native title suggestion: {meta['title_secondary']}")

    # Build all background variants up front so review can switch instantly.
    yt_thumb = thumbnail.download_yt_thumb(meta.get("yt_thumbnail_url"), work_dir)
    backgrounds = {"color": art["background"]}
    if art["cover"]:
        backgrounds["cover"] = artwork.make_cover_background(
            art["cover"], work_dir / "bg_cover.png", art["bg_color"])
    if yt_thumb:
        backgrounds["thumbnail"] = artwork.make_image_background(
            yt_thumb, work_dir / "bg_thumbnail.png")

    thumbnail.make_cinematic(meta["title"], meta["title_secondary"], yt_thumb,
                             art["bg_color"], work_dir / "thumb_cinematic.png",
                             cover=art["cover"])
    log(f"  backgrounds: {sorted(backgrounds)} | thumbnail: cinematic")
    progress(1.0)

    return {
        "meta": meta,
        "duration": duration,
        "instrumental": sep["instrumental"],
        "vocal": sep["vocal"],
        "sep_model_file": sep["model"],
        "lrc": lrc,
        "lrc_candidates": candidates,
        "cover": art["cover"],
        "cover_url": art["cover_url"],
        "bg_color": art["bg_color"],
        "background": art["background"],
        "backgrounds": backgrounds,
        "palette": art.get("palette", []),
        "yt_thumb": yt_thumb,
    }


def finalize(ctx: dict, work_dir: Path, out_dir: Path, *,
             lrc: str | None, romaji: str | None = None, offset_ms: int = 0,
             vocal_mode: str = "instrumental",
             bg_mode: str = config.DEFAULT_BG_MODE,
             title_secondary: str | None = None, title_main: str | None = None,
             title_size: int = config.THUMB_TITLE_SIZE,
             pill_size: int = config.THUMB_PILL_SIZE, thumb_bg: str = "youtube",
             pill_gap: int = config.THUMB_PILL_GAP, bg_color=None, pill_color=None,
             lyric_size: int | None = None,
             log: Log = _noop, stage: Stage = _noop, progress: Progress = _noop) -> dict:
    """Render the video + thumbnail from the (possibly user-edited) review state."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stage("rendering"); progress(0.0)

    duration = ctx["duration"]
    ass_path = None
    if lrc and lrc.strip():
        ass_path = work_dir / "lyrics.ass"
        n = ass_render.write_ass(lrc, str(ass_path), duration=duration, offset_ms=offset_ms,
                                 romaji=romaji, scroll=config.scroll_for(lyric_size))
        log(f"  wrote ASS with {len(n)} lines (offset={offset_ms}ms, size={lyric_size or 'default'}"
            f"{', +romaji' if romaji and romaji.strip() else ''})")
    else:
        log("  no lyrics — rendering background + audio only")
    progress(0.2)

    backgrounds = ctx.get("backgrounds", {"color": ctx["background"]})
    background = backgrounds.get(bg_mode) or ctx["background"]
    # Flat-colour background uses the user-picked palette colour.
    if bg_mode == "color" and bg_color:
        background = artwork.make_flat_background(tuple(bg_color), work_dir / "background.png")
    log(f"  background mode={bg_mode if bg_mode in backgrounds else 'color (fallback)'}")

    log(f"Building audio track (mode={vocal_mode})…")
    render_audio = video.build_audio_track(
        ctx["instrumental"], ctx["vocal"], vocal_mode, work_dir / "render_audio.wav")
    progress(0.35)

    log("Composing 1080p60 video (ffmpeg + libass)…")
    out_video = work_dir / "output.mp4"
    video.compose_video(background, render_audio, ass_path, out_video,
                        duration=duration,
                        progress_cb=lambda p: progress(0.35 + 0.50 * p))
    progress(0.85)

    log("Generating cinematic thumbnail…")
    out_thumb = work_dir / "thumbnail.png"
    sec = title_secondary if title_secondary is not None \
        else ctx["meta"].get("title_secondary")
    thumbnail.make_thumbnail(ctx["meta"], work_dir, ctx["bg_color"], out_thumb,
                             yt_thumb=ctx.get("yt_thumb"), secondary=sec, title_main=title_main,
                             title_size=title_size, cover=ctx.get("cover"),
                             bg_source=thumb_bg, pill_size=pill_size, pill_color=pill_color,
                             pill_gap=pill_gap)
    progress(0.95)

    outputs = _collect(out_dir, ctx["meta"], out_video, out_thumb, ctx["instrumental"])
    progress(1.0)
    stage("done")
    log(f"Done -> {outputs}")
    return outputs


def _safe(name: str) -> str:
    keep = "-_.() "
    s = "".join(c if c.isalnum() or c in keep else "_" for c in name).strip()
    return s or "norchid"


def _collect(out_dir: Path, meta: dict, video_p: Path, thumb_p: Path,
             instrumental: Path) -> dict:
    base = _safe(f"{meta.get('artist','')} - {meta.get('title','norchid')}".strip(" -"))
    out = {}
    for key, src, ext in (("video", video_p, "mp4"),
                          ("thumbnail", thumb_p, "png"),
                          ("instrumental", instrumental, "wav")):
        if src and Path(src).exists():
            dst = out_dir / f"{base}.{ext}" if key != "instrumental" \
                else out_dir / f"{base} (instrumental).wav"
            shutil.copy2(src, dst)
            out[key] = str(dst)
    return out
