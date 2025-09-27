# app_v5/integrations/youtube_api.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, Dict, List
import logging

# Reutiliza a busca de links do YouTube já existente no projeto
from app_v5.services.youtube_backfill import buscar_youtube_link

log = logging.getLogger("FourierMatch")

# Palavras-chave que geralmente indicam o gênero em tags do YouTube
GENRE_KEYWORDS = [
    'rock', 'pop', 'samba', 'pagode', 'sertanejo', 'mpb', 'forró', 'funk',
    'rap', 'hip hop', 'trap', 'eletrônica', 'house', 'techno', 'trance',
    'reggae', 'jazz', 'blues', 'metal', 'indie', 'alternative', 'axé',
    'bossa nova', 'gospel', 'soul', 'r&b', 'piseiro', 'arrocha'
]

def enrich_from_youtube(artist: Optional[str], title: Optional[str]) -> Optional[Dict[str, List[str]]]:
    """
    Busca metadados no YouTube, focando em extrair o gênero a partir
    das tags e da categoria do vídeo.
    """
    if not artist or not title:
        return None

    # 1. Encontra o link do vídeo mais relevante
    yt_link = buscar_youtube_link(artist, title)
    if not yt_link:
        log.warning(f"  - YouTube API: Nenhum vídeo encontrado para '{artist} - {title}'.")
        return None

    log.info(f"  - YouTube API: Encontrado vídeo de referência: {yt_link}")

    # 2. Usa yt-dlp para extrair os metadados do vídeo (sem baixar)
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        log.error("  - A biblioteca 'yt-dlp' é necessária para a busca de metadados no YouTube.")
        return None

    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'extract_flat': True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(yt_link, download=False)
            # Em modo 'extract_flat', a info está no primeiro item de 'entries'
            video_info = info.get('entries', [{}])[0] if 'entries' in info else info
    except Exception as e:
        log.error(f"  - YouTube API: Falha ao extrair metadados do vídeo: {e}")
        return None

    # 3. Extrai e filtra os gêneros a partir das tags e categorias
    genres = set()
    tags = video_info.get('tags', []) or []
    categories = video_info.get('categories', []) or []

    # Combina tags e categorias numa única lista de texto
    text_pool = [str(t).lower() for t in tags + categories]
    
    # Procura por palavras-chave de gênero na lista de texto
    for keyword in GENRE_KEYWORDS:
        for text in text_pool:
            if keyword in text:
                genres.add(keyword.capitalize()) # Capitaliza para um formato consistente

    if not genres:
        log.warning("  - YouTube API: Nenhum gênero relevante encontrado nas tags ou categoria do vídeo.")
        return None

    log.info(f"  - YouTube API: Gêneros encontrados: {list(genres)}")
    return {
        "genres": list(genres),
        "source": "youtube"
    }