"""Headless browser test of the live preview — drives the real page with mocked
API responses, reaches the review screen, and reports console errors + whether
the scrolling lyrics actually render (positions/opacities), and whether the
RAF clock advances. This is how we debug the preview without a real job."""

import time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8030"

LRC = "\\n".join([
    "[00:00.50] first line of the song",
    "[00:02.00] 二行目の歌詞 second line",
    "[00:04.00] 노래방 third line here",
    "[00:06.00] fourth line keeps going",
    "[00:08.00] fifth line of lyrics",
    "[00:10.00] sixth and final line",
])

# Mock fetch installed BEFORE Alpine runs, so the component talks to canned data.
MOCK = r"""
window.__logs = [];
const realFetch = window.fetch;
window.fetch = async (url, opts) => {
  const u = (typeof url === 'string') ? url : url.url;
  const json = (o) => new Response(JSON.stringify(o), {headers:{'Content-Type':'application/json'}});
  if (u.endsWith('/api/models')) return json({default:'roformer', models:[{id:'roformer',label:'R'}], vocal_modes:['instrumental','guide'], bg_modes:[{id:'color',label:'Flat'}], default_bg_mode:'color'});
  if (u.endsWith('/api/render-config')) return json({width:1920,height:1080,scroll:{font_size:60,line_spacing:104,visible_radius:6,transition_ms:450,alpha_active:0,alpha_inactive:0.55}});
  if (u.match(/\/api\/jobs\/[^/]+\/review$/)) return json({
     status:'awaiting_review', meta:{title:'Test Song', artist:'Tester'}, duration:12.0,
     lrc: __LRC__, offset_ms:0, bg_color:[40,46,60], cover_url:null, has_synced:true,
     candidates:[], thumbnail_url:'/static/app.css', instrumental_url:'__WAV__', vocal_url:null,
     bg_mode:'color', vocal_mode:'instrumental', title_secondary:'', title_size:110,
     backgrounds:[{id:'color',label:'Flat',available:true,url:'/static/app.css'}]});
  if (u.match(/\/api\/jobs$/)) return json({job_id:'testjob'});
  if (u.match(/\/api\/jobs\/[^/]+$/)) return json({status:'awaiting_review', stage:'awaiting_review', progress:1, meta:{title:'Test Song',artist:'Tester'}, logs:[], outputs:{}, bg_color:[40,46,60]});
  return realFetch(url, opts);
};
"""

# A tiny silent wav (data URI) so the <audio> can have a duration we can scrub.
WAV = ("data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAA"
       "ZGF0YQAAAAA=")


def main():
    mock = (MOCK.replace("__LRC__", '"' + LRC + '"').replace("__WAV__", WAV))
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/chromium-browser", args=["--no-sandbox"])
        pg = b.new_page()
        errors, logs = [], []
        pg.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(mock)
        pg.goto(BASE, wait_until="networkidle")
        # Drive into review: set jobId and poll.
        pg.evaluate("""() => {
            const el = document.querySelector('[x-data]');
            const c = Alpine.$data(el);
            c.jobId = 'testjob';
            c.startPolling();
        }""")
        time.sleep(1.5)
        # Inspect.
        info = pg.evaluate("""() => {
            const el = document.querySelector('[x-data]');
            const c = Alpine.$data(el);
            const canvas = document.querySelector('.pv-canvas');
            const lines = canvas ? canvas.querySelectorAll('.line') : [];
            const visible = [...lines].filter(l => l.style.display !== 'none');
            const stage = document.querySelector('.preview');
            return {
              screen: c.screen, parsedLen: c.parsed.length, looping: c._looping,
              dirty: c._dirty,
              canvasExists: !!canvas,
              canvasTransform: canvas ? canvas.style.transform : null,
              stageW: stage ? stage.clientWidth : null,
              stageVisible: stage ? (stage.offsetParent !== null) : null,
              lineCount: lines.length, visibleCount: visible.length,
              sampleLine: visible[0] ? {text: visible[0].textContent, top: visible[0].style.top, left: visible[0].style.left, fontSize: visible[0].style.fontSize, opacity: visible[0].style.opacity} : null,
              audioReadyState: c.$refs.inst ? c.$refs.inst.readyState : 'no-ref',
            };
        }""")
        # Advance the audio clock and re-check that render updates.
        pg.evaluate("""() => { const c = Alpine.$data(document.querySelector('[x-data]')); if (c.$refs.inst) { try { c.$refs.inst.currentTime = 5.0; } catch(e){} } }""")
        time.sleep(0.6)
        after = pg.evaluate("""() => {
            const canvas = document.querySelector('.pv-canvas');
            const visible = canvas ? [...canvas.querySelectorAll('.line')].filter(l=>l.style.display!=='none') : [];
            const c = Alpine.$data(document.querySelector('[x-data]'));
            return { time: c.$refs.inst ? c.$refs.inst.currentTime : null, label: (c.$refs.timeLabel||{}).textContent, topOfActive: visible.map(v=>v.style.top).slice(0,3) };
        }""")
        b.close()
        print("PAGE ERRORS:", errors or "none")
        print("CONSOLE:", *logs, sep="\n  ")
        print("STATE:", info)
        print("AFTER seek to 5s:", after)


if __name__ == "__main__":
    main()
