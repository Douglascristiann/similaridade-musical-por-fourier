import discogs_client

# Seu token de acesso
TOKEN = 'QZgdlkbRWFIbKlCVztBdCIvSYNqPKsyoLaasyyTD'

# Inicializa o cliente Discogs
d = discogs_client.Client('MeuApp/1.0', user_token=TOKEN)

def enriquecer_metadados_discogs(lista_metadados):
    """
    Recebe lista de metadados com 'titulo', 'artista' e 'arquivo', retorna lista enriquecida com:
    - genero
    - estilo
    - capa_album
    """
    resultados = []
    for item in lista_metadados:
        titulo_completo = item.get('titulo', '')
        artista = item.get('artista', '')
        musica = titulo_completo.replace(f"{artista} - ", "").strip()

        try:
            query = f"{musica} {artista}"
            resultados_discogs = d.search(query, artist=artista, type='release')

            if resultados_discogs:
                release = resultados_discogs[0]
                item.update({
                    "genero": release.genres[0] if release.genres else "Desconhecido",
                    "estilo": release.styles[0] if release.styles else "Desconhecido",
                    "capa_album": release.thumb if release.thumb else ""
                })
            else:
                item.update({
                    "genero": "Desconhecido",
                    "estilo": "Desconhecido",
                    "capa_album": ""
                })

        except Exception:
            item.update({
                "genero": "Desconhecido",
                "estilo": "Desconhecido",
                "capa_album": ""
            })

        resultados.append(item)

    return resultados