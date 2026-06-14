# norchid — Architecture & Technical Spec

## 1. High-level flow

```
        ┌──────────────── browser (Alpine.js SPA) ────────────────┐
        │  paste URL → live progress → REVIEW → download outputs   │
        └───────────────────────────┬─────────────────────────────┘
                                     │ REST + polling
                            ┌────────▼─────────┐
                            │  FastAPI server  │
                            │  + job queue     │
                            └────────┬─────────┘
            single worker thread     │  (heavy steps run one at a time)
  ┌──────────┬───────────────┬───────┴────────┬──────────────┬───────────────┐
  ▼          ▼               ▼                ▼              ▼               ▼
[1] yt-dlp [2] audio-     [3] LRCLIB +     (PAUSE:        [4] LRC→ASS    [5] Pillow
 download   separator      iTunes/Deezer    review        → ffmpeg        thumbnail
 audio+meta both stems     lyrics + art     lyrics/offset/ render MP4      (2 layouts)
            (1 pass)                        layout)        1080p60
```

## 2. Job lifecycle (state machine)

```
queued → downloading → separating → fetching_lyrics → awaiting_review
                                                            │ (user confirms)
                                                            ▼
                                                        rendering → done
   (any stage) → error
```

The **`awaiting_review`** pause is deliberate: lyric matching/offset is the #1 quality risk, so the
user fixes it **before** the expensive render, not after. Separation already ran (we need its
duration + stems), so review is fast and the only thing gating the render.

## 3. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.10+ | matches existing audio-separator workflow |
| Web server | FastAPI + Uvicorn | async, simple job APIs |
| Frontend | **Full Alpine.js** + minimal CSS | one declarative model, no build step |
| YouTube | yt-dlp | audio + metadata + thumbnail |
| Separation | audio-separator (python-audio-separator) + torch | BS/Mel-Band Roformer default |
| Lyrics | LRCLIB REST via httpx | free, crowd-sourced, no key |
| Cover art | iTunes Search API / Deezer cover API | free, no key; for bg color + thumbnail |
| Render | ASS + ffmpeg/libass | karaoke styling for free |
| Images | Pillow | thumbnails + (any) generated backgrounds |
| Color | Pillow / colorthief-style average + luma clamp | Spotify-style bg color |
| Fonts | Noto Sans CJK (lyrics) + Montserrat ExtraBold (Latin titles) | universal scripts |

## 4. Core technical risk + solution: the renderer

Convert **LRC → ASS subtitle → burn over background with ffmpeg/libass**. ASS gives
styling/positioning/fades for free; no Node, no Premiere.

### 4.1 Spotify-style smooth scroll (continuous motion)
- Parse LRC into `[(t_i, text_i)]` (drop empty lines), apply global `offset_ms` to every `t_i`.
- Video 1920×1080; set ASS `PlayResX/Y` to match.
- **Each line is its own positioned `\an5` event** (not a redrawn window). Within an inter-line
  interval the line **holds** centered, then over the last `TRANSITION_MS` (~450 ms) it **scrolls up
  one slot** via `\move`, while the highlight hands off to the next line via `\t` on `\alpha`. Because
  consecutive events share identical positions at their shared boundary, the motion is **continuous**
  — a real scroll, not a per-line pop/fade. (The earlier windowed-snapshot approach is replaced.)
- **Active** = full-opacity white; **Inactive** = white ~45% (brighter-only, no size change).
- The scroll geometry (`SCROLL` in `app/config.py`: font size, line spacing, visible radius,
  transition, opacity) is **shared with the browser preview** (`/api/render-config`) so the live
  review preview matches libass. Last line holds centered until song/instrumental end.

```
ffmpeg -loop 1 -i background.png -i instrumental.wav \
       -vf "ass=lyrics.ass" -r 60 \
       -c:v libx264 -pix_fmt yuv420p -preset medium \
       -c:a aac -b:a 192k -shortest output.mp4
```

> **CJK caveat (must-handle):** libass needs a font covering the target script. Use **Noto Sans
> CJK** (JP+KR+Latin) for lyrics or non-Latin renders as tofu. Set `fontsdir` / fontconfig so the
> bundled font is found regardless of system fonts.

*Alt renderer if richer motion is wanted later: MoviePy or Remotion. ffmpeg+ASS chosen for v1 =
fastest, fewest deps.*

### 4.2 Background (3 modes, chosen in review)
- **`color`** (default): cover art (iTunes/Deezer) → **average/dominant** color → **luma clamp**
  (darken near-white toward grey, mute over-saturation) → flat 1920×1080 PNG. Spotify lyrics look.
- **`cover`**: album art scaled to fill 16:9, heavily blurred + darkened (Spotify full-screen look).
- **`thumbnail`**: the YouTube thumbnail filled to 16:9 and darkened.
- All three are generated during `prepare` so the review screen can switch between them instantly;
  the lyric style carries a subtle outline so white text stays legible over image backgrounds.

### 4.3 Guide-vocal option (no re-separation)
audio-separator emits **both** instrumental and vocal stems in one pass. At render:
- **Full instrumental** (default): use instrumental stem as-is.
- **Guide vocal**: `ffmpeg amix` instrumental + vocal at low gain (e.g. vocal ×0.15).
Discard vocal stem after render (keep instrumental per user preference).

## 5. API design

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/jobs` | `{youtube_url, sep_model, options}` → `{job_id}` (model chosen before separation) |
| `GET` | `/api/jobs/{id}` | status, stage, progress %, logs, meta, error, result URLs |
| `GET` | `/api/jobs/{id}/review` | LRC candidates, chosen LRC, cover art, suggested offset |
| `POST` | `/api/jobs/{id}/review` | `{lrc, offset_ms, thumbnail_layout, vocal_mode}` → resume to render |
| `GET` | `/api/files/{id}/{video.mp4\|thumbnail.png\|instrumental.wav}` | downloads |

Frontend polls `GET /api/jobs/{id}` (or SSE) for live progress.

## 6. Data model

```python
@dataclass
class Job:
    id: str
    url: str
    status: str          # queued|running|awaiting_review|done|error
    stage: str           # downloading|separating|fetching_lyrics|rendering
    progress: float
    sep_model: str       # separation model id (UI dropdown; quality default)
    meta: dict           # {title, artist, duration, yt_thumbnail_url, cover_url}
    lrc: str | None
    lrc_candidates: list  # from LRCLIB search
    offset_ms: int
    bg_color: tuple       # computed RGB after luma clamp
    thumbnail_layout: str # "cinematic" | "album"
    vocal_mode: str       # "instrumental" | "guide"
    outputs: dict         # {video, thumbnail, instrumental}
    logs: list[str]
    error: str | None
```

Persistence: in-memory dict + per-job working dir `workspace/<job_id>/`
(`source.*`, `instrumental.wav`, `vocals.wav`, `lyrics.lrc`, `lyrics.ass`, `background.png`,
`cover.jpg`, `output.mp4`, `thumbnail.png`). SQLite for resume = later enhancement.

## 7. Concurrency
Single background **worker thread** consuming a FIFO queue — separation + ffmpeg run one at a time.
Correct for local single-user; no Celery/Redis. The `awaiting_review` state lets a job sit between
separation and render without holding the worker (worker picks it back up on review submit).

## 8. Repo structure

```
norchid/
├── pyproject.toml
├── README.md
├── docs/{PRD,ARCHITECTURE,BRANDING,ROADMAP,DECISIONS}.md
├── app/
│   ├── main.py          # FastAPI app + routes + static serving
│   ├── jobs.py          # Job model, queue, worker thread
│   └── config.py
├── pipeline/
│   ├── download.py      # yt-dlp → audio + metadata
│   ├── separate.py      # audio-separator → instrumental + vocal
│   ├── lyrics.py        # LRCLIB search/match + LRC parse
│   ├── artwork.py       # iTunes/Deezer cover fetch + average color + luma clamp
│   ├── ass_render.py    # LRC(+offset) → ASS (windowed highlight)
│   ├── video.py         # ffmpeg compose → MP4 (+ guide-vocal amix)
│   └── thumbnail.py     # Pillow → 1280x720 PNG, 2 layouts
├── web/
│   ├── index.html       # Alpine.js SPA
│   └── app.css
└── assets/fonts/        # NotoSansCJK*, Montserrat-ExtraBold
```
