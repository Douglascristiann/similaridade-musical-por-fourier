# app_v5/integrations/deezer.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, Dict, Any
import requests

DEEZER_API_BASE_URL = "https://api.deezer.com"

# =============================================================
# FUNÇÃO EXISTENTE (MANTIDA PARA COMPATIBILIDADE)
# =============================================================
def search_deezer(
    artist: Optional[str],
    track: Optional[str],
    album: Optional[str],
    q_fallback: str,
    limit: int = 5,
    timeout: int = 15
) -> Optional[Dict[str, Any]]:
    """
    Função de busca genérica na Deezer. Mantida para os outros fluxos do sistema.
    """
    if artist and track and album:
        q = f'artist:"{artist}" track:"{track}" album:"{album}"'
    elif artist and track:
        q = f'artist:"{artist}" track:"{track}"'
    elif track:
        q = f'track:"{track}"'
    else:
        q = q_fallback

    try:
        r = requests.get(f"{DEEZER_API_BASE_URL}/search", params={"q": q, "limit": limit}, timeout=timeout)
        r.raise_for_status()

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
        
        return {
            "title": tit, "artist": art, "album": alb,
            "cover": cover, "genres": None, "deezer_link": d.get("link"), "source": "deezer"
        }
    except requests.RequestException:
        return None

# =============================================================
# NOVA FUNÇÃO (USADA PELO SCRIPT backfill_metadata.py)
# =============================================================
def enrich_from_deezer(artist_hint: str, title_hint: str) -> Optional[Dict[str, Any]]:
    """
    Busca metadados na Deezer, com foco específico em extrair o gênero do álbum.
    """
    if not artist_hint or not title_hint:
        return None

    query = f'artist:"{artist_hint}" track:"{title_hint}"'
    
    try:
        # Busca pela faixa exata
        search_response = requests.get(
            f"{DEEZER_API_BASE_URL}/search",
            params={"q": query, "limit": 1},
            timeout=15
        )
        search_response.raise_for_status()
        search_data = search_response.json()
        
        tracks = search_data.get("data", [])
        if not tracks:
            return None

        track_info = tracks[0]
        album_id = track_info.get("album", {}).get("id")

        if not album_id:
            return None

        # Busca os detalhes do álbum para pegar o gênero
        album_response = requests.get(
            f"{DEEZER_API_BASE_URL}/album/{album_id}",
            timeout=15
        )
        album_response.raise_for_status()
        album_data = album_response.json()

        genres_data = album_data.get("genres", {}).get("data", [])
        if not genres_data:
            return None

        genres = [genre.get("name") for genre in genres_data if genre.get("name")]
        
        if not genres:
            return None

        return {
            "genres": genres,
            "source": "deezer"
        }

    except requests.RequestException:
        return None