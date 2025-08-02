import discogs_client

# Seu token de acesso
TOKEN = 'QZgdlkbRWFIbKlCVztBdCIvSYNqPKsyoLaasyyTD'

# Inicializa o cliente Discogs
d = discogs_client.Client('MeuApp/1.0', user_token=TOKEN)

def buscar_genero_discogs(musica, artista):
    try:
        query = f"{musica} {artista}"
        resultados = d.search(query, artist=artista, type='release')

        if not resultados:
            return {"erro": "Nenhum resultado encontrado no Discogs."}

        release = resultados[0]

        dados = {
            "titulo": release.title,
            "artista": release.artists[0].name if release.artists else "Desconhecido",
            "ano": release.year if release.year else "Desconhecido",
            "generos": release.genres if release.genres else ["Desconhecido"],
            "estilos": release.styles if release.styles else ["Desconhecido"],
            "capa": release.thumb if release.thumb else "Sem imagem"
        }

        return dados

    except Exception as e:
        return {"erro": str(e)}

def processar_lista_titulos(lista):
    resultados = []
    for item in lista:
        titulo_completo = item.get('titulo', '')
        artista = item.get('artista', '')
        musica = titulo_completo.replace(f"{artista} - ", "")
        resultado = buscar_genero_discogs(musica.strip(), artista.strip())
        resultados.append(resultado)
    return resultados
