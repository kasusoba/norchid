"""In-memory job model + single-worker FIFO queue (docs/ARCHITECTURE.md §6/§7).

One background worker thread runs the heavy steps one at a time. A job pauses in
`awaiting_review` between separation and render (the worker is free during the
pause); submitting the review re-enqueues it for the render half.
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue

from app import config
from pipeline import artwork, lyrics, runner

# Persisted, machine-portable per-job state (the heavy artifacts already live in
# workspace/<id>/; we only need the metadata to rehydrate a job after a restart).
_PERSIST_FIELDS = ("url", "sep_model", "status", "stage", "meta", "offset_ms",
                   "vocal_mode", "bg_mode", "title_secondary", "title_size",
                   "pill_size", "thumb_bg", "pill_color", "lyric_size", "lrc",
                   "romaji", "lrc_candidates", "outputs", "error")
_BG_FILES = {"color": "background.png", "cover": "bg_cover.png",
             "thumbnail": "bg_thumbnail.png"}


def _job_to_dict(job: "Job") -> dict:
    d = {"v": 1, "id": job.id, "progress": job.progress,
         "bg_color": list(job.bg_color)}
    for f in _PERSIST_FIELDS:
        d[f] = getattr(job, f)
    ctx = job.ctx or {}
    d["duration"] = ctx.get("duration", 0.0)
    d["cover_url"] = ctx.get("cover_url")
    d["sep_model_file"] = ctx.get("sep_model_file")
    return d


def _rebuild_ctx(job: "Job", duration: float, cover_url, sep_model_file) -> dict | None:
    """Rehydrate ctx from the on-disk workspace files (paths reconstructed by id
    + known filenames, so it survives a repo move)."""
    wd = config.WORKSPACE / job.id
    inst = wd / "instrumental.wav"
    if not inst.exists():
        return None
    if not duration:
        from pipeline import video
        duration = video.probe_duration(inst)
    backgrounds = {m: wd / f for m, f in _BG_FILES.items() if (wd / f).exists()}
    cover = (wd / "cover.jpg") if (wd / "cover.jpg").exists() else None
    return {
        "meta": job.meta, "duration": duration, "instrumental": inst,
        "palette": artwork.palette(cover) if cover else [],
        "vocal": (wd / "vocals.wav") if (wd / "vocals.wav").exists() else None,
        "sep_model_file": sep_model_file,
        "lrc": job.lrc, "lrc_candidates": job.lrc_candidates,
        "cover": cover,
        "cover_url": cover_url, "bg_color": tuple(job.bg_color),
        "background": backgrounds.get("color") or (wd / "background.png"),
        "backgrounds": backgrounds,
        "yt_thumb": (wd / "yt_thumb.jpg") if (wd / "yt_thumb.jpg").exists() else None,
    }


def _job_from_dict(d: dict) -> "Job":
    job = Job(id=d["id"], url=d.get("url", ""),
              sep_model=d.get("sep_model", config.DEFAULT_SEP_MODEL))
    for f in _PERSIST_FIELDS:
        if f in d and d[f] is not None:
            setattr(job, f, d[f])
    job.progress = d.get("progress", 1.0)
    job.bg_color = tuple(d.get("bg_color", (38, 48, 66)))
    job.ctx = _rebuild_ctx(job, d.get("duration", 0.0), d.get("cover_url"),
                           d.get("sep_model_file"))
    return job


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
    title_size: int = config.THUMB_TITLE_SIZE
    pill_size: int = config.THUMB_PILL_SIZE
    thumb_bg: str = "youtube"
    pill_color: tuple | None = None   # None = auto (sampled from background)
    lyric_size: int = 0   # 0 = default scroll font size
    outputs: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)
    error: str | None = None

    # Internal (not serialized verbatim to the client).
    ctx: dict | None = None
    lrc: str | None = None
    romaji: str | None = None
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
        self._load_persisted()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # --- persistence ------------------------------------------------------
    def _load_persisted(self) -> None:
        """Rehydrate jobs from workspace/<id>/job.json on startup."""
        if not config.WORKSPACE.exists():
            return
        entries = []
        for d in config.WORKSPACE.iterdir():
            pj = d / "job.json"
            if not pj.is_file():
                continue
            try:
                job = _job_from_dict(json.loads(pj.read_text(encoding="utf-8")))
            except Exception:
                continue
            if job.status == "running":           # interrupted mid-work
                job.status, job.error = "error", "interrupted by restart"
            entries.append((pj.stat().st_mtime, job))
        for _, job in sorted(entries, key=lambda x: x[0]):
            self.jobs[job.id] = job

    def _save(self, job: Job) -> None:
        try:
            d = config.WORKSPACE / job.id
            d.mkdir(parents=True, exist_ok=True)
            (d / "job.json").write_text(json.dumps(_job_to_dict(job)), encoding="utf-8")
        except Exception:
            pass

    def list_public(self) -> list[dict]:
        """Compact list of resumable jobs, newest first."""
        items = [{"id": j.id, "status": j.status,
                  "title": (j.meta or {}).get("title") or j.url,
                  "artist": (j.meta or {}).get("artist", "")}
                 for j in self.jobs.values() if j.ctx or j.status == "done"]
        return list(reversed(items))

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
            "romaji": job.romaji or "",
            "lyric_size": job.lyric_size or config.SCROLL["font_size"],
            "offset_ms": job.offset_ms,
            "bg_color": list(job.bg_color),
            "cover_url": ctx.get("cover_url"),
            "has_synced": bool(job.lrc),
            "candidates": [lyrics.candidate_summary(c) for c in job.lrc_candidates],
            "vocal_mode": job.vocal_mode,
            "bg_mode": job.bg_mode,
            "backgrounds": backgrounds,
            "title_secondary": job.meta.get("title_secondary", ""),
            "title_size": job.title_size,
            "pill_size": job.pill_size,
            "thumb_bg": job.thumb_bg,
            "pill_color": list(job.pill_color) if job.pill_color else None,
            "bg_swatches": [list(artwork.clamp_color(c)) for c in ctx.get("palette", [])],
            "pill_swatches": [list(artwork.mute_for_pill(c)) for c in ctx.get("palette", [])],
            "has_cover": bool(ctx.get("cover")),
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

    def submit_review(self, job: Job, *, lrc, romaji, offset_ms, vocal_mode, bg_mode,
                      title_secondary, title_size, pill_size, thumb_bg, lyric_size,
                      bg_color=None, pill_color=None) -> None:
        job.lrc = lrc
        job.romaji = romaji
        job.offset_ms = int(offset_ms or 0)
        job.vocal_mode = vocal_mode or "instrumental"
        job.bg_mode = bg_mode if bg_mode in config.BG_MODES else config.DEFAULT_BG_MODE
        job.title_secondary = (title_secondary or "").strip()
        job.meta["title_secondary"] = job.title_secondary
        job.title_size = int(title_size or config.THUMB_TITLE_SIZE)
        job.pill_size = int(pill_size or config.THUMB_PILL_SIZE)
        job.thumb_bg = thumb_bg if thumb_bg in config.THUMB_BG_SOURCES else "youtube"
        if bg_color:
            job.bg_color = tuple(bg_color)
        job.pill_color = tuple(pill_color) if pill_color else None
        job.lyric_size = int(lyric_size or 0)
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
                    self._save(job)
                elif kind == "finalize":
                    work_dir = config.WORKSPACE / job.id
                    out_dir = config.OUTPUTS / job.id
                    outputs = runner.finalize(
                        job.ctx, work_dir, out_dir,
                        lrc=job.lrc, romaji=job.romaji, offset_ms=job.offset_ms,
                        vocal_mode=job.vocal_mode, bg_mode=job.bg_mode,
                        title_secondary=job.title_secondary, title_size=job.title_size,
                        pill_size=job.pill_size, thumb_bg=job.thumb_bg,
                        bg_color=job.bg_color, pill_color=job.pill_color,
                        lyric_size=job.lyric_size,
                        log=log, stage=stage, progress=progress)
                    job.outputs = outputs
                    job.status = "done"
                    job.stage = "done"
                    job.progress = 1.0
                    self._save(job)
            except Exception as e:  # noqa: BLE001
                job.status = "error"
                job.error = str(e)
                job.logs.append("ERROR: " + str(e))
                job.logs.append(traceback.format_exc())
                self._save(job)


manager = JobManager()
