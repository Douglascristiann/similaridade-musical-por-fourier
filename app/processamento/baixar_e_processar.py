from yt_dlp import YoutubeDL
import os

def baixar_musicas(lista_de_links, destino='./audio'):
    os.makedirs(destino, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{destino}/%(title)s.%(ext)s',
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
    lista_links = "/home/jovyan/work/cache/links_youtube"

    baixar_musicas(lista_links, pasta_download)