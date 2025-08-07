# API/reconhecimento_unificado.py

import asyncio
from API.reconhecimento_shazam import reconhecer_shazam_trechos
from API.reconhecimento_audd import reconhecer_audd
from API.reconhecimento_metadado import reconhecer_metadado
from API.reconhecimento_discogs import enriquecer_metadados_discogs_item

async def reconhecer_musica(path):
    """
    Pipeline de reconhecimento:
      1) Tags ID3 locais → Discogs (enriquecimento)
      2) ShazamIO
      3) AudD
      4) Tags locais finais
    Retorna: (artista, titulo, album, genero, capa_album)
    """

    # 1️⃣ Metadados locais via TinyTag
    artista, titulo, album, genero, capa = reconhecer_metadado(path)
    if artista != "Não Encontrado" and titulo != "Não Encontrado":
        # tenta enriquecer com Discogs
        disc = enriquecer_metadados_discogs_item(artista, titulo)
        genero     = disc.get("genero", genero)
        capa       = disc.get("capa_album", capa)
        # opcionalmente corrigir title/album se quiser:
        titulo = disc.get("titulo_track", titulo)
        album  = disc.get("album_title", album)
        return artista, titulo, album, genero, capa

    # 2️⃣ ShazamIO
    print("⚠️ Tags vazias. Tentando ShazamIO...")
    shz = await reconhecer_shazam_trechos(path)
    if shz:
        artista, titulo, album, genero_shz, capa_shz = shz
        # enriquece Shazam com Discogs
        disc = enriquecer_metadados_discogs_item(artista, titulo)
        genero = disc.get("genero", genero_shz)
        capa   = disc.get("capa_album", capa_shz)
        return artista, titulo, album, genero, capa

    # 3️⃣ AudD
    print("⚠️ Shazam falhou. Tentando AudD...")
    audd = reconhecer_audd(path)
    if any(r != "Não Encontrado" for r in audd):
        artista, titulo, album, genero_audd, capa_audd = audd
        # enriquece AudD com Discogs
        disc = enriquecer_metadados_discogs_item(artista, titulo)
        genero = disc.get("genero", genero_audd)
        capa   = disc.get("capa_album", capa_audd)
        return artista, titulo, album, genero, capa

    # 4️⃣ Por fim, volta aos metadados locais
    print("⚠️ AudD falhou. Usando novamente tags locais.")
    artista, titulo, album, genero, capa = reconhecer_metadado(path)
    return artista, titulo, album, genero, capa
