"""In-memory job model + single-worker FIFO queue (docs/ARCHITECTURE.md §6/§7).

One background worker thread runs the heavy steps one at a time. A job pauses in
`awaiting_review` between separation and render (the worker is free during the
pause); submitting the review re-enqueues it for the render half.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue

from app import config
from pipeline import lyrics, runner


@dataclass
class Job:
    id: str
    url: str
    sep_model: str = config.DEFAULT_SEP_MODEL
    status: str = "queued"          # queued|running|awaiting_review|done|error
    stage: str = "queued"           # downloading|separating|fetching_lyrics|rendering|done
    progress: float = 0.0
    meta: dict = field(default_factory=dict)
    offset_ms: int = 0
    bg_color: tuple = (38, 48, 66)
    vocal_mode: str = "instrumental"
    bg_mode: str = config.DEFAULT_BG_MODE
    title_secondary: str = ""
    outputs: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)
    error: str | None = None

    # Internal (not serialized verbatim to the client).
    ctx: dict | None = None
    lrc: str | None = None
    lrc_candidates: list = field(default_factory=list)

    def public(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "sep_model": self.sep_model,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 3),
            "meta": self.meta,
            "offset_ms": self.offset_ms,
            "bg_color": list(self.bg_color),
            "vocal_mode": self.vocal_mode,
            "bg_mode": self.bg_mode,
            "outputs": {k: f"/api/files/{self.id}/{Path(v).name}"
                        for k, v in self.outputs.items()},
            "logs": self.logs[-200:],
            "error": self.error,
        }


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._queue: "Queue[tuple]" = Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # --- public API -------------------------------------------------------
    def create(self, url: str, sep_model: str) -> Job:
        jid = uuid.uuid4().hex[:10]
        job = Job(id=jid, url=url,
                  sep_model=sep_model if sep_model in config.SEP_MODELS
                  else config.DEFAULT_SEP_MODEL)
        with self._lock:
            self.jobs[jid] = job
        self._queue.put(("prepare", jid))
        return job

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def review_payload(self, job: Job) -> dict:
        """Data the review screen needs (incl. preview asset URLs)."""
        ctx = job.ctx or {}
        a = f"/api/jobs/{job.id}/asset"
        bg_files = {"color": "background.png", "cover": "bg_cover.png",
                    "thumbnail": "bg_thumbnail.png"}
        available = set(ctx.get("backgrounds", {}).keys()) or {"color"}
        backgrounds = [
            {"id": k, "label": config.BG_MODES[k], "available": k in available,
             "url": f"{a}/{bg_files[k]}"}
            for k in config.BG_MODES
        ]
        return {
            "status": job.status,
            "meta": job.meta,
            "duration": ctx.get("duration", 0.0),
            "lrc": job.lrc,
            "offset_ms": job.offset_ms,
            "bg_color": list(job.bg_color),
            "cover_url": ctx.get("cover_url"),
            "has_synced": bool(job.lrc),
            "candidates": [lyrics.candidate_summary(c) for c in job.lrc_candidates],
            "vocal_mode": job.vocal_mode,
            "bg_mode": job.bg_mode,
            "backgrounds": backgrounds,
            "title_secondary": job.meta.get("title_secondary", ""),
            "thumbnail_url": f"{a}/thumb_cinematic.png",
            "instrumental_url": f"{a}/instrumental.wav",
            "vocal_url": f"{a}/vocals.wav" if ctx.get("vocal") else None,
        }

    def asset_path(self, job: Job, name: str) -> Path | None:
        """Resolve a whitelisted preview asset within the job workspace."""
        allowed = {"instrumental.wav", "vocals.wav", "background.png",
                   "bg_cover.png", "bg_thumbnail.png", "thumb_cinematic.png",
                   "cover.jpg", "yt_thumb.jpg"}
        safe = Path(name).name
        if safe not in allowed:
            return None
        p = config.WORKSPACE / job.id / safe
        return p if p.exists() else None

    def candidate_lrc(self, job: Job, candidate_id: int) -> str | None:
        for c in job.lrc_candidates:
            if c.get("id") == candidate_id:
                return c.get("syncedLyrics") or c.get("plainLyrics")
        return None

    def submit_review(self, job: Job, *, lrc, offset_ms, vocal_mode, bg_mode,
                      title_secondary) -> None:
        job.lrc = lrc
        job.offset_ms = int(offset_ms or 0)
        job.vocal_mode = vocal_mode or "instrumental"
        job.bg_mode = bg_mode if bg_mode in config.BG_MODES else config.DEFAULT_BG_MODE
        job.title_secondary = (title_secondary or "").strip()
        job.meta["title_secondary"] = job.title_secondary
        job.status = "running"
        job.stage = "rendering"
        self._queue.put(("finalize", job.id))

    # --- worker -----------------------------------------------------------
    def _callbacks(self, job: Job):
        def log(msg: str):
            job.logs.append(msg)

        def stage(s: str):
            job.stage = s

        def progress(p: float):
            job.progress = max(0.0, min(1.0, p))
        return log, stage, progress

    def _run(self) -> None:
        while True:
            kind, jid = self._queue.get()
            job = self.jobs.get(jid)
            if not job:
                continue
            log, stage, progress = self._callbacks(job)
            try:
                if kind == "prepare":
                    job.status = "running"
                    work_dir = config.WORKSPACE / job.id
                    ctx = runner.prepare(job.url, work_dir, job.sep_model,
                                         log=log, stage=stage, progress=progress)
                    job.ctx = ctx
                    job.meta = ctx["meta"]
                    job.lrc = ctx["lrc"]
                    job.lrc_candidates = ctx["lrc_candidates"]
                    job.bg_color = tuple(ctx["bg_color"])
                    job.status = "awaiting_review"
                    job.stage = "awaiting_review"
                    job.progress = 1.0
                    log("Ready for review.")
                elif kind == "finalize":
                    work_dir = config.WORKSPACE / job.id
                    out_dir = config.OUTPUTS / job.id
                    outputs = runner.finalize(
                        job.ctx, work_dir, out_dir,
                        lrc=job.lrc, offset_ms=job.offset_ms,
                        vocal_mode=job.vocal_mode, bg_mode=job.bg_mode,
                        title_secondary=job.title_secondary,
                        log=log, stage=stage, progress=progress)
                    job.outputs = outputs
                    job.status = "done"
                    job.stage = "done"
                    job.progress = 1.0
            except Exception as e:  # noqa: BLE001
                job.status = "error"
                job.error = str(e)
                job.logs.append("ERROR: " + str(e))
                job.logs.append(traceback.format_exc())


manager = JobManager()
