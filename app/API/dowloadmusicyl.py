import os
from yt_dlp import YoutubeDL

def reconhecer_titulo(links):
    """
    Recebe uma lista de links e retorna uma lista de dicionários com títulos e artistas das músicas encontradas no YouTube.
    """
    resultados = []
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'extract_flat': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        for link in links:
            try:
                info = ydl.extract_info(link, download=False)
                titulo = info.get('title', 'Título não encontrado')
                artista = info.get('artist') or info.get('uploader') or 'Artista não encontrado'
                resultados.append({'titulo': titulo, 'artista': artista})
            except Exception as e:
                print(f"❌ Erro ao reconhecer título de {link}: {e}")
                resultados.append({'titulo': 'Erro ao obter título', 'artista': 'Erro ao obter artista'})
    return resultados


def inserir_links(entrada_links, caminho_arquivo_links):
    try:
        with open(caminho_arquivo_links, "w") as f:
            f.write(entrada_links)
    except Exception as e:
        print(f"❌ Erro ao inserir links {e}")

def ler_links_de_arquivo(caminho_arquivo):
    links = []
    try:
        with open(caminho_arquivo, "r") as f:
            for linha in f:
                url = linha.strip()
                if url and url.startswith("http"):
                    links.append(url)
    except Exception as e:
        print(f"❌ Erro ao ler o arquivo de links: {e}")
    if not links:
        print("⚠️ Nenhum link válido encontrado.")
    return links

def baixar_musicas(lista_de_links, pasta_download):
    os.makedirs(pasta_download, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{pasta_download}/%(title)s.%(ext)s',
        'quiet': False,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    total_baixadas = 0
    with YoutubeDL(ydl_opts) as ydl:
        for link in lista_de_links:
            try:
                print(f"⬇️ Baixando: {link}")
                ydl.download([link])
                total_baixadas += 1
            except Exception as e:
                print(f"❌ Erro ao baixar {link}: {e}")
    return total_baixadas

def limpar_arquivo(caminho_arquivo_links):
    try:
        with open(caminho_arquivo_links, "w") as f:
            f.write("")
    except Exception as e:
        print(f"❌ Erro ao limpar o arquivo links: {e}")

def limpar_audio(pasta_download):
    try:
        for filename in os.listdir(pasta_download):
            if filename.endswith(".mp3"):
                file_path = os.path.join(pasta_download, filename)
                os.remove(file_path)
    except Exception as e:
        print(f"❌ Erro ao limpar arquivos de áudio: {e}")

