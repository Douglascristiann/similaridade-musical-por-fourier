# -*- coding: utf-8 -*-
"""
Integração Deezer — busca por query estruturada (artist/track/album).
Retorna dict padronizado:
{
  "title": str|None, "artist": str|None, "album": str|None,
  "cover": str|None, "genres": None, "deezer_link": str|None, "source": "deezer"
}
"""
from __future__ import annotations
from typing import Optional, Dict, Any
import requests

def search_deezer(
    artist: Optional[str],
    track: Optional[str],
    album: Optional[str],
    q_fallback: str,
    limit: int = 5,
    timeout: int = 15
) -> Optional[Dict[str, Any]]:
    if artist and track and album:
        q = f'artist:"{artist}" track:"{track}" album:"{album}"'
    elif artist and track:
        q = f'artist:"{artist}" track:"{track}"'
    elif track:
        q = f'track:"{track}"'
    else:
        q = q_fallback

    r = requests.get("https://api.deezer.com/search", params={"q": q, "limit": limit}, timeout=timeout)
    if r.status_code != 200:
        return None

    data = r.json() or {}
    items = data.get("data") or []
    if not items:
        return None

    d = items[0]
    art = (d.get("artist") or {}).get("name")
    tit = d.get("title")
    alb = (d.get("album") or {}).get("title")
    alb_obj = d.get("album") or {}
    cover = alb_obj.get("cover_xl") or alb_obj.get("cover_big") or alb_obj.get("cover_medium") or alb_obj.get("cover")
    link = d.get("link")

    return {
        "title": tit or None,
        "artist": art or None,
        "album": alb or album or None,
        "cover": cover or None,
        "genres": None,              # Deezer não retorna “genres” aqui
        "deezer_link": link or None,
        "source": "deezer",
    }
