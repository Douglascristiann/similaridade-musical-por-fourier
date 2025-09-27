# -*- coding: utf-8 -*-
"""
Integração Shazam (via shazamio) com cache simples por hash do arquivo.
Retorna RecResult(title, artist) ou None.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, hashlib, asyncio

CACHE_PATH = Path(__file__).resolve().parents[1] / "cache" / "shazam_cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

@dataclass
class RecResult:
    title: str | None
    artist: str | None

def _hash_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _cache_load() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _cache_save(d: dict) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def recognize_with_cache(path: Path) -> RecResult | None:
    key = _hash_file(Path(path))
    cache = _cache_load()
    if key in cache:
        d = cache[key]
        return RecResult(title=d.get("title"), artist=d.get("artist"))

    try:
        from shazamio import Shazam  # pip install shazamio
    except Exception:
        return None

    async def _run(p: Path):
        shazam = Shazam()
        out = await shazam.recognize_song(str(p))
        try:
            track = out["track"]
            title  = track.get("title")
            artist = track.get("subtitle")
            return title, artist
        except Exception:
            return None, None

    try:
        title, artist = asyncio.get_event_loop().run_until_complete(_run(Path(path)))
        if title or artist:
            cache[key] = {"title": title, "artist": artist}
            _cache_save(cache)
            return RecResult(title=title, artist=artist)
    except Exception:
        return None
    return None
