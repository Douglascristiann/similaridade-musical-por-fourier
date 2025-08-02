# API/processar_links.py

import os
from yt_dlp import YoutubeDL
# IMPORTANTE: Remova a importação direta de extrator_fft aqui.
# A função será chamada a partir do main.py
# (Ou faça uma importação segura se você for usá-la aqui)

def buscar_youtube_link(artista, titulo):
    """Busca um link do YouTube para uma música."""
    # ... (código existente)
    # Esta função está bem aqui.

def processar_link(link, caminho_arquivo_links, pasta_audio):
    """
    Baixa o áudio de um link do YouTube, salva no diretório local e retorna o caminho.
    O processamento do áudio é feito pelo módulo de extrator.
    """
    if not link:
        return None, "❌ Link do YouTube não pode ser vazio."

    try:
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
        }
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info_dict)
            filename = os.path.splitext(filename)[0] + '.mp3' # Garante a extensão correta

            # Salva o link para futura referência
            with open(caminho_arquivo_links, 'a') as f:
                f.write(f"{link}\n")

            return filename, f"✅ O link do YouTube foi processado e o arquivo salvo em {filename}."

    except Exception as e:
        return None, f"❌ Erro ao processar o link do YouTube: {e}"