# -*- coding: utf-8 -*-
"""
Orquestra metadados: Spotify → (Discogs → Deezer) → Shazam.
Valida contra hints (título/artista) e respeita STRICT_METADATA.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
from pathlib import Path
import json, logging, re, unicodedata
from difflib import SequenceMatcher

from app_v4_new.config import DISCOGS_TOKEN, STRICT_METADATA, INSERT_ON_LOW_CONFIDENCE

# integrações moduladas (mesma pasta do spotify.py)
from app_v4_new.integrations.spotify import enrich_from_spotify
from app_v4_new.integrations.discogs import search_discogs
from app_v4_new.integrations.deezer  import search_deezer
from app_v4_new.integrations.shazam_api import recognize_with_cache

log = logging.getLogger("FourierMatch")

# ---------- util fuzz ----------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", s)
    s = re.sub(r"(?i)\b(ao vivo|live|oficial|official|audio|áudio|clipe|karaok[eê]|cover|lyric|vídeo|video|remix|vers[aã]o)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _ratio(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _artist_tokens(s: str) -> List[str]:
    s = _norm(s)
    s = re.sub(r"(?i)\b(feat\.?|com)\b", ",", s)
    return [t.strip() for t in re.split(r"[,&/x+]+", s) if t.strip()]

def _artist_match_ok(cand: str, hint: Optional[str]) -> bool:
    if not cand:
        return False
    if not hint:
        return True
    if _ratio(cand, hint) >= 0.65:
        return True
    cand_t = _artist_tokens(cand)
    hint_t = _artist_tokens(hint or "")
    for a in cand_t:
        for b in hint_t:
            if _ratio(a, b) >= 0.90:
                return True
    return False

def _parse_title_tokens(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not text:
        return None, None, None
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    parts = [p.strip() for p in t.split(" - ") if p.strip()]
    if len(parts) >= 3:
        artist = parts[0]
        album = parts[-1]
        track = " - ".join(parts[1:-1])
        return artist, track, album
    if len(parts) == 2:
        return parts[0], parts[1], None
    return None, parts[0] if parts else None, None

# ---------- pipeline ----------
def enrich_metadata(arquivo: Path, duration_sec: float, hints: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retorna dict com:
      { title, artist, album, genres, cover, accepted }
    Em modo estrito (STRICT_METADATA=True), exige artista+titulo confiáveis.
    """
    artist_hint = hints.get("artist")
    track_hint  = hints.get("title")
    album_hint  = hints.get("album")
    yt_thumb    = hints.get("thumb")

    titulo = arquivo.stem
    artista = "desconhecido"
    album = genero = capa = None

    # 1) Spotify (alta precisão)
    used_spotify = False
    try:
        if artist_hint or track_hint:
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

    # 2) Discogs → Deezer (se Spotify não bateu)
    if not used_spotify:
        q_fb = " ".join([p for p in [artist_hint, track_hint, album_hint] if p]) or arquivo.stem

        md = search_discogs(artist_hint, track_hint, album_hint, q_fb, token=DISCOGS_TOKEN)
        if md and (_artist_match_ok(md.get("artist",""), artist_hint)) and (_ratio(md.get("title",""), track_hint or "") >= 0.60):
            titulo = md.get("title") or titulo
            artista = md.get("artist") or artista
            album = md.get("album") or album_hint or album
            capa = md.get("cover") or yt_thumb or capa
            if md.get("genres"):
                genero = ", ".join(md["genres"]) if isinstance(md["genres"], list) else str(md["genres"])
        else:
            md2 = search_deezer(artist_hint, track_hint, album_hint, q_fb)
            if md2 and (_artist_match_ok(md2.get("artist",""), artist_hint)) and (_ratio(md2.get("title",""), track_hint or "") >= 0.60):
                titulo = md2.get("title") or titulo
                artista = md2.get("artist") or artista
                album = md2.get("album") or album_hint or album
                capa = md2.get("cover") or yt_thumb or capa
                if md2.get("genres"):
                    genero = ", ".join(md2["genres"]) if isinstance(md2["genres"], list) else str(md2["genres"])
            else:
                # 3) Shazam (reconhecimento por áudio)
                log.info("🎧 Tentando reconhecer pelo Shazam…")
                rec = recognize_with_cache(arquivo)
                if rec and (rec.title or rec.artist):
                    if rec.title:  titulo = rec.title
                    if rec.artist: artista = rec.artist
                    # opcional: tentar completar álbum/capa via Discogs com o retorno do Shazam
                    if DISCOGS_TOKEN and rec.title and rec.artist:
                        try:
                            md3 = search_discogs(rec.artist, rec.title, None, f"{rec.artist} {rec.title}", token=DISCOGS_TOKEN)
                            if md3:
                                if md3.get("album"): album = md3["album"]
                                if md3.get("cover"): capa = md3["cover"]
                                if md3.get("genres"):
                                    genero = ", ".join(md3["genres"]) if isinstance(md3["genres"], list) else str(md3["genres"])
                        except Exception:
                            pass

    # 4) Regras de aceitação
    accepted = True
    if STRICT_METADATA:
        a_ok = artista and artista != "desconhecido"
        t_ok = titulo and (titulo != arquivo.stem)
        if not (a_ok and t_ok):
            if not INSERT_ON_LOW_CONFIDENCE:
                accepted = False
            else:
                # grava com hints (modo permissivo)
                artista = artist_hint or artista
                titulo  = track_hint  or titulo
                album   = album_hint  or album
                capa    = yt_thumb    or capa
                accepted = True

    return {
        "title":   titulo,
        "artist":  artista,
        "album":   album,
        "genres":  genero,
        "cover":   capa,
        "accepted": accepted
    }
