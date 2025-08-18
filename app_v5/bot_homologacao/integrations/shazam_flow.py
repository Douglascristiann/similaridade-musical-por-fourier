from __future__ import annotations
import asyncio
from typing import Dict, Any, Optional, Tuple

try:
    # shazamio é async
    from shazamio import Shazam
except Exception as e:
    Shazam = None  # será verificado em runtime

def _extract_track_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai (de forma tolerante) campos úteis do retorno do shazamio."""
    tr = (data or {}).get("track") or {}
    title  = tr.get("title") or ""
    artist = tr.get("subtitle") or ""
    isrc   = tr.get("isrc") or ""
    # tenta achar possível URL do YouTube (quando disponível)
    yt_url = None
    # alguns payloads trazem seção com youtube
    for sec in tr.get("sections", []) or []:
        if isinstance(sec, dict) and sec.get("type") == "VIDEO":
            videos = sec.get("youtubeurl") or sec.get("youtube") or []
            # dependendo da versão, pode vir como lista de dicts com "url"
            if isinstance(videos, list):
                for v in videos:
                    url = (v or {}).get("url") or (v or {}).get("uri")
                    if url and "youtube" in url:
                        yt_url = url
                        break
            elif isinstance(videos, dict):
                url = videos.get("url") or videos.get("uri")
                if url and "youtube" in url:
                    yt_url = url
        if yt_url:
            break
    return {"title": title, "artist": artist, "isrc": isrc, "yt_url": yt_url, "raw": tr}

async def recognize_snippet(audio_path: str) -> Dict[str, Any]:
    """
    Reconhece um trecho de áudio via Shazam.
    Retorna: {"ok": bool, "title": str, "artist": str, "isrc": str, "yt_url": Optional[str], "raw": dict}
    """
    if Shazam is None:
        return {"ok": False, "error": "Biblioteca 'shazamio' não instalada. Adicione em requirements."}
    shazam = Shazam()
    try:
        data = await shazam.recognize_song(audio_path)
    except Exception as e:
        return {"ok": False, "error": f"Falha no Shazam: {e}"}
    fields = _extract_track_fields(data)
    ok = bool(fields.get("title") and fields.get("artist"))
    return {"ok": ok, **fields}

def build_yt_search_query(title: str, artist: str) -> str:
    """
    Monta uma busca do yt-dlp: baixa o primeiro resultado relevante.
    """
    base = (artist or "").strip() + " " + (title or "").strip()
    base = base.strip() or "audio"
    # Preferir busca por áudio oficial
    return f"ytsearch1:{base} audio"

async def recognize_and_pick_youtube(audio_path: str) -> Dict[str, Any]:
    """
    Faz o reconhecimento e define a URL de destino no YouTube (ou uma ytsearch1:...).
    Retorna:
      {"ok": bool, "title":..., "artist":..., "isrc":..., "target": "url_ou_ytsearch1:...", "from": "direct|search", ...}
    """
    r = await recognize_snippet(audio_path)
    if not r.get("ok"):
        return r
    yt = r.get("yt_url")
    if yt:
        return {**r, "target": yt, "from": "direct"}
    # fallback: busca
    target = build_yt_search_query(r.get("title",""), r.get("artist",""))
    return {**r, "target": target, "from": "search"}
