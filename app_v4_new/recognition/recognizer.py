
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

from config import AUDD_TOKEN  # usa seu token do config.py

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

def recognize_with_cache(file_path: str | Path) -> RecognitionResult:
    key = _file_hash(file_path)
    if key in _MEMO:
        r = _MEMO[key]
        return RecognitionResult(r.get("title"), r.get("artist"), r.get("album"),
                                 r.get("isrc"), r.get("source"), float(r.get("confidence") or 0.0), r)
    # Somente AudD nesta versão (Shazam opcional; pode ser adicionado se quiser)
    result = _audd(str(file_path)) or {"title": None, "artist": None, "album": None, "isrc": None, "source": None, "confidence": 0.0}
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
