# -*- coding: utf-8 -*-
"""
Spotify Client Credentials: busca faixa e valida por duração/artista/título.
Retorna dict:
  { accepted: bool, title, artist, album, cover, genres, reason }
"""
from __future__ import annotations
import base64, time
from typing import Optional, Dict, Any, List
import requests

from app_v5.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_MARKET

_TOKEN_VAL: dict = {"access_token": None, "exp": 0.0}

def _get_token() -> Optional[str]:
    global _TOKEN_VAL
    now = time.time()
    if _TOKEN_VAL["access_token"] and _TOKEN_VAL["exp"] > now + 30:
        return _TOKEN_VAL["access_token"]
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    auth = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    r = requests.post(
       "https://accounts.spotify.com/api/token",
       data={"grant_type":"client_credentials"},
       headers={"Authorization": f"Basic {auth}"}, timeout=15
    )
    if r.status_code != 200:
        return None
    data = r.json()
    _TOKEN_VAL["access_token"] = data.get("access_token")
    _TOKEN_VAL["exp"] = time.time() + float(data.get("expires_in", 3600))
    return _TOKEN_VAL["access_token"]

def _search_track(q: str, market: str = "BR", limit: int = 5) -> List[dict]:
    tok = _get_token()
    if not tok: return []
    r = requests.get(
        "https://api.spotify.com/v1/search",
        params={"q": q, "type": "track", "limit": limit, "market": market},
        headers={"Authorization": f"Bearer {tok}"}, timeout=20
    )
    if r.status_code != 200:
        return []
    return (r.json().get("tracks") or {}).get("items") or []

def _ratio(a: str, b: str) -> float:
    import unicodedata, re
    from difflib import SequenceMatcher
    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", s)
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s
    return SequenceMatcher(None, norm(a), norm(b)).ratio()

def enrich_from_spotify(artist_hint: str|None, title_hint: str|None, album_hint: str|None, duration_sec: float|None) -> Dict[str, Any]:
    if not title_hint and not artist_hint:
        return {"accepted": False, "reason": "no_query"}
    # Monta queries do mais restrito ao mais permissivo
    queries = []
    if artist_hint and title_hint and album_hint:
        queries.append(f'track:"{title_hint}" artist:"{artist_hint}" album:"{album_hint}"')
    if artist_hint and title_hint:
        queries.append(f'track:"{title_hint}" artist:"{artist_hint}"')
    if title_hint:
        queries.append(f'track:"{title_hint}"')
    if not queries:
        queries.append(f'{artist_hint or ""} {title_hint or ""}'.strip())

    items = []
    for q in queries:
        items = _search_track(q, market=SPOTIFY_MARKET, limit=5)
        if items: break
    if not items:
        return {"accepted": False, "reason": "no_results"}

    # pick best
    best, best_s = None, -1.0
    for it in items:
        tit = it.get("name") or ""
        arts = ", ".join(a["name"] for a in it.get("artists", []))
        dur_ms = int(it.get("duration_ms") or 0)
        dur_ok = True
        if duration_sec:
            delta = abs(dur_ms/1000.0 - float(duration_sec))
            dur_ok = (delta <= max(5.0, 0.08*max(dur_ms/1000.0, float(duration_sec))))
        s = 0.6*_ratio(tit, title_hint or tit) + 0.4*_ratio(arts, artist_hint or arts)
        if dur_ok and s > best_s:
            best_s, best = s, it

    if not best:
        return {"accepted": False, "reason": "no_match"}

    alb = best.get("album") or {}
    imgs = alb.get("images") or []
    cover = imgs[0]["url"] if imgs else None
    arts = ", ".join(a["name"] for a in best.get("artists", []))
    genres = []  # requer outra chamada na API do artista; omitimos por simplicidade

    accepted = (best_s >= 0.62)
    return {
        "accepted": accepted,
        "reason": "ok" if accepted else "low_score",
        "title": best.get("name"),
        "artist": arts,
        "album": alb.get("name"),
        "cover": cover,
        "genres": genres
    }
