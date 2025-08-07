# API/reconhecimento_unificado.py

import asyncio
import discogs_client
import requests
from tinytag import TinyTag

from API.reconhecimento_shazam import reconhecer_shazam_trechos
from API.reconhecimento_audd import reconhecer_audd

# Token de acesso ao Discogs
TOKEN = 'QZgdlkbRWFIbKlCVztBdCIvSYNqPKsyoLaasyyTD'
d = discogs_client.Client('MusicDataPro/1.0', user_token=TOKEN)

def reconhecer_metadado(path):
    """Lê tags ID3 locais via TinyTag."""
    try:
        tag = TinyTag.get(path)
        return (
            tag.artist or "Não Encontrado",
            tag.title  or "Não Encontrado",
            tag.album  or "Não Encontrado",
            tag.genre  or "Não Encontrado",
            None  # TinyTag não fornece capa
        )
    except:
        return ("Não Encontrado",) * 5

def discogs_lookup(artista, titulo):
    """
    Consulta o Discogs para enriquecer metadados.
    Retorna dict com album, genero e capa_album, ou None se não achar.
    """
    try:
        query = f"{titulo} {artista}"
        results = d.search(query, artist=artista, type='release')
        if results:
            release = results[0]
            # Título do álbum
            album = release.title
            # Gênero principal
            genero = release.genres[0] if release.genres else "Desconhecido"
            # Capa (thumbnail)
            capa   = release.thumb or ""
            return {"album": album, "genero": genero, "capa_album": capa}
    except Exception:
        pass
    return None

async def reconhecer_musica(path):
    """
    Pipeline:
      1) Tags locais → Discogs
      2) ShazamIO → Discogs
      3) AudD    → Discogs
      4) Tags locais finais
    Retorna: (artista, titulo, album, genero, capa_album)
    """

    # 1️⃣ Metadados locais
    artista, titulo, album_loc, genero_loc, _ = reconhecer_metadado(path)
    if artista != "Não Encontrado" and titulo != "Não Encontrado":
        disc = discogs_lookup(artista, titulo)
        if disc:
            return artista, titulo, disc["album"], disc["genero"], disc["capa_album"]
        # se Discogs não tiver, mantemos os tags locais
        album, genero, capa = album_loc, genero_loc, None
    else:
        album, genero, capa = None, None, None

    # 2️⃣ ShazamIO
    try:
        print("⚠️ Tags incompletas. Tentando ShazamIO...")
        shz = await reconhecer_shazam_trechos(path)
    except Exception:
        shz = None

    if shz:
        artista, titulo, album_shz, genero_shz, capa_shz = shz
        disc = discogs_lookup(artista, titulo)
        if disc:
            return artista, titulo, disc["album"], disc["genero"], disc["capa_album"]
        return artista, titulo, album_shz, genero_shz, capa_shz

    # 3️⃣ AudD
    print("⚠️ Shazam falhou. Tentando AudD...")
    audd = reconhecer_audd(path)
    if any(x != "Não Encontrado" for x in audd):
        artista, titulo, album_audd, genero_audd, capa_audd = audd
        disc = discogs_lookup(artista, titulo)
        if disc:
            return artista, titulo, disc["album"], disc["genero"], disc["capa_album"]
        return artista, titulo, album_audd, genero_audd, capa_audd

    # 4️⃣ Por fim, volta aos metadados locais
    print("⚠️ AudD falhou. Usando Tags locais finais.")
    return reconhecer_metadado(path)
