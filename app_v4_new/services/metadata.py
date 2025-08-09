# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, Dict, Any, List
from pathlib import Path
import json, logging, re, unicodedata
from difflib import SequenceMatcher

from app_v4_new.config import DISCOGS_TOKEN, STRICT_METADATA, INSERT_ON_LOW_CONFIDENCE
from app_v4_new.recognition.recognizer import recognize_with_cache

log = logging.getLogger("FourierMatch")

try:
    from app_v4_new.integrations.spotify import enrich_from_spotify
    _HAS_SPOTIFY = True
except Exception:
    _HAS_SPOTIFY = False

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", s)
    s = re.sub(r"(?i)\b(ao vivo|live|oficial|official|audio|áudio|clipe|karaok[eê]|cover|lyric|vídeo|video|remix|vers[aã]o)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _ratio(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b: return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _artist_tokens(s: str) -> List[str]:
    s = _norm(s)
    s = re.sub(r"(?i)\b(feat\.?|com)\b", ",", s)
    return [t.strip() for t in re.split(r"[,&/x+]+", s) if t.strip()]

def _artist_match_ok(cand: str, hint: Optional[str]) -> bool:
    if not cand: return False
    if not hint: return True
    if _ratio(cand, hint) >= 0.65: return True
    cand_t = _artist_tokens(cand); hint_t = _artist_tokens(hint or "")
    for a in cand_t:
        for b in hint_t:
            if _ratio(a, b) >= 0.90: return True
    return False

def _parse_title_tokens(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not text: return None, None, None
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    parts = [p.strip() for p in t.split(" - ") if p.strip()]
    if len(parts) >= 3:
        return parts[0], " - ".join(parts[1:-1]), parts[-1]
    if len(parts) == 2:
        return parts[0], parts[1], None
    return None, parts[0] if parts else None, None

def _discogs_search(artist: Optional[str], track: Optional[str], album: Optional[str], q_fallback: str) -> Optional[Dict[str, Any]]:
    if not DISCOGS_TOKEN: return None
    try:
        import requests
        params = {"token": DISCOGS_TOKEN, "per_page": 5}
        if artist: params["artist"] = artist
        if track:  params["track"] = track
        if album:  params["release_title"] = album
        if not artist and not track and not album: params["q"] = q_fallback
        r = requests.get("https://api.discogs.com/database/search", params=params, timeout=15)
        if r.status_code != 200: return None
        data = r.json() or {}; results = data.get("results") or []
        if not results: return None
        best = results[0]
        title_full = best.get("title") or ""
        if " - " in title_full:
            a, t = title_full.split(" - ", 1)
            artist_out, title_out = a.strip(), t.strip()
        else:
            artist_out, title_out = (artist or ""), (track or title_full.strip())
        genres = []
        g = best.get("genre") or []; s = best.get("style") or []
        if isinstance(g, list): genres.extend(g)
        if isinstance(s, list): genres.extend(s)
        return {
            "title": title_out or None,
            "artist": artist_out or None,
            "album": best.get("title") or (album or None),
            "cover": best.get("cover_image") or None,
            "genres": list(dict.fromkeys(genres)) or None,
            "source": "discogs",
        }
    except Exception:
        return None

def _deezer_search(artist: Optional[str], track: Optional[str], album: Optional[str], q_fallback: str) -> Optional[Dict[str, Any]]:
    try:
        import requests
        if artist and track and album: q = f'artist:"{artist}" track:"{track}" album:"{album}"'
        elif artist and track:         q = f'artist:"{artist}" track:"{track}"'
        elif track:                    q = f'track:"{track}"'
        else:                          q = q_fallback
        r = requests.get("https://api.deezer.com/search", params={"q": q}, timeout=15)
        if r.status_code != 200: return None
        data = r.json() or {}; items = data.get("data") or []
        if not items: return None
        d = items[0]
        art = (d.get("artist") or {}).get("name")
        tit = d.get("title")
        alb = (d.get("album") or {}).get("title")
        alb_obj = d.get("album") or {}
        cover = alb_obj.get("cover_xl") or alb_obj.get("cover_big") or alb_obj.get("cover_medium") or alb_obj.get("cover")
        link = d.get("link")
        return {"title": tit or None, "artist": art or None, "album": alb or album or None,
                "cover": cover or None, "genres": None, "deezer_link": link or None, "source": "deezer"}
    except Exception:
        return None

def enrich_metadata(arquivo: Path, duration_sec: float, hints: Dict[str, Any]) -> Dict[str, Any]:
    artist_hint = hints.get("artist")
    track_hint  = hints.get("title")
    album_hint  = hints.get("album")
    yt_thumb    = hints.get("thumb")

    titulo = arquivo.stem
    artista = "desconhecido"
    album = genero = capa = None

    used_spotify = False
    if _HAS_SPOTIFY and (artist_hint or track_hint):
        try:
            log.info("🟢 Buscando no Spotify (metadados confiáveis)…")
            sp = enrich_from_spotify(artist_hint, track_hint, album_hint, duration_sec)
            if sp.get("accepted"):
                titulo  = sp.get("title")  or titulo
                artista = sp.get("artist") or artista
                album   = sp.get("album")  or album
                capa    = sp.get("cover")  or yt_thumb or capa
                g_list  = sp.get("genres")
                if g_list: genero = ", ".join(g_list)
                used_spotify = True
            else:
                log.info(f"Spotify não confirmou ({sp.get('reason')}). Indo para Discogs/Deezer…")
        except Exception as e:
            log.info(f"Spotify indisponível: {e}. Partindo para Discogs/Deezer…")

    if not used_spotify:
        q_fb = " ".join([p for p in [artist_hint, track_hint, album_hint] if p]) or arquivo.stem
        md = _discogs_search(artist_hint, track_hint, album_hint, q_fb)
        if md and (_artist_match_ok(md.get("artist",""), artist_hint)) and (_ratio(md.get("title",""), track_hint or "") >= 0.60):
            titulo = md.get("title") or titulo
            artista = md.get("artist") or artista
            album = md.get("album") or album_hint or album
            capa = md.get("cover") or yt_thumb or capa
            if md.get("genres"): genero = ", ".join(md["genres"]) if isinstance(md["genres"], list) else str(md["genres"])
        else:
            md2 = _deezer_search(artist_hint, track_hint, album_hint, q_fb)
            if md2 and (_artist_match_ok(md2.get("artist",""), artist_hint)) and (_ratio(md2.get("title",""), track_hint or "") >= 0.60):
                titulo = md2.get("title") or titulo
                artista = md2.get("artist") or artista
                album = md2.get("album") or album_hint or album
                capa = md2.get("cover") or yt_thumb or capa
                if md2.get("genres"): genero = ", ".join(md2["genres"]) if isinstance(md2["genres"], list) else str(md2["genres"])
            else:
                log.info("🎧 Tentando reconhecer pelo Shazam…")
                try:
                    rec = recognize_with_cache(arquivo, prefer_shazam_first=True)
                except TypeError:
                    rec = recognize_with_cache(arquivo)
                if rec and (rec.title or rec.artist):
                    if rec.title:  titulo = rec.title
                    if rec.artist: artista = rec.artist

    # Aceitação estrita
    accepted = True
    if STRICT_METADATA:
        a_ok = artista and artista != "desconhecido"
        t_ok = titulo and (titulo != arquivo.stem)
        if not (a_ok and t_ok):
            if not INSERT_ON_LOW_CONFIDENCE:
                accepted = False
            else:
                artista = artist_hint or artista
                titulo  = track_hint  or titulo
                album   = album_hint  or album
                capa    = yt_thumb    or capa
                accepted = True

    return {"title": titulo, "artist": artista, "album": album, "genres": genero, "cover": capa, "accepted": accepted}
