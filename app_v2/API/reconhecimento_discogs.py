# API/reconhecimento_discogs.py

import discogs_client
import requests
from config import DISCOGS_TOKEN

# inicializa o cliente
_d = discogs_client.Client('MusicDataPro/1.0', user_token=DISCOGS_TOKEN)

def enriquecer_metadados_discogs_item(artista, titulo):
    """
    Dado artista+título, retorna dict com:
      - titulo_track  (pode vir do reconhecimento anterior ou ser corrigido aqui)
      - album_title   (release.title)
      - genero
      - estilo
      - capa_album
    Faz fallback para Deezer caso Discogs falhe.
    """
    item = {
        "titulo_track": titulo,
        "album_title":  "Desconhecido",
        "genero":       "Desconhecido",
        "estilo":       "Desconhecido",
        "capa_album":   ""
    }

    try:
        # busca o release no Discogs
        query = f"{titulo} {artista}"
        results = _d.search(query, artist=artista, type='release')
        if results:
            release = results[0]

            # 1) álbum
            item["album_title"] = release.title or item["album_title"]

            # 2) tracklist → procura faixa que case com 'titulo'
            for tr in release.tracklist:
                # cada tr tem atributo .title
                if tr.title.strip().lower() == titulo.strip().lower():
                    item["titulo_track"] = tr.title
                    break

            # 3) gênero/estilo
            item["genero"]     = release.genres[0] if release.genres else item["genero"]
            item["estilo"]     = release.styles[0] if release.styles else item["estilo"]
            item["capa_album"] = release.thumb or item["capa_album"]
            return item

    except Exception:
        pass  # próximo fallback

    # fallback Deezer
    try:
        deezer_url = (
            f"https://api.deezer.com/search"
            f"?q=artist:\"{artista}\" track:\"{titulo}\""
        )
        resp = requests.get(deezer_url, timeout=5).json().get('data', [])
        if resp:
            track = resp[0]
            item["titulo_track"] = track.get('title', item["titulo_track"])
            item["album_title"]  = track.get('album', {}).get('title', item["album_title"])
            item["capa_album"]   = track.get('album', {}).get('cover_medium', item["capa_album"])
            # Deezer não fornece gênero por faixa, manter como está
    except Exception:
        pass

    return item
