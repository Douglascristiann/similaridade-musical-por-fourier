# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, Dict, Any
import requests
import logging

log = logging.getLogger("FourierMatch")

def search_deezer(
    artist: Optional[str],
    track: Optional[str],
    album: Optional[str],
    q_fallback: str,
    limit: int = 5,
    timeout: int = 15
) -> Optional[Dict[str, Any]]:
    if artist and track:
        q = f'artist:"{artist}" track:"{track}"'
    elif artist:
        q = f'artist:"{artist}"'
    elif track:
        q = f'track:"{track}"'
    else:
        q = q_fallback
    
    try:
        r = requests.get("https://api.deezer.com/search", params={"q": q, "limit": limit}, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Erro na requisição para a API do Deezer: {e}")
        return None

    data = r.json() or {}
    items = data.get("data") or []
    if not items:
        return None

    d = items[0]
    alb_obj = d.get("album") or {}
    cover = alb_obj.get("cover_xl") or alb_obj.get("cover_big") or alb_obj.get("cover_medium")

    return {
        "title": d.get("title"),
        "artist": (d.get("artist") or {}).get("name"),
        "album": alb_obj.get("title"),
        "cover": cover,
        "genres": None,  # Deezer não retorna "genres" na busca de faixa
        "deezer_link": d.get("link"),
        "source": "deezer",
    }

# ==============================================================================
# === FUNÇÃO PRINCIPAL ADICIONADA PARA CORRIGIR O ERRO DE IMPORTAÇÃO ===
# ==============================================================================
def deezer_flow(artist: Optional[str], title: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Orquestrador que usa a sua função `search_deezer`.
    """
    log.info(f"Buscando no Deezer por: '{artist} - {title}'")
    fallback_query = f"{artist or ''} {title or ''}".strip()
    
    result = search_deezer(artist, title, None, fallback_query)
    
    if result and result.get("cover"):
        log.info(f"✅ Deezer encontrou uma capa para: {result.get('title')}")
        return {"cover": result.get("cover")} # Retorna apenas a informação que o metadata.py espera
    else:
        log.warning("⚠️ Deezer não encontrou resultados ou capa.")
        return None