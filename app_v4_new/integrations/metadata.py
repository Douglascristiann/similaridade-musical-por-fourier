# app_v4_new/integrations/metadata.py
from __future__ import annotations
import re
import unicodedata
from typing import Optional, Dict, Any, Tuple
import requests

from app_v4_new.config import DISCOGS_TOKEN

def _strip_accents(s: str) -> str:
    try:
        return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    except Exception:
        return s

def guess_artist_title(filename_stem: str) -> Tuple[Optional[str], str, str]:
    """
    Tenta deduzir 'artista - título' do nome do arquivo.
    Remove sufixo '-<idDoYouTube>' se existir. Ex.: 'Daniela-jTK21XxJ3_g' -> ('None','Daniela').
    Retorna (artist|None, title, raw_query).
    """
    name = filename_stem.strip().replace("_", " ")
    m = re.match(r"^(.*?)-[A-Za-z0-9_-]{8,}$", name)  # remove '-<id>'
    if m:
        name = m.group(1).strip()
    raw_query = name
    if " - " in name:  # padrão 'Artista - Título'
        a, t = name.split(" - ", 1)
        return a.strip(), t.strip(), raw_query
    return None, name.strip(), raw_query

def _discogs_search(artist: Optional[str], title: Optional[str], query: str) -> Optional[Dict[str, Any]]:
    if not DISCOGS_TOKEN:
        return None
    try:
        params = {"token": DISCOGS_TOKEN, "per_page": 5}
        if artist: params["artist"] = artist
        if title:
            params["track"] = title
            params["release_title"] = title
        if not artist and not title:
            params["q"] = query

        r = requests.get("https://api.discogs.com/database/search", params=params, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json() or {}
        results = data.get("results") or []
        if not results:
            return None

        best = results[0]
        title_full = best.get("title") or ""
        if " - " in title_full:
            a, t = title_full.split(" - ", 1)
            artist_out, title_out = a.strip(), t.strip()
        else:
            artist_out, title_out = artist or "", title or title_full.strip()

        genres = []
        g = best.get("genre") or []
        s = best.get("style") or []
        if isinstance(g, list): genres.extend(g)
        if isinstance(s, list): genres.extend(s)

        return {
            "title": title_out or None,
            "artist": artist_out or None,
            "album": best.get("title") or None,  # 'release title' como proxy
            "cover": best.get("cover_image") or None,
            "genres": list(dict.fromkeys(genres)) or None,
            "source": "discogs",
        }
    except Exception:
        return None

def _deezer_search(artist: Optional[str], title: Optional[str], query: str) -> Optional[Dict[str, Any]]:
    try:
        if artist and title:
            q = f'artist:"{artist}" track:"{title}"'
        elif title:
            q = f'track:"{title}"'
        else:
            q = query
        r = requests.get("https://api.deezer.com/search", params={"q": q}, timeout=15)
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
        cover = (d.get("album") or {}).get("cover_medium") or (d.get("album") or {}).get("cover")
        link = d.get("link")
        return {
            "title": tit or None,
            "artist": art or None,
            "album": alb or None,
            "cover": cover or None,
            "genres": None,   # Deezer não retorna gênero direto aqui
            "deezer_link": link or None,
            "source": "deezer",
        }
    except Exception:
        return None

def enrich_metadata_prefer_discogs_deezer(file_stem: str) -> Dict[str, Any]:
    """
    Tenta Discogs -> Deezer usando heurística do nome do arquivo.
    Se ainda faltar título ou artista, quem chama decide acionar Shazam.
    """
    artist_guess, title_guess, raw_query = guess_artist_title(file_stem)
    # 1) Discogs
    disc = _discogs_search(artist_guess, title_guess, raw_query)
    if disc and disc.get("title") and disc.get("artist"):
        return disc
    # 2) Deezer
    deez = _deezer_search(artist_guess, title_guess, raw_query)
    if deez and deez.get("title") and deez.get("artist"):
        return deez
    # Parciais (Discogs sem artista ou Deezer sem artista…)
    return disc or deez or {}
