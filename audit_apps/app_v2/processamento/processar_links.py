# processamento/processar_links.py

import os
import logging
from yt_dlp import YoutubeDL
from config import AUDIO_FOLDER

logger = logging.getLogger('processar_links')


def processar_link(link, arquivo_txt, pasta_audio=AUDIO_FOLDER):
    """
    Baixa um único vídeo do YouTube como MP3.
    """
    logger.info(f"[YTD] Baixando link: {link}")
    if not link.strip():
        return None, "❌ Link vazio."

    os.makedirs(pasta_audio, exist_ok=True)
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(pasta_audio, '%(title)s.%(ext)s'),
        'quiet': True,
        'cookiefile': os.path.abspath('/home/jovyan/work/app/cache/cookies/cookies.txt'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }]
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
        with open(arquivo_txt, 'a') as f:
            f.write(link + '\n')
        msg = f"✅ Áudio salvo em: {filename}"
        logger.info(msg)
        return filename, msg
    except Exception as e:
        msg = f"❌ Erro ao baixar: {e}"
        logger.error(msg)
        return None, msg


def processar_playlist(link, arquivo_txt, pasta_audio=AUDIO_FOLDER):
    """
    Baixa todos os vídeos de uma playlist ou álbum do YouTube como MP3.
    Retorna lista de caminhos salvos.
    """
    logger.info(f"[YTD] Baixando playlist: {link}")
    os.makedirs(pasta_audio, exist_ok=True)
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(pasta_audio, '%(playlist_index)s - %(title)s.%(ext)s'),
        'quiet': True,
        'yesplaylist': True,
        'cookiefile': os.path.abspath('/home/jovyan/work/app/cache/cookies/cookies.txt'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }]
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=True)
        downloaded = []
        for entry in info.get('entries', []):
            fn = ydl.prepare_filename(entry).rsplit('.', 1)[0] + '.mp3'
            downloaded.append(fn)
            with open(arquivo_txt, 'a') as f:
                f.write(entry.get('webpage_url', '') + '\n')
        msg = f"✅ Playlist baixada: {len(downloaded)} faixas."
        logger.info(msg)
        return downloaded, msg
    except Exception as e:
        msg = f"❌ Erro ao baixar playlist: {e}"
        logger.error(msg)
        return [], msg
