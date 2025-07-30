import discogs_client

# Seu token de acesso
TOKEN = 'QZgdlkbRWFIbKlCVztBdCIvSYNqPKsyoLaasyyTD'

# Inicializa o cliente Discogs
d = discogs_client.Client('MeuApp/1.0', user_token=TOKEN)

def buscar_genero_discogs(musica, artista):
    try:
        # Combina nome da música e artista para busca
        query = f"{musica} {artista}"

        # Busca lançamentos com base na música e artista
        resultados = d.search(query, artist=artista, type='release')

        if not resultados:
            return {"erro": "Nenhum resultado encontrado no Discogs."}

        release = resultados[0]  # Pega o primeiro resultado mais relevante

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



if __name__ == "__main__":
    musica = input("Digite o nome da música: ")
    artista = input("Digite o nome do artista: ")
    info = buscar_genero_discogs(musica, artista)
    print(info)

