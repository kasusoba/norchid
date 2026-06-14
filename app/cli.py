"""norchid CLI — run the full chain headless (Phase 1 / ROADMAP).

    python -m app.cli <youtube_url> [options]

Runs download -> separate -> lyrics -> cover -> render -> thumbnail with no
review pause (auto-picks the best LRC; override with --lrc-file / --offset).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from app import config
from pipeline import runner


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="norchid", description=__doc__)
    p.add_argument("url", help="YouTube URL")
    p.add_argument("--sep-model", default=config.DEFAULT_SEP_MODEL,
                   choices=list(config.SEP_MODELS), help="separation model")
    p.add_argument("--offset", type=int, default=0, dest="offset_ms",
                   help="global lyric offset in ms (+ delays lyrics)")
    p.add_argument("--title-secondary", default=None,
                   help="optional Japanese/secondary thumbnail title (auto-fetched if omitted)")
    p.add_argument("--title-size", type=int, default=config.THUMB_TITLE_SIZE,
                   help="cinematic thumbnail title size (px)")
    p.add_argument("--vocal-mode", default="instrumental",
                   choices=["instrumental", "guide"], help="guide-vocal mix")
    p.add_argument("--bg-mode", default=config.DEFAULT_BG_MODE,
                   choices=list(config.BG_MODES), help="video background mode")
    p.add_argument("--lrc-file", type=Path, default=None,
                   help="use a custom .lrc file instead of LRCLIB")
    p.add_argument("--out-dir", type=Path, default=config.OUTPUTS,
                   help="where to copy final outputs")
    p.add_argument("--keep-workspace", action="store_true",
                   help="keep the per-job working dir")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    job_id = uuid.uuid4().hex[:10]
    work_dir = config.WORKSPACE / job_id
    out_dir = args.out_dir

    def log(msg: str) -> None:
        print(msg, flush=True)

    def stage(s: str) -> None:
        print(f"[{s}]", flush=True)

    try:
        ctx = runner.prepare(args.url, work_dir, args.sep_model,
                             log=log, stage=stage)

        lrc = ctx["lrc"]
        if args.lrc_file:
            lrc = args.lrc_file.read_text(encoding="utf-8")
            log(f"Using custom LRC from {args.lrc_file}")
        if not lrc:
            log("WARNING: no synced lyrics found — video will have no lyrics. "
                "Provide --lrc-file to add them.")

        outputs = runner.finalize(
            ctx, work_dir, out_dir,
            lrc=lrc, offset_ms=args.offset_ms,
            vocal_mode=args.vocal_mode, bg_mode=args.bg_mode,
            title_secondary=args.title_secondary, title_size=args.title_size,
            log=log, stage=stage)
    except Exception as e:  # noqa: BLE001
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1

    print("\n=== OUTPUTS ===")
    for k, v in outputs.items():
        print(f"  {k}: {v}")
    if not args.keep_workspace:
        log(f"(workspace kept at {work_dir}; instrumental already copied to outputs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
