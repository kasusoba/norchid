# norchid — Product Requirements Document

## 1. Overview

### 1.1 Problem
Making instrumental + scrolling-lyrics karaoke videos is a repetitive manual pipeline:
instrumental (x-minus.pro) → scrolling lyrics (Gaudio "noraebang") → mask/composite in Premiere
→ export → hand-made matching thumbnail. The lyric-timing and compositing steps are the painful,
repetitive parts. No existing free tool does the **whole** chain and exports a video:
- **Apple Music Sing** — Apple-only, subscription, on-device, **no export**.
- **Spotify / YouTube** — no karaoke / vocal-removal export.
- **Gaudio GTS** ("noraebang") — the tool that inspired this; now B2B-only, no free public demo.

### 1.2 Goal
One local tool: **paste a YouTube URL → finished 1080p60 karaoke MP4 (instrumental + Spotify-style
scrolling lyrics) + matching thumbnail**, with minimal manual touch-up.

### 1.3 Primary use case
**Japanese songs** (the original use case — Gaudio was just a Korean tool). Script-agnostic:
must render **romaji / Latin, hiragana / katakana / kanji, Hangul** equally. The user historically
fed the tool **romaji** lyrics, so manual lyric entry/edit is first-class, not a fallback.

### 1.4 Target user
Single user, local, self-hosted. Comfortable with Python/CLI but wants a simple web UI for runs.

## 2. User stories
- Paste a YouTube link → tool fetches audio, makes the instrumental, finds synced lyrics, renders
  the scrolling-lyrics video. No Premiere.
- **Review before the slow render**: edit/replace lyric text (e.g. paste romaji), fix a wrong
  LRCLIB match, apply a global time offset (YT uploads often have intros / different timing).
- Pick a **thumbnail layout** (cinematic full-bleed, or album-cover based) → get a branded
  thumbnail with title + "Instrumental" tag.
- Optionally render a **guide-vocal** version (faint vocals mixed back for practice).
- Download MP4, thumbnail, and the instrumental stem.

## 3. Scope

### 3.1 In scope (v1)
- Single YouTube URL input.
- Local instrumental separation (audio-separator; quality model default).
- Synced lyrics via **LRCLIB**, with manual edit + paste + global offset.
- **Line-level** Spotify-style scrolling lyrics → 1920×1080 @ 60fps MP4.
- Album-color video background (Spotify-style), white lyrics (dim inactive / bright active).
- Auto thumbnail, **two layouts** (see BRANDING.md).
- Optional guide-vocal mix at render time.
- Local web UI (full Alpine.js) with job progress + a lyric/offset review step.

### 3.2 Out of scope (v1) — parked
- **Word-by-word karaoke wipe** (needs WhisperX forced alignment) → Roadmap Phase 4.
- Batch / playlist processing.
- 9:16 Shorts format.
- Cloud hosting / multi-user / auth.
- Spotify/Musixmatch lyric scraping (gray area; LRCLIB + manual paste only).

## 4. Functional requirements
| # | Requirement |
|---|---|
| F1 | Accept a YouTube URL; download best audio + metadata (title, artist, duration, thumbnail). |
| F2 | Separate instrumental and vocal stems in a single pass; keep both until render. |
| F3 | Fetch synced (LRC) lyrics from LRCLIB, best-match by duration; expose candidates. |
| F4 | Fetch cover art (iTunes/Deezer) for background color + album-layout thumbnail. |
| F5 | Pause for user review: edit lyric text, swap match, paste custom LRC/romaji, set offset (ms). |
| F6 | Render line-level scrolling lyrics over album-color background at 1080p60. |
| F7 | Generate thumbnail in the selected layout with title + "Instrumental" tag. |
| F8 | Offer full-instrumental vs guide-vocal (low-volume vocal mix) at render. |
| F9 | Provide downloads: video.mp4, thumbnail.png, instrumental.wav. |
| F10 | Render any of Latin/romaji, JP kana/kanji, Hangul correctly (CJK font). |
| F11 | Let the user pick the separation model (quality default + faster options) at job start. |

## 5. Non-functional requirements
- Runs locally, single-user; needs network for yt-dlp + LRCLIB + cover art.
- GPU optional; detect and warn if CPU-only (separation is the slow step).
- Heavy steps run sequentially via a single worker (no GPU/CPU thrash).
- No frontend build step (Alpine via CDN/vendored script).

## 6. Success metric
Time-per-song from "a couple manual hours" → **under ~10 minutes, mostly unattended**, with
Premiere eliminated entirely.
