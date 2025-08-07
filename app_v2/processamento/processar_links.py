# processamento/processar_links.py

import os
from yt_dlp import YoutubeDL

def processar_link(link, arquivo_txt, pasta_audio):
    print(f"[YTD] Baixando de: {link}")
    if not link.strip():
        return None, "❌ Link vazio."
    os.makedirs(pasta_audio, exist_ok=True)
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{pasta_audio}/%(title)s.%(ext)s',
        'quiet': True,
        'cookiefile': os.path.abspath("/home/jovyan/work/app/cache/cookies/cookies.txt"),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp3"
        with open(arquivo_txt, 'a') as f:
            f.write(link + "\n")
        print(f"[YTD] Baixado e salvo em {filename}")
        return filename, f"✅ {filename}"
    except Exception as e:
        print(f"[YTD] ❌ Erro ao baixar: {e}")
        return None, f"❌ {e}"
