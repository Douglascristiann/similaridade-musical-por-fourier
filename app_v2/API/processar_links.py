# API/processar_links.py

import os
from yt_dlp import YoutubeDL

def buscar_youtube_link(artista, titulo):
    # ... (o código desta função permanece o mesmo) ...

def processar_link(link, caminho_arquivo_links, pasta_audio):
    if not link:
        return None, "❌ Link do YouTube não pode ser vazio."

    try:
        # Adicione a opção 'cookiefile' para autenticação com cookies
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(pasta_audio, '%(title)s.%(ext)s'),
            'cachedir': False,
            'verbose': True,
            # ADICIONE ESTA LINHA:
            'cookiefile': os.path.join(os.path.dirname(__file__), 'cookies.txt'),
        }
        with YoutubeDL(ydl_opts) as ydl:
            # ... (o restante do código permanece o mesmo) ...
            info_dict = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info_dict)
            filename = os.path.splitext(filename)[0] + '.mp3'

            with open(caminho_arquivo_links, 'a') as f:
                f.write(f"{link}\n")

            return filename, f"✅ O link do YouTube foi processado e o arquivo salvo em {filename}."

    except Exception as e:
        return None, f"❌ Erro ao processar o link do YouTube: {e}"