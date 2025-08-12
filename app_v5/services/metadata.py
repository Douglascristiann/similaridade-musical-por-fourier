# -*- coding: utf-8 -*-
"""
Orquestra metadados com preenchimento por CAMADAS e por CAMPO:
Spotify → Discogs → Deezer → Shazam (+ Discogs/Deezer pós-Shazam)
Se algum campo ainda ficar vazio, aplica defaults:
  album/genero = "Desconhecido", capa_album = "Não Encontrado"
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
from pathlib import Path
import json, logging, re, unicodedata
from difflib import SequenceMatcher

from app_v4_new.config import DISCOGS_TOKEN, STRICT_METADATA, INSERT_ON_LOW_CONFIDENCE

# integrações (na mesma pasta de spotify.py)
from app_v4_new.integrations.spotify import enrich_from_spotify
from app_v4_new.integrations.discogs import search_discogs
from app_v4_new.integrations.deezer  import search_deezer
from app_v4_new.integrations.shazam_api import recognize_with_cache

log = logging.getLogger("FourierMatch")

# =============== utils de normalização/fuzzy ===============
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
        return parts[0], " - ".join(parts[1:-1]), parts[-1]
    if len(parts) == 2:
        return parts[0], parts[1], None
    return None, parts[0] if parts else None, None

# =============== helpers de merge ===============
def _is_empty(v: Optional[str]) -> bool:
    if v is None:
        return True
    v2 = str(v).strip().lower()
    return (v2 == "" or v2 in {"desconhecido", "nao encontrado", "não encontrado"})

def _merge_field(dst: Dict[str, Any], src: Dict[str, Any], f_src: str, f_dst: str) -> None:
    """Se o campo f_dst de dst estiver vazio, preenche com src[f_src] (se existir/e for não-vazio)."""
    if _is_empty(dst.get(f_dst)) and not _is_empty(src.get(f_src)):
        dst[f_dst] = src.get(f_src)

def _merge_meta(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    """Mescla título, artista, álbum, capa, gêneros (em string, coma-separada)."""
    if not src:
        return
    for pair in [("title","title"), ("artist","artist"), ("album","album"), ("cover","cover")]:
        _merge_field(dst, src, pair[0], pair[1])
    # gêneros podem vir como list -> string
    g = src.get("genres")
    if _is_empty(dst.get("genres")) and g:
        if isinstance(g, list):
            dst["genres"] = ", ".join(g)
        else:
            dst["genres"] = str(g)

# =============== pipeline principal ===============
def enrich_metadata(arquivo: Path, duration_sec: float, hints: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retorna dict com:
      { title, artist, album, genres, cover, accepted }
    Estratégia:
      1) Spotify
      2) Discogs
      3) Deezer
      4) Shazam (se ainda faltar título/artista) + nova rodada Discogs/Deezer
      5) Defaults (album/genero/capa se vazios)
    Em modo estrito (STRICT_METADATA=True), exige artista+titulo confiáveis.
    """
    artist_hint = hints.get("artist")
    track_hint  = hints.get("title")
    album_hint  = hints.get("album")
    yt_thumb    = hints.get("thumb")

    # estado acumulado
    meta: Dict[str, Any] = {
        "title": arquivo.stem,          # valor base
        "artist": "desconhecido",
        "album": None,
        "cover": yt_thumb or None,      # se tiver thumb do YT, já entra como candidato
        "genres": None,
    }

    # ---------- 1) Spotify ----------
    try:
        if artist_hint or track_hint:
            log.info("🟢 Spotify…")
            sp = enrich_from_spotify(artist_hint, track_hint, album_hint, duration_sec)
            if sp:
                _merge_meta(meta, sp)
                if not _is_empty(sp.get("cover")) and _is_empty(meta.get("cover")):
                    meta["cover"] = sp.get("cover")
    except Exception as e:
        log.info(f"Spotify indisponível: {e}")

    # ---------- 2) Discogs ----------
    try:
        q_fb = " ".join([p for p in [artist_hint, track_hint, album_hint] if p]) or arquivo.stem
        log.info("🔵 Discogs…")
        dg = search_discogs(artist_hint, track_hint, album_hint, q_fb, token=DISCOGS_TOKEN)
        if dg:
            # valida suavemente com hints (quando existirem)
            if (_artist_match_ok(dg.get("artist",""), artist_hint) or _is_empty(meta["artist"])) and \
               (_ratio(dg.get("title",""), track_hint or "") >= 0.55 or _is_empty(track_hint)):
                _merge_meta(meta, dg)
    except Exception as e:
        log.info(f"Discogs indisponível: {e}")

    # ---------- 3) Deezer ----------
    try:
        log.info("🟣 Deezer…")
        dz = search_deezer(artist_hint, track_hint, album_hint, q_fb)
        if dz:
            if (_artist_match_ok(dz.get("artist",""), artist_hint) or _is_empty(meta["artist"])) and \
               (_ratio(dz.get("title",""), track_hint or "") >= 0.55 or _is_empty(track_hint)):
                _merge_meta(meta, dz)
    except Exception as e:
        log.info(f"Deezer indisponível: {e}")

    # ---------- 4) Shazam (se ainda estiver fraco em título/artista) ----------
    need_core = _is_empty(meta.get("title")) or (meta.get("title") == arquivo.stem) or _is_empty(meta.get("artist")) or (meta.get("artist") == "desconhecido")
    if need_core:
        try:
            log.info("🎧 Shazam…")
            rec = recognize_with_cache(arquivo)
            if rec:
                # atualiza base com título/artista detectados
                if not _is_empty(rec.title):  meta["title"]  = rec.title
                if not _is_empty(rec.artist): meta["artist"] = rec.artist

                # com o que o Shazam deu, tenta completar álbum/capa/gênero
                a2, t2 = meta.get("artist"), meta.get("title")
                try:
                    dg2 = search_discogs(a2, t2, None, f"{a2} {t2}", token=DISCOGS_TOKEN)
                    if dg2:
                        _merge_meta(meta, dg2)
                except Exception:
                    pass
                try:
                    dz2 = search_deezer(a2, t2, None, f"{a2} {t2}")
                    if dz2:
                        _merge_meta(meta, dz2)
                except Exception:
                    pass
        except Exception as e:
            log.info(f"Shazam indisponível: {e}")

    # ---------- 5) Defaults para campos faltantes ----------
    if _is_empty(meta.get("album")):
        meta["album"] = "Desconhecido"
    if _is_empty(meta.get("genres")):
        meta["genres"] = "Desconhecido"
    if _is_empty(meta.get("cover")):
        meta["cover"] = "Não Encontrado"

    # ---------- Aceitação estrita (apenas título/artista) ----------
    accepted = True
    if STRICT_METADATA:
        a_ok = not _is_empty(meta.get("artist")) and meta.get("artist") != "desconhecido"
        t_ok = not _is_empty(meta.get("title")) and meta.get("title") != arquivo.stem
        if not (a_ok and t_ok):
            if not INSERT_ON_LOW_CONFIDENCE:
                accepted = False
            else:
                # usa hints como fallback leve
                if _is_empty(meta.get("artist")) and not _is_empty(artist_hint): meta["artist"] = artist_hint
                if (meta.get("title") == arquivo.stem) and not _is_empty(track_hint): meta["title"] = track_hint
                if _is_empty(meta.get("album")) and not _is_empty(album_hint): meta["album"] = album_hint
                if _is_empty(meta.get("cover")) and not _is_empty(yt_thumb): meta["cover"] = yt_thumb
                accepted = True

    # normaliza saída
    return {
        "title":   meta.get("title"),
        "artist":  meta.get("artist"),
        "album":   meta.get("album"),
        "genres":  meta.get("genres"),
        "cover":   meta.get("cover"),
        "accepted": accepted
    }
