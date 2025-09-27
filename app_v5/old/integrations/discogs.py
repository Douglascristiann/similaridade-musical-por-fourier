# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, Dict, Any, List
import requests
import logging

try:
    from app_v5.config import DISCOGS_TOKEN
except ImportError:
    DISCOGS_TOKEN = None

log = logging.getLogger("FourierMatch")

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
    # A API do Discogs funciona melhor com release_title e artist
    if artist: params["artist"] = artist
    if track:  params["release_title"] = track
    if album and not track: params["release_title"] = album # Usa album se não tiver track
    
    # Fallback se não houver hints suficientes
    if not artist and not track and not album:
        params["q"] = q_fallback

    try:
        r = requests.get("https://api.discogs.com/database/search", params=params, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Erro na requisição para a API do Discogs: {e}")
        return None

    data = r.json() or {}
    results: List[dict] = data.get("results") or []
    if not results:
        return None

    best = results[0]
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
    
    return {
        "title": title_out or None,
        "artist": artist_out or None,
        "album": best.get("title") or (album or None),
        "cover": best.get("cover_image") or None,
        "genres": list(dict.fromkeys(genres)) if genres else [],
        "release_year": str(best.get("year")) if best.get("year") else None,
        "source": "discogs",
    }

# ==============================================================================
# === FUNÇÃO PRINCIPAL ADICIONADA PARA CORRIGIR O ERRO DE IMPORTAÇÃO ===
# ==============================================================================
def discogs_flow(artist: Optional[str], title: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Orquestrador que usa a sua função `search_discogs`.
    """
    log.info(f"Buscando no Discogs por: '{artist} - {title}'")
    fallback_query = f"{artist or ''} {title or ''}".strip()
    
    result = search_discogs(artist, title, None, fallback_query)
    
    if result and result.get("genres"):
        log.info(f"✅ Discogs encontrou: {result.get('title')}")
        return result
    else:
        log.warning("⚠️ Discogs não encontrou resultados ou gêneros.")
        return None