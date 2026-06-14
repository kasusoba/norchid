"""Screenshot the live preview element AND render the exact libass frame at the
same playhead, so we can compare spacing/position pixel-for-pixel."""

import json, sys, time, urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8034"
JID = sys.argv[1]
T = 70.0


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/chromium-browser", args=["--no-sandbox"])
        pg = b.new_page()
        pg.goto(BASE, wait_until="networkidle")
        pg.evaluate(f"() => {{ const c=Alpine.$data(document.querySelector('[x-data]')); c.jobId='{JID}'; c.startPolling(); }}")
        time.sleep(2.5)
        # pin playhead to T, force a render frame, read line tops
        info = pg.evaluate(f"""() => {{
            const c=Alpine.$data(document.querySelector('[x-data]'));
            if (c.$refs.inst) c.$refs.inst.currentTime = {T};
            c.renderFrame({T});
            const canvas=document.querySelector('.pv-canvas');
            const vis=[...canvas.querySelectorAll('.line')].filter(l=>l.style.display!=='none');
            return {{ lyric_size:c.form.lyric_size, spacing:c.lineSpacing(),
                      tops: vis.map(l=>l.style.top), fontSize: vis[0]?vis[0].style.fontSize:null,
                      stageW: document.querySelector('.preview').clientWidth }};
        }}""")
        # screenshot just the preview box
        pg.locator('.preview').screenshot(path="outputs/cmp_preview.png")
        b.close()
    print("PREVIEW:", info)
    # exact frame at same params
    body = json.dumps({"lrc": _lrc(), "offset_ms": 0, "t": T, "bg_mode": "color",
                       "lyric_size": info["lyric_size"]}).encode()
    req = urllib.request.Request(f"{BASE}/api/jobs/{JID}/preview-frame", data=body,
                                 headers={"Content-Type": "application/json"})
    open("outputs/cmp_render_full.png", "wb").write(urllib.request.urlopen(req, timeout=30).read())
    # downscale render to the preview box width for a fair visual compare
    from PIL import Image
    im = Image.open("outputs/cmp_render_full.png")
    w = info["stageW"]
    im.resize((w, round(w * im.height / im.width))).save("outputs/cmp_render.png")
    print("saved outputs/cmp_preview.png + outputs/cmp_render.png (same width)")
    print("expected libass tops (540 + rel*104 scaled):", [540 + r*104 for r in range(-3, 4)])


def _lrc():
    d = json.load(urllib.request.urlopen(f"{BASE}/api/jobs/{JID}/review", timeout=10))
    return d["lrc"]


if __name__ == "__main__":
    main()
