# -*- coding: utf-8 -*-
"""
Integração Discogs — busca metadados por artista/faixa/álbum.
Retorna dict padronizado:
{
  "title": str|None, "artist": str|None, "album": str|None,
  "cover": str|None, "genres": list[str]|None, "source": "discogs"
}
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
import requests

from app_v5.config import DISCOGS_TOKEN

def search_discogs(
    artist: Optional[str],
    track: Optional[str],
    album: Optional[str],
    q_fallback: str,
    token: Optional[str] = None,
    per_page: int = 5,
    timeout: int = 15
) -> Optional[Dict[str, Any]]:
    tok = token or DISCOGS_TOKEN
    if not tok:
        return None

    params: Dict[str, Any] = {"token": tok, "per_page": per_page}
    if artist: params["artist"] = artist
    if track:  params["track"] = track
    if album:  params["release_title"] = album
    if not artist and not track and not album:
        params["q"] = q_fallback

    r = requests.get("https://api.discogs.com/database/search", params=params, timeout=timeout)
    if r.status_code != 200:
        return None

    data = r.json() or {}
    results: List[dict] = data.get("results") or []
    if not results:
        return None

    best = results[0]
    # many Discogs results vêm no formato "ARTISTA - TÍTULO"
    title_full = best.get("title") or ""
    if " - " in title_full:
        a, t = title_full.split(" - ", 1)
        artist_out, title_out = a.strip(), t.strip()
    else:
        artist_out, title_out = (artist or ""), (track or title_full.strip())

    genres: List[str] = []
    g = best.get("genre") or []; s = best.get("style") or []
    if isinstance(g, list): genres.extend(g)
    if isinstance(s, list): genres.extend(s)
    genres = list(dict.fromkeys(genres)) if genres else None

    return {
        "title": title_out or None,
        "artist": artist_out or None,
        "album": best.get("title") or (album or None),
        "cover": best.get("cover_image") or None,
        "genres": genres,
        "source": "discogs",
    }
