"""Final check: at a lyric moment, screenshot the live preview AND the exact
libass frame in the same box, and measure the active-line glyph height + line
spacing in each. They should now match (font scale + spacing)."""

import json, sys, time, urllib.request
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8036"
JID = sys.argv[1]
T = 70.0


def glyph_and_gap(path, scale_to=None):
    im = Image.open(path).convert("L")
    if scale_to:
        im = im.resize((scale_to, round(scale_to * im.height / im.width)))
    a = np.asarray(im).astype(float)
    mask = a > 200
    rows = mask.any(axis=1)
    bands, s = [], None
    for y in range(a.shape[0]):
        if rows[y] and s is None: s = y
        elif not rows[y] and s is not None: bands.append((s, y - 1)); s = None
    if not bands: return None, None
    best = max(bands, key=lambda b: mask[b[0]:b[1] + 1].sum())
    gh = best[1] - best[0] + 1
    # nearest dim line gap via broad threshold
    diff = (np.abs(a - np.median(a)) > 22).any(axis=1)
    centers, s = [], None
    for y in range(a.shape[0]):
        if diff[y] and s is None: s = y
        elif not diff[y] and s is not None:
            if y - 1 - s >= 3: centers.append((s + y - 1) / 2)
            s = None
    gaps = sorted(round(centers[i + 1] - centers[i], 1) for i in range(len(centers) - 1))
    med = gaps[len(gaps) // 2] if gaps else None
    return gh, med


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/chromium-browser", args=["--no-sandbox"])
        pg = b.new_page(); pg.goto(BASE, wait_until="networkidle")
        pg.evaluate(f"() => {{ const c=Alpine.$data(document.querySelector('[x-data]')); c.jobId='{JID}'; c.startPolling(); }}")
        time.sleep(2.5)
        w = pg.evaluate(f"""() => {{ const c=Alpine.$data(document.querySelector('[x-data]'));
            if(c.$refs.inst) c.$refs.inst.currentTime={T}; c.renderFrame({T});
            return document.querySelector('.preview').clientWidth; }}""")
        pg.locator('.preview').screenshot(path="outputs/g_preview.png")
        b.close()
    body = json.dumps({"lrc": _lrc(), "offset_ms": 0, "t": T, "bg_mode": "color", "lyric_size": 60}).encode()
    req = urllib.request.Request(f"{BASE}/api/jobs/{JID}/preview-frame", data=body, headers={"Content-Type": "application/json"})
    open("outputs/g_render_full.png", "wb").write(urllib.request.urlopen(req, timeout=30).read())
    pg_gh, pg_gap = glyph_and_gap("outputs/g_preview.png")
    rn_gh, rn_gap = glyph_and_gap("outputs/g_render_full.png", scale_to=w)
    print(f"preview box width: {w}px")
    print(f"PREVIEW : active glyph height={pg_gh}px  line gap={pg_gap}px")
    print(f"RENDER  : active glyph height={rn_gh}px  line gap={rn_gap}px  (scaled to {w}px)")


def _lrc():
    return json.load(urllib.request.urlopen(f"{BASE}/api/jobs/{JID}/review", timeout=10))["lrc"]


if __name__ == "__main__":
    main()
