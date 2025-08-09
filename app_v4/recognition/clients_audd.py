
from __future__ import annotations
import requests
from pathlib import Path
from typing import Optional

AUDD_URL = "https://api.audd.io/"

def audd_recognize_file(file_path: str, api_token: str, return_fields: str = "apple_music,spotify") -> Optional[dict]:
    if not api_token:
        return None
    p = Path(file_path)
    files = {"file": (p.name, p.read_bytes())}
    data = {"api_token": api_token, "return": return_fields}
    try:
        r = requests.post(AUDD_URL, data=data, files=files, timeout=30)
        r.raise_for_status()
    except Exception:
        return None
    try:
        j = r.json()
    except Exception:
        return None
    if not j or j.get("status") != "success" or not j.get("result"):
        return None
    res = j["result"]
    out = {
        "title": res.get("title"),
        "artist": res.get("artist"),
        "album": res.get("album"),
        "isrc": res.get("isrc"),
        "source": "audd",
        "confidence": float(res.get("score") or 0.0) if isinstance(res, dict) else 0.0,
        "raw_audd": res,
    }
    return out
