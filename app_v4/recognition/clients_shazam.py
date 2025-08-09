
from __future__ import annotations
from typing import Optional
from pathlib import Path

async def _shazam_async_recognize(file_path: str) -> Optional[dict]:
    try:
        from shazamio import Shazam
    except Exception:
        return None
    try:
        shazam = Shazam()
        out = await shazam.recognize_song(file_path)
    except Exception:
        return None
    if not out:
        return None
    # heuristic mapping
    track = out.get("track") or {}
    title = track.get("title")
    subtitle = track.get("subtitle")  # artist
    sections = track.get("sections") or []
    isrc = None
    for s in sections:
        if isinstance(s, dict) and s.get("type") == "SONG":
            meta = s.get("metadata") or []
            for m in meta:
                if m.get("title") == "ISRC":
                    isrc = m.get("text")
                    break
    return {
        "title": title,
        "artist": subtitle,
        "album": None,
        "isrc": isrc,
        "source": "shazam",
        "confidence": 1.0 if title and subtitle else 0.0,
        "raw_shazam": out,
    }

def shazam_recognize_file(file_path: str) -> Optional[dict]:
    # bridge to sync
    try:
        import asyncio
    except Exception:
        return None
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    try:
        if loop.is_running():
            # in running loop, create new loop policy
            new_loop = asyncio.new_event_loop()
            res = new_loop.run_until_complete(_shazam_async_recognize(file_path))
            new_loop.close()
            return res
        else:
            return loop.run_until_complete(_shazam_async_recognize(file_path))
    except Exception:
        return None
