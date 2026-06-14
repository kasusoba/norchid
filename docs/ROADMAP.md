# norchid — Roadmap

Build the **renderer first** — it's the highest-risk piece. If ASS scrolling + CJK fonts work, the
rest is plumbing.

| Phase | Deliverable | Proves |
|---|---|---|
| **0 — Spike** | Hardcoded LRC + a wav + a flat bg → `ass_render.py` → ffmpeg → watchable 1080p60 MP4, including a **Japanese** sample line | The renderer + CJK fonts work |
| **1 — CLI MVP** | `python -m norchid <url>` runs the full chain headless → MP4 + thumbnail + instrumental | End-to-end pipeline |
| **2 — Web UI** | FastAPI + job queue + Alpine SPA: paste URL, live progress, **review step** (edit lyrics / offset / layout / vocal mode), download | The actual product UX |
| **3 — Polish** | Album-color bg tuning, both thumbnail layouts, in-browser lyric edit + render preview, robust error handling, guide-vocal toggle | Daily-usable |
| **4 — Stretch** | Word-level karaoke wipe (WhisperX forced alignment), playlist/batch, 9:16 Shorts, style presets | Beyond v1 |

## Phase 0 acceptance checklist
- [ ] Parse a small `.lrc` into `[(t, text)]`.
- [ ] Emit ASS with windowed highlight (active=white 100%, inactive=white 45%), `\an5`, fades.
- [ ] Burn over a flat-color 1920×1080 bg via ffmpeg at 60fps with an instrumental wav.
- [ ] A hiragana/kanji line and a Hangul line render correctly (no tofu).
- [ ] Output plays, lyrics scroll in time, audio is the instrumental.

## Phase 1 pipeline order
download → separate (both stems) → fetch lyrics (LRCLIB) → fetch cover + bg color →
render ASS → compose video → thumbnail → collect outputs.

## Known Phase 4 design note
LRCLIB gives **line-level** timestamps only. Word-by-word wipe needs **word-level** timing →
run WhisperX forced alignment on the **vocal stem** (which separation already produced) against the
LRC text, then emit ASS `\k` tags. The vocal stem being free from step 2 makes this cheap to add.
