# API/processar_links.py

import os
from yt_dlp import YoutubeDL
from extrator_fft import processar_audio_local # Importa a função de outro módulo

def buscar_youtube_link(artista, titulo):
    """Busca um link do YouTube para uma música."""
    if artista == "Não Encontrado" or titulo == "Não Encontrado":
        return "Não Encontrado"

    query = f"{artista} {titulo}"
    ydl_opts = {
        'quiet': True, # Suprime a saída do yt-dlp
        'skip_download': True, # Não baixa o vídeo
        'extract_flat': True, # Extrai apenas informações básicas rapidamente
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if 'entries' in result and result['entries']:
                video_id = result['entries'][0].get('id')
                if video_id:
                    return f"https://www.youtube.com/watch?v={video_id}"
    except Exception as e:
        print("❌ Erro yt_dlp:", e)
    return "Não Encontrado"


def processar_link(link, caminho_arquivo_links, pasta_audio):
    """
    Baixa o áudio de um link do YouTube, salva no diretório local
    e o processa.
    """
    if not link:
        return "❌ Link do YouTube não pode ser vazio."

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

            # Chama a função de processamento local
            processar_audio_local(filename)
            
            # Salva o link para futura referência
            with open(caminho_arquivo_links, 'a') as f:
                f.write(f"{link}\n")

            return f"✅ O link do YouTube foi processado e o arquivo salvo em {filename}."

    except Exception as e:
        return f"❌ Erro ao processar o link do YouTube: {e}"