# norchid

Turn a YouTube link into a finished **karaoke / instrumental video** — Spotify-style scrolling
lyrics over an album-colored background — plus a matching thumbnail. Local, free, scriptable.

Replaces the old manual chain (x-minus instrumental → Gaudio "noraebang" scrolling lyrics →
mask/composite in Premiere → export → hand-made thumbnail) with one local web tool.

> Origin: built to recreate (for free, forever) the workflow that Gaudio Lab's **GTS / noraebang**
> lyric-sync demo used to provide before it went B2B-only. Primary use case: **Japanese songs**,
> but script-agnostic (romaji / kana / kanji / Hangul / Latin).

## What it does

```
YouTube URL
  → [1] download audio + metadata        (yt-dlp)
  → [2] separate instrumental (+vocal)   (audio-separator, both stems in one pass)
  → [3] fetch synced lyrics              (LRCLIB)  + cover art (iTunes/Deezer)
  → [ REVIEW: edit lyrics, nudge offset, pick thumbnail layout ]
  → [4] render scrolling-lyrics video    (LRC → ASS → ffmpeg/libass, 1080p60)
  → [5] generate thumbnail               (Pillow)
  → out: video.mp4 + thumbnail.png + instrumental.wav
```

## Quick start

System deps: **ffmpeg** (built with libass) and a CUDA GPU (optional — CPU works,
slower). Fonts are vendored in `assets/fonts/` (Noto Sans CJK + Montserrat ExtraBold).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .                      # for GPU separation also: pip install "audio-separator[gpu]"

# Web UI (paste URL → review lyrics/offset/layout → render):
uvicorn app.main:app --reload         # open http://localhost:8000

# Or headless CLI (auto-picks best LRC; outputs to ./outputs/):
python -m app.cli "https://www.youtube.com/watch?v=…" \
    --layout album --vocal-mode instrumental --offset 0
```

Outputs: `video.mp4` (1080p60), `thumbnail.png` (1280×720), `instrumental.wav`.

## Status

**Built through Phase 3** (renderer spike → CLI pipeline → web UI + review → polish).
Verified end-to-end on Japanese material (CJK + Hangul lyrics render with no tofu;
BS-Roformer separation on GPU ~40s/song). See `docs/`:
- [`PRD.md`](docs/PRD.md) — what we're building and why
- [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design, pipeline, API, rendering technique
- [`BRANDING.md`](docs/BRANDING.md) — visual spec (colors, fonts, thumbnail layouts)
- [`ROADMAP.md`](docs/ROADMAP.md) — build phases (start at Phase 0: the renderer spike)
- [`DECISIONS.md`](docs/DECISIONS.md) — locked decisions + rationale

## Legal note

Downloading from YouTube and publishing karaoke versions of copyrighted songs is a legal gray
area (personal/transformative use vs. rights holders). This tool is for personal use; what you
publish is your call. See PRD §1.7.
