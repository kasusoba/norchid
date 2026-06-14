"""Drive the REAL page against a REAL prepared job (no mocks) — exactly what the
user sees. Reports console errors and whether the preview renders + advances."""

import sys, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8030"
JID = sys.argv[1]


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/chromium-browser", args=["--no-sandbox"])
        pg = b.new_page()
        errors, logs = [], []
        pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(BASE, wait_until="networkidle")
        pg.evaluate(f"""() => {{
            const c = Alpine.$data(document.querySelector('[x-data]'));
            c.jobId = '{JID}';
            c.startPolling();
        }}""")
        time.sleep(2.5)  # let review load + audio fetch + a few RAF frames
        info = pg.evaluate("""() => {
            const c = Alpine.$data(document.querySelector('[x-data]'));
            const canvas = document.querySelector('.pv-canvas');
            const lines = canvas ? canvas.querySelectorAll('.line') : [];
            const visible = [...lines].filter(l => l.style.display !== 'none');
            const stage = document.querySelector('.preview');
            const a = c.$refs.inst;
            return {
              screen: c.screen, parsedLen: c.parsed.length, looping: c._looping,
              canvasTransform: canvas ? canvas.style.transform : null,
              stageW: stage ? stage.clientWidth : null,
              bgStyle: stage ? stage.getAttribute('style') : null,
              lineCount: lines.length, visibleCount: visible.length,
              sample: visible[0] ? {text: visible[0].textContent.slice(0,20), top: visible[0].style.top, opacity: visible[0].style.opacity} : null,
              audio: a ? {readyState:a.readyState, duration:a.duration, src:(a.currentSrc||'').slice(-40), error: a.error?a.error.code:null} : 'no-ref',
              pvDuration: c.pvDuration,
            };
        }""")
        # try playing
        playres = pg.evaluate("""async () => {
            const c = Alpine.$data(document.querySelector('[x-data]'));
            try { c.togglePlay(); } catch(e){ return 'togglePlay err: '+e.message; }
            return 'ok';
        }""")
        time.sleep(1.5)
        moving = pg.evaluate("""() => {
            const c = Alpine.$data(document.querySelector('[x-data]'));
            const a = c.$refs.inst;
            const canvas = document.querySelector('.pv-canvas');
            const tops = canvas ? [...canvas.querySelectorAll('.line')].filter(l=>l.style.display!=='none').map(l=>l.style.top).slice(0,3) : [];
            return { time: a?a.currentTime:null, paused: a?a.paused:null, label:(c.$refs.timeLabel||{}).textContent, tops };
        }""")
        b.close()
        print("PAGE ERRORS:", errors or "none")
        print("CONSOLE (last 8):")
        for l in logs[-8:]:
            print("  ", l)
        print("STATE:", info)
        print("PLAY:", playres, "| AFTER 1.5s:", moving)


if __name__ == "__main__":
    main()
