"""FastAPI app: job APIs + static SPA (docs/ARCHITECTURE.md §5).

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config
from app.jobs import manager

WEB = config.ROOT / "web"

app = FastAPI(title="norchid", version="0.1.0")


@app.middleware("http")
async def _no_cache_frontend(request, call_next):
    """Force revalidation of the SPA + static assets so a code change is never
    masked by a stale browser cache (the inline JS lives in index.html)."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static") or path.startswith("/fonts"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


class CreateJob(BaseModel):
    youtube_url: str
    sep_model: str = config.DEFAULT_SEP_MODEL


class ReviewSubmit(BaseModel):
    lrc: str | None = None
    offset_ms: int = 0
    vocal_mode: str = "instrumental"
    bg_mode: str = config.DEFAULT_BG_MODE
    title_secondary: str = ""
    title_size: int = config.THUMB_TITLE_SIZE
    lyric_size: int = 0


class PreviewFrame(BaseModel):
    lrc: str | None = None
    offset_ms: int = 0
    t: float = 0.0
    bg_mode: str = config.DEFAULT_BG_MODE
    lyric_size: int = 0


@app.get("/api/models")
def list_models():
    return {
        "default": config.DEFAULT_SEP_MODEL,
        "models": [{"id": k, "label": v["label"]} for k, v in config.SEP_MODELS.items()],
        "vocal_modes": ["instrumental", "guide"],
        "bg_modes": [{"id": k, "label": v} for k, v in config.BG_MODES.items()],
        "default_bg_mode": config.DEFAULT_BG_MODE,
    }


@app.get("/api/render-config")
def render_config():
    """Scroll geometry shared with the browser preview so it matches libass."""
    return {"width": config.WIDTH, "height": config.HEIGHT, "scroll": config.SCROLL}


@app.post("/api/jobs")
def create_job(body: CreateJob):
    url = body.youtube_url.strip()
    if not url:
        raise HTTPException(400, "youtube_url is required")
    job = manager.create(url, body.sep_model)
    return {"job_id": job.id}


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    job = manager.get(jid)
    if not job:
        raise HTTPException(404, "job not found")
    return job.public()


@app.get("/api/jobs/{jid}/review")
def get_review(jid: str):
    job = manager.get(jid)
    if not job:
        raise HTTPException(404, "job not found")
    return manager.review_payload(job)


@app.get("/api/jobs/{jid}/candidate/{cid}")
def get_candidate_lrc(jid: str, cid: int):
    job = manager.get(jid)
    if not job:
        raise HTTPException(404, "job not found")
    lrc = manager.candidate_lrc(job, cid)
    if lrc is None:
        raise HTTPException(404, "candidate not found")
    return {"lrc": lrc}


@app.post("/api/jobs/{jid}/review")
def submit_review(jid: str, body: ReviewSubmit):
    job = manager.get(jid)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status not in ("awaiting_review", "error", "done"):
        raise HTTPException(409, f"job not ready for review (status={job.status})")
    if not job.ctx:
        raise HTTPException(409, "job has no prepared context yet")
    manager.submit_review(job, lrc=body.lrc, offset_ms=body.offset_ms,
                          vocal_mode=body.vocal_mode, bg_mode=body.bg_mode,
                          title_secondary=body.title_secondary, title_size=body.title_size,
                          lyric_size=body.lyric_size)
    return {"ok": True, "job_id": job.id}


@app.post("/api/jobs/{jid}/thumbnail-preview")
def thumbnail_preview(jid: str, body: dict):
    """Render the cinematic thumbnail with the given (editable) secondary title."""
    job = manager.get(jid)
    if not job or not job.ctx:
        raise HTTPException(404, "job not ready")
    from pipeline import thumbnail
    work_dir = config.WORKSPACE / jid
    out = work_dir / "thumb_preview.png"
    try:
        thumbnail.make_thumbnail(job.meta, work_dir, job.bg_color, out,
                                 yt_thumb=job.ctx.get("yt_thumb"),
                                 secondary=(body or {}).get("title_secondary", ""),
                                 title_size=int((body or {}).get("title_size") or config.THUMB_TITLE_SIZE))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"thumbnail render failed: {e}")
    return FileResponse(out, headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{jid}/asset/{name}")
def get_asset(jid: str, name: str):
    """Serve a whitelisted preview asset (audio/background/thumbnail) from the
    job workspace — used by the live review preview."""
    job = manager.get(jid)
    if not job:
        raise HTTPException(404, "job not found")
    path = manager.asset_path(job, name)
    if not path:
        raise HTTPException(404, "asset not found")
    return FileResponse(path)


@app.post("/api/jobs/{jid}/preview-frame")
def preview_frame(jid: str, body: PreviewFrame):
    """Render a single libass frame at time t — the exact-fidelity spot-check
    for the live preview (the browser preview is a close approximation)."""
    job = manager.get(jid)
    if not job or not job.ctx:
        raise HTTPException(404, "job not ready")
    from pipeline import ass_render, video
    work_dir = config.WORKSPACE / jid
    ctx = job.ctx
    backgrounds = ctx.get("backgrounds", {"color": ctx["background"]})
    background = backgrounds.get(body.bg_mode) or ctx["background"]
    out = work_dir / "preview_frame.png"
    try:
        ass_path = None
        if body.lrc and body.lrc.strip():
            ass_path = work_dir / "preview.ass"
            ass_render.write_ass(body.lrc, str(ass_path), duration=ctx["duration"],
                                 offset_ms=body.offset_ms,
                                 scroll=config.scroll_for(body.lyric_size))
        video.render_still(background, ass_path, body.t, out)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"preview render failed: {e}")
    return FileResponse(out, headers={"Cache-Control": "no-store"})


@app.get("/api/files/{jid}/{name}")
def get_file(jid: str, name: str):
    # Outputs live under OUTPUTS/<jid>/; constrain to that dir.
    safe = Path(name).name
    path = (config.OUTPUTS / jid / safe)
    if not path.exists():
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=safe)


@app.get("/favicon.ico")
def favicon():
    from fastapi import Response
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


# Static assets (app.css, vendored alpine.js) + vendored fonts for the preview
# (so the browser preview uses the same Noto Sans CJK as the libass render).
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")
app.mount("/fonts", StaticFiles(directory=str(config.FONTS_DIR)), name="fonts")
