# app_v4_new/recognition/recognizer.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
from pathlib import Path
import hashlib
import os

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

from app_v4_new.config import AUDD_TOKEN

@dataclass
class RecognitionResult:
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    isrc: Optional[str] = None
    source: Optional[str] = None
    confidence: float = 0.0
    extras: Dict[str, Any] | None = None

_MEMO: Dict[str, dict] = {}

def _file_hash(path: str | Path, algo: str = "sha1", chunk: int = 1024 * 1024) -> str:
    p = Path(path)
    h = hashlib.new(algo)
    with p.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def _audd(file_path: str) -> Optional[dict]:
    if not AUDD_TOKEN:
        return None
    try:
        import requests  # type: ignore
    except Exception:
        return None
    try:
        p = Path(file_path)
        files = {"file": (p.name, p.read_bytes())}
        data = {"api_token": AUDD_TOKEN, "return": "apple_music,spotify"}
        r = requests.post("https://api.audd.io/", data=data, files=files, timeout=30)
        r.raise_for_status()
        j = r.json()
        if not j or j.get("status") != "success" or not j.get("result"):
            return None
        res = j["result"]
        return {
            "title": res.get("title"),
            "artist": res.get("artist"),
            "album": res.get("album"),
            "isrc": res.get("isrc"),
            "source": "audd",
            "confidence": float(res.get("score") or 0.0) if isinstance(res, dict) else 0.0,
            "raw_audd": res,
        }
    except Exception:
        return None

def _shazam(file_path: str) -> Optional[dict]:
    try:
        from shazamio import Shazam  # type: ignore
        import asyncio
    except Exception:
        return None

    async def _run(path: str):
        try:
            shazam = Shazam()
            out = await shazam.recognize(path)  # método atual
        except Exception:
            return None
        if not out:
            return None
        track = out.get("track") or {}
        title = track.get("title")
        artist = track.get("subtitle")
        isrc = None
        for s in track.get("sections") or []:
            if isinstance(s, dict) and s.get("type") == "SONG":
                for m in s.get("metadata") or []:
                    if m.get("title") == "ISRC":
                        isrc = m.get("text"); break
        return {
            "title": title,
            "artist": artist,
            "album": None,
            "isrc": isrc,
            "source": "shazam",
            "confidence": 1.0 if title and artist else 0.0,
            "raw_shazam": out,
        }

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    try:
        if loop.is_running():
            new_loop = asyncio.new_event_loop()
            res = new_loop.run_until_complete(_run(str(file_path)))
            new_loop.close()
            return res
        else:
            return loop.run_until_complete(_run(str(file_path)))
    except Exception:
        return None

def recognize_with_cache(file_path: str | Path, prefer_shazam_first: bool = True) -> RecognitionResult:
    key = _file_hash(file_path)
    if key in _MEMO:
        r = _MEMO[key]
        return RecognitionResult(r.get("title"), r.get("artist"), r.get("album"),
                                 r.get("isrc"), r.get("source"), float(r.get("confidence") or 0.0), r)

    result = None
    if prefer_shazam_first:
        result = _shazam(str(file_path))
    if not result:
        result = _audd(str(file_path))
    if not result:
        result = {"title": None, "artist": None, "album": None, "isrc": None, "source": None, "confidence": 0.0}

    _MEMO[key] = result
    return RecognitionResult(
        title=result.get("title"),
        artist=result.get("artist"),
        album=result.get("album"),
        isrc=result.get("isrc"),
        source=result.get("source"),
        confidence=float(result.get("confidence") or 0.0),
        extras=result,
    )
