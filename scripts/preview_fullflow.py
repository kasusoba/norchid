"""Full natural flow: load page, type URL, click Start, wait through the real
download+separation to review, then verify the preview renders + plays — the
exact path the user takes. Uses the persistent renderLoop (no manual start)."""

import time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8032"
URL = "https://music.youtube.com/watch?v=tLSez4SA8cY"  # the user's test track


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/chromium-browser", args=["--no-sandbox"])
        pg = b.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE, wait_until="networkidle")
        # type URL + click Start, exactly like a user
        pg.fill('input[type=text]', URL)
        pg.click('button:has-text("Start")')
        # wait until the review screen appears (separation can take a while)
        deadline = time.time() + 240
        reached = False
        while time.time() < deadline:
            st = pg.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).job.status")
            if st in ("awaiting_review", "error"):
                reached = st
                break
            time.sleep(3)
        print("reached:", reached)
        if reached != "awaiting_review":
            err = pg.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).job.error")
            print("job error:", err)
            b.close(); return
        time.sleep(2.5)  # a few render frames + audio load
        info = pg.evaluate("""() => {
            const c = Alpine.$data(document.querySelector('[x-data]'));
            const canvas = document.querySelector('.pv-canvas');
            const vis = canvas ? [...canvas.querySelectorAll('.line')].filter(l=>l.style.display!=='none') : [];
            return { screen:c.screen, parsed:c.parsed.length, transform:canvas?canvas.style.transform:null,
                     visible:vis.length, sample:vis[0]?{t:vis[0].textContent.slice(0,16),top:vis[0].style.top}:null,
                     dur:c.pvDuration };
        }""")
        # press play, confirm the clock + scroll advance
        pg.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).togglePlay()")
        time.sleep(1.6)
        moving = pg.evaluate("""() => {
            const c = Alpine.$data(document.querySelector('[x-data]'));
            const a = c.$refs.inst, canvas = document.querySelector('.pv-canvas');
            const tops = canvas ? [...canvas.querySelectorAll('.line')].filter(l=>l.style.display!=='none').map(l=>l.style.top).slice(0,3) : [];
            return { time: a?+a.currentTime.toFixed(2):null, paused:a?a.paused:null,
                     label:(c.$refs.timeLabel||{}).textContent, scrubValue:(c.$refs.scrub||{}).value, tops };
        }""")
        b.close()
        print("REVIEW STATE:", info)
        print("AFTER PLAY 1.6s:", moving)
        print("ERRORS:", errs or "none")


if __name__ == "__main__":
    main()
