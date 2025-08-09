
from __future__ import annotations
import requests
from typing import Optional

def discogs_search(artist: str, title: str, token: str) -> Optional[dict]:
    if not token:
        return None
    q = f"{title} {artist}".strip()
    url = "https://api.discogs.com/database/search"
    params = {"q": q, "type": "release", "token": token, "per_page": 1, "page": 1}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        j = r.json()
    except Exception:
        return None
    results = j.get("results") or []
    if not results:
        return None
    r0 = results[0]
    info = {
        "year": r0.get("year"),
        "genre": r0.get("genre"),
        "style": r0.get("style"),
        "country": r0.get("country"),
        "thumb": r0.get("thumb"),
        "discogs_id": r0.get("id"),
        "discogs_title": r0.get("title"),
        "label": r0.get("label"),
    }
    return info
