# norchid — Decision Log

Locked decisions from the planning session, with rationale. (Newest context wins if revisited.)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Name: `norchid`** | User choice. (Nods to "noraebang" origin.) |
| D2 | **Primary use = Japanese songs; script-agnostic** | Original use case was JP; Gaudio was merely a Korean *tool*. Must render romaji / kana / kanji / Hangul / Latin. |
| D3 | **Input = single YouTube URL** | User's chosen entry point. Local-file input is a cheap future fallback if yt-dlp breaks. |
| D4 | **Lyrics: LRCLIB primary + manual paste/edit** | Free, crowd-sourced, no key, legal. User historically typed **romaji** by hand → manual entry is first-class. Spotify/Musixmatch scraping rejected (gray area, gated). |
| D5 | **Separation: audio-separator, quality model default** | De-facto headless wrapper over the standard models (Demucs/MDX/Roformer). Default = BS/Mel-Band **Roformer** (top SDR); MDX-NET-Inst as fast draft fallback. |
| D6 | **Both stems in one pass; keep vocal temporarily** | audio-separator outputs instrumental **and** vocal together → **no re-separation** needed for the guide-vocal option. Discard vocal after render (keep instrumental only). |
| D7 | **Guide-vocal option at render** | Full instrumental (default) vs. low-volume vocal mixed back (~×0.15) via ffmpeg `amix` for sing-along practice. |
| D8 | **Lyric style = line-level Spotify scroll** | Matches the desired look; no ML needed (LRCLIB line timestamps suffice). Word-wipe deferred to Phase 4 (WhisperX). |
| D9 | **Video bg = flat album-derived color + luma clamp** | Spotify lyrics look. Darken near-white covers toward grey so white text stays legible. |
| D10 | **Lyrics always white: inactive ~45% / active 100%** | Spotify behavior; "always white, brighter when highlighted." |
| D11 | **Fonts: Noto Sans CJK (lyrics) + Montserrat ExtraBold (Latin thumbnail titles, CJK fallback)** | Noto CJK = universal script coverage; Montserrat = punchy thumbnail look from references. |
| D12 | **Thumbnail = 2 layouts (Cinematic / Album), no duration badge** | From user's two reference screenshots. Duration badge in ref was YouTube's overlay, not design. |
| D13 | **Cover art via iTunes Search API / Deezer** | Free, no key. Feeds both bg color and album-layout thumbnail. |
| D14 | **Render: ffmpeg + libass, 1920×1080 @ 60fps, H.264/AAC** | Karaoke styling free via ASS; 60fps for smooth scroll fades. |
| D15 | **Frontend: FULL Alpine.js, no build step** | Consistency > micro-optimization — avoid a mixed imperative/declarative codebase a reviewer would question. Alpine ~15kb, declarative, no build. |
| D16 | **Backend: FastAPI + Uvicorn; single worker thread + in-memory jobs + per-job workspace dir** | Local single-user; no Celery/Redis. `awaiting_review` state pauses between separate and render. |
| D17 | **Review step pauses before the slow render** | Lyric match/offset is the #1 quality risk; fix it before paying render cost. |
| D18 | **Separation model is user-selectable (UI dropdown)** | Chosen at job start (before separation). Quality Roformer default + faster MDX-NET option. |
| D19 | **Build agent vendors fonts itself** | Noto Sans CJK + Montserrat are free (Google Fonts); the build session downloads them into `assets/fonts/`. Not the user's job. |
| D20 | **User tests only the finished product** | No incremental user testing; next session builds through Phase 3 before handing back for testing. |

## Open / deferred
- ~~Default separation model: pick exact Roformer checkpoint during Phase 1.~~
  **Resolved (Phase 1):** default = `model_bs_roformer_ep_317_sdr_12.9755.ckpt`
  (BS-Roformer Viperx-1297) — top-SDR general Roformer, emits both stems in one
  pass (needed for guide-vocal). Dropdown also exposes MelBand Roformer Inst v2
  (cleanest instrumental) and UVR-MDX-NET Inst HQ 3 (faster draft). On an RTX 3060
  a ~4-min song separates in ~40s.
- SQLite job persistence (resume) — enhancement, not v1.
- Local-file input fallback — add if yt-dlp reliability becomes an issue.
- Phase 4: WhisperX word-level wipe, batch/playlist, 9:16 Shorts.
