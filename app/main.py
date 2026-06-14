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


class CreateJob(BaseModel):
    youtube_url: str
    sep_model: str = config.DEFAULT_SEP_MODEL


class ReviewSubmit(BaseModel):
    lrc: str | None = None
    offset_ms: int = 0
    thumbnail_layout: str = "cinematic"
    vocal_mode: str = "instrumental"


@app.get("/api/models")
def list_models():
    return {
        "default": config.DEFAULT_SEP_MODEL,
        "models": [{"id": k, "label": v["label"]} for k, v in config.SEP_MODELS.items()],
        "layouts": ["cinematic", "album"],
        "vocal_modes": ["instrumental", "guide"],
    }


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
                          thumbnail_layout=body.thumbnail_layout,
                          vocal_mode=body.vocal_mode)
    return {"ok": True, "job_id": job.id}


@app.get("/api/files/{jid}/{name}")
def get_file(jid: str, name: str):
    # Outputs live under OUTPUTS/<jid>/; constrain to that dir.
    safe = Path(name).name
    path = (config.OUTPUTS / jid / safe)
    if not path.exists():
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=safe)


@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


# Static assets (app.css, vendored alpine.js).
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")
