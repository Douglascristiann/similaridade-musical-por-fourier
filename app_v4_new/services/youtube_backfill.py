# -*- coding: utf-8 -*-
"""
Backfill simples do link do YouTube para ARQUIVOS LOCAIS, SEM cookies.
Usa yt_dlp com ytsearch1: "<artista> <titulo>" (com variações).
Retorna link canônico https://www.youtube.com/watch?v=<id> ou None.
"""
from __future__ import annotations
from typing import Optional, List
import re, unicodedata

try:
    # yt-dlp é obrigatório para este backfill
    from yt_dlp import YoutubeDL  # type: ignore
except Exception:
    YoutubeDL = None  # tratamos no runtime

def _clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", s)  # remove bracketed noise
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _build_queries(artist: Optional[str], title: Optional[str]) -> List[str]:
    a = _clean_text(artist)
    t = _clean_text(title)
    qs: List[str] = []
    if a and t:
        qs.append(f'{a} {t} "audio"')  # prioriza áudio oficial
        qs.append(f"{a} {t}")
    if t:
        qs.append(t)
    if a:
        qs.append(a)
    return qs

def _mk_link(video_id: Optional[str]) -> Optional[str]:
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"

def buscar_youtube_link(artist: Optional[str], title: Optional[str]) -> Optional[str]:
    """
    Busca 1º resultado do YouTube para a query construída.
    Retorna link canônico (watch?v=) ou None.
    """
    # evita lixo tipo "Não Encontrado"
    for s in (artist, title):
        if isinstance(s, str) and s.strip().lower() in {"não encontrado", "nao encontrado", "desconhecido"}:
            return None

    if YoutubeDL is None:
        # yt-dlp não instalado
        return None

    queries = _build_queries(artist, title)
    if not queries:
        return None

    # Opções sem cookies e sem download
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,      # rápido: não resolve player
        "noplaylist": True,
        "default_search": "ytsearch",
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }

    # tenta em ordem, parando no 1º bom
    for q in queries:
        try:
            with YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f"ytsearch1:{q}", download=False)
            entries = (result or {}).get("entries") or []
            if entries:
                video_id = entries[0].get("id")
                link = _mk_link(video_id)
                if link:
                    return link
        except Exception:
            # ignora e tenta próxima variação
            continue
    return None
