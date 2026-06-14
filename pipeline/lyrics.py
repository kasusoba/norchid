"""LRCLIB: fetch synced (LRC) lyrics + expose candidates for the review step.

docs/ARCHITECTURE.md step [3], DECISIONS D4. Free, crowd-sourced, no key.
We prefer synced lyrics whose duration is closest to the separated audio.
"""

from __future__ import annotations

import httpx

API = "https://lrclib.net/api"
UA = "norchid/0.1 (https://github.com/kasusoba/norchid)"


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA}, timeout=20.0)


def _score(candidate: dict, duration: float) -> tuple:
    """Sort key: synced first, then closest duration."""
    has_synced = bool(candidate.get("syncedLyrics"))
    cand_dur = candidate.get("duration") or 0
    dur_gap = abs(cand_dur - duration) if duration else cand_dur
    return (not has_synced, dur_gap)


def search(artist: str, title: str, duration: float = 0.0) -> list[dict]:
    """Return LRC candidates, best first. Each dict carries syncedLyrics text."""
    candidates: list[dict] = []
    with _client() as c:
        # Exact get first (highest-confidence single match).
        try:
            params = {"artist_name": artist, "track_name": title}
            if duration:
                params["duration"] = int(round(duration))
            r = c.get(f"{API}/get", params=params)
            if r.status_code == 200:
                candidates.append(r.json())
        except httpx.HTTPError:
            pass

        # Broader search for alternatives the user can swap to in review.
        try:
            r = c.get(f"{API}/search",
                      params={"track_name": title, "artist_name": artist})
            if r.status_code == 200:
                candidates.extend(r.json())
        except httpx.HTTPError:
            pass

        # Last resort: free-text query.
        if not candidates:
            try:
                r = c.get(f"{API}/search", params={"q": f"{artist} {title}".strip()})
                if r.status_code == 200:
                    candidates.extend(r.json())
            except httpx.HTTPError:
                pass

    # De-dupe by id, keep order, then sort by quality.
    seen, deduped = set(), []
    for c in candidates:
        cid = c.get("id")
        if cid in seen:
            continue
        seen.add(cid)
        deduped.append(c)
    deduped.sort(key=lambda c: _score(c, duration))
    return deduped


def best_lrc(candidates: list[dict]) -> str | None:
    """The synced lyrics of the top candidate, if any."""
    for c in candidates:
        if c.get("syncedLyrics"):
            return c["syncedLyrics"]
    return None


def _solve_pow(prefix: str, target_hex: str, max_iters: int = 80_000_000) -> str | None:
    """Find a nonce so SHA256(prefix+nonce) <= target (LRCLIB proof-of-work)."""
    import hashlib
    target = bytes.fromhex(target_hex)
    for nonce in range(max_iters):
        if hashlib.sha256(f"{prefix}{nonce}".encode()).digest() <= target:
            return str(nonce)
    return None


def publish(track: str, artist: str, album: str, duration: int,
            plain: str, synced: str) -> tuple[bool, str]:
    """Publish a synced LRC to LRCLIB (solves their PoW challenge first)."""
    try:
        with _client() as c:
            ch = c.post(f"{API}/request-challenge")
            if ch.status_code != 200:
                return False, f"challenge failed ({ch.status_code})"
            d = ch.json()
            nonce = _solve_pow(d["prefix"], d["target"])
            if nonce is None:
                return False, "could not solve the proof-of-work"
            r = c.post(f"{API}/publish",
                       headers={"X-Publish-Token": f"{d['prefix']}:{nonce}"},
                       json={"trackName": track, "artistName": artist,
                             "albumName": album or track, "duration": duration,
                             "plainLyrics": plain, "syncedLyrics": synced})
        if r.status_code in (200, 201):
            return True, "Published to LRCLIB — thanks for contributing!"
        return False, f"LRCLIB rejected it ({r.status_code}): {r.text[:160]}"
    except httpx.HTTPError as e:
        return False, f"network error: {e}"


def candidate_summary(c: dict) -> dict:
    """Compact form for the review UI (no full lyric blobs in the list)."""
    return {
        "id": c.get("id"),
        "trackName": c.get("trackName"),
        "artistName": c.get("artistName"),
        "albumName": c.get("albumName"),
        "duration": c.get("duration"),
        "synced": bool(c.get("syncedLyrics")),
        "instrumental": bool(c.get("instrumental")),
    }
