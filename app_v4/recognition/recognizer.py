
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
from pathlib import Path
import hashlib
import os

try:
    from dotenv import load_dotenv  # optional
    load_dotenv()
except Exception:
    pass

from ..config import AUDD_API_TOKEN, DISCOGS_TOKEN, SHAZAM_ENABLE
from .clients_audd import audd_recognize_file
from .clients_shazam import shazam_recognize_file
from .clients_discogs import discogs_search
from ..storage.db_utils import upsert_recognition, get_recognition, ensure_schema

@dataclass
class RecognitionResult:
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    isrc: Optional[str] = None
    source: Optional[str] = None
    confidence: float = 0.0
    extras: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "title": self.title, "artist": self.artist, "album": self.album,
            "isrc": self.isrc, "source": self.source, "confidence": float(self.confidence),
        }
        if self.extras:
            d.update(self.extras)
        return d

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

def recognize_with_cache(db_path: str | Path, file_path: str | Path, use_cache: bool = True) -> RecognitionResult:
    ensure_schema(db_path)
    h = _file_hash(file_path)
    if use_cache:
        cached = get_recognition(db_path, h)
        if cached:
            return RecognitionResult(
                title=cached.get("title"),
                artist=cached.get("artist"),
                album=cached.get("album"),
                isrc=cached.get("isrc"),
                source=cached.get("source"),
                confidence=float(cached.get("confidence") or 0.0),
                extras=cached,
            )

    # Pipeline: Shazam (if enabled) -> AudD -> (optional) Discogs enrichment
    result = None
    if SHAZAM_ENABLE:
        result = shazam_recognize_file(str(file_path))
    if not result and AUDD_API_TOKEN:
        result = audd_recognize_file(str(file_path), AUDD_API_TOKEN)
    if not result:
        result = {"title": None, "artist": None, "album": None, "isrc": None, "source": None, "confidence": 0.0}

    # Discogs enrichment (when we have artist/title)
    if result.get("artist") and result.get("title") and DISCOGS_TOKEN:
        info = discogs_search(result["artist"], result["title"], DISCOGS_TOKEN)
        if info:
            result.update({"discogs": info})

    # Persist cache
    upsert_recognition(db_path, h, result)
    return RecognitionResult(
        title=result.get("title"),
        artist=result.get("artist"),
        album=result.get("album"),
        isrc=result.get("isrc"),
        source=result.get("source"),
        confidence=float(result.get("confidence") or 0.0),
        extras=result,
    )
