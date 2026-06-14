# norchid — Branding & Visual Spec

Two distinct surfaces with **different** backgrounds. Keep them separate.

## 1. Lyrics VIDEO background — Spotify-style flat color

- Source the **album cover** (iTunes Search API / Deezer by artist + title; LRCLIB has no art).
- Compute the **average / dominant color** of the cover.
- **Luminance clamp** (Spotify behavior):
  - If too light (e.g. near-white album) → darken toward a mid/dark grey.
  - Lightly mute extreme saturation.
  - Target: a calm, mid-dark flat field where white text is always legible.
- Render as a flat **1920×1080** background. (No image, no gradient by default — just the color,
  like Spotify's lyrics view.)

### Lyrics typography
- Color: **always white.**
  - Inactive lines: white at **~45% opacity**.
  - Active (current) line: **100% opacity white.**
- Font: **Noto Sans CJK** (Bold weight) — single family covers **Latin/romaji + hiragana/katakana/
  kanji + Hangul**. Romaji or native script both render. (This is what makes the tool universal.)
- Layout: centered (`\an5`), windowed ~5 lines, active line emphasized, soft fades between lines.
- Aspect/FPS: **1920×1080 @ 60fps**, H.264 + AAC.

## 2. THUMBNAIL — image-based, two layouts

Both: white text, "Instrumental" tag, **no duration badge** (YouTube draws its own).
Output **1280×720**.

### Layout 1 — "Cinematic" (ref: *Mela!*)
- Background: full-bleed **YouTube video thumbnail** image.
- Darkened gradient/overlay for text legibility.
- **Title:** large bold white, **centered**.
- **"Instrumental":** smaller label, **centered directly under** the title.

### Layout 2 — "Album" (ref: *Omoinotake — One Day*)
- Background: **album cover**, blurred-and-extended to fill 16:9, with the cover readable.
- **"instrumental":** small box/tag, **top-left corner**.
- **Text:** artist line + title (bold white), stacked.

### Thumbnail title font
- **Montserrat ExtraBold** for Latin titles (matches the punchy look of the references).
- **Fall back to Noto Sans CJK Bold** when the title contains CJK (so Japanese titles still render).

## 3. Asset checklist
- `assets/fonts/NotoSansCJKjp-Bold` (or full CJK) — lyrics + CJK titles.
- `assets/fonts/NotoSansCJKkr-Bold` — Hangul (covered by full CJK pack).
- `assets/fonts/Montserrat-ExtraBold` — Latin thumbnail titles.
- Ensure libass/fontconfig can find the bundled fonts (set `fontsdir`).

## 4. Color algorithm (reference)
```
cover = fetch_cover(artist, title)          # iTunes/Deezer
rgb   = dominant_color(cover)               # average or k-means dominant
L     = luminance(rgb)                       # 0..1
if L > 0.65:  rgb = darken(rgb, toward grey) # avoid white-on-white
if sat(rgb) > 0.8: rgb = desaturate(rgb, 0.2)
bg = flat_image(1920, 1080, rgb)
```
