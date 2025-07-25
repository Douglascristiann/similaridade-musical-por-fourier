import os
from yt_dlp import YoutubeDL

def ler_links_de_arquivo(caminho_arquivo):
    """
    Lê um arquivo .txt contendo links (um por linha) e retorna uma lista com URLs válidas.
    """
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
    """
    Baixa os links fornecidos como arquivos .mp3 na pasta especificada.
    """
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

    with YoutubeDL(ydl_opts) as ydl:
        for link in lista_de_links:
            try:
                print(f"⬇️ Baixando: {link}")
                ydl.download([link])
            except Exception as e:
                print(f"❌ Erro ao baixar {link}: {e}")

if __name__ == "__main__":
    pasta_download = "/home/jovyan/work/audio"
    caminho_arquivo_links = "/home/jovyan/work/cache/links_youtube/links.txt"

    lista_links = ler_links_de_arquivo(caminho_arquivo_links)
    if lista_links:
        baixar_musicas(lista_links, pasta_download)
