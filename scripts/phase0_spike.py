"""Phase 0 spike: prove ASS scrolling lyrics + CJK fonts render over a flat
background via ffmpeg at 1080p60 — including Japanese and Hangul lines (no tofu).

Run:  .venv/bin/python -m scripts.phase0_spike
Produces outputs/phase0/spike.mp4 plus verification frames.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app import config
from pipeline import ass_render, video

OUT = config.ROOT / "outputs" / "phase0"

# Multi-script sample: romaji/Latin, hiragana+kanji, katakana, Hangul.
SAMPLE_LRC = """[ar:norchid]
[ti:Phase 0 Spike]
[00:00.00] norchid renderer spike
[00:02.50] Spotify-style scrolling lyrics
[00:05.00] こんにちは世界
[00:07.50] 夜に駆ける 星空の下
[00:10.00] カタカナ テスト ライン
[00:12.50] 안녕하세요 세계
[00:15.00] 노래방 카라오케
[00:17.50] romaji: yoru ni kakeru
[00:20.00] 日本語 and 한글 together
[00:22.50] no tofu — every script renders
"""
DURATION = 25.0
BG_RGB = (38, 48, 66)  # calm mid-dark Spotify-style field


def make_flat_bg(rgb, path: Path) -> None:
    color = "0x{:02X}{:02X}{:02X}".format(*rgb)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"color=c={color}:s={config.WIDTH}x{config.HEIGHT}", "-frames:v", "1", str(path)],
        check=True, capture_output=True,
    )


def make_tone_wav(path: Path, seconds: float) -> None:
    # A gentle two-tone bed so "audio is the instrumental" is audible/verifiable.
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"sine=frequency=220:duration={seconds}", "-f", "lavfi", "-i",
         f"sine=frequency=330:duration={seconds}",
         "-filter_complex", "[0][1]amix=inputs=2,volume=0.4", str(path)],
        check=True, capture_output=True,
    )


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def extract_frame(video_path: Path, t: float, out_png: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(t), "-i", str(video_path),
         "-frames:v", "1", str(out_png)],
        check=True, capture_output=True,
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    video.ensure_ffmpeg()

    bg = OUT / "background.png"
    wav = OUT / "instrumental.wav"
    ass = OUT / "lyrics.ass"
    mp4 = OUT / "spike.mp4"

    print("• Generating flat background + tone wav…")
    make_flat_bg(BG_RGB, bg)
    make_tone_wav(wav, DURATION)

    print("• Parsing LRC + writing ASS…")
    lines = ass_render.write_ass(SAMPLE_LRC, str(ass), duration=DURATION)
    print(f"  parsed {len(lines)} lyric lines; first='{lines[0].text}'")

    print("• Composing 1080p60 MP4 (ffmpeg + libass)…")
    video.compose_video(bg, wav, ass, mp4, fps=config.FPS)

    info = probe(mp4)
    vstream = next(s for s in info["streams"] if s["codec_type"] == "video")
    astream = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    w, h = vstream["width"], vstream["height"]
    num, den = (vstream["r_frame_rate"].split("/") + ["1"])[:2]
    fps = round(int(num) / int(den))
    dur = float(info["format"]["duration"])
    print(f"  -> {w}x{h} @ {fps}fps, {dur:.1f}s, "
          f"audio={astream['codec_name'] if astream else 'NONE'}")

    # Verification frames: a Japanese line (t=6s -> 夜に駆ける active region) and a
    # Hangul line (t=13s -> 안녕하세요 active). View these to confirm no tofu.
    extract_frame(mp4, 6.0, OUT / "frame_japanese.png")
    extract_frame(mp4, 13.0, OUT / "frame_hangul.png")
    extract_frame(mp4, 21.0, OUT / "frame_mixed.png")
    print("• Extracted verification frames: frame_japanese/hangul/mixed.png")

    # Acceptance assertions.
    ok = (w == config.WIDTH and h == config.HEIGHT and fps == config.FPS
          and astream is not None and abs(dur - DURATION) < 1.5)
    print("\nACCEPTANCE:", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
