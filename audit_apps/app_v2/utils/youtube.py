# utils/youtube.py

from yt_dlp import YoutubeDL

def buscar_youtube_link(artista, titulo):
    if artista=="Não Encontrado" or titulo=="Não Encontrado":
        return "Não Encontrado"
    q = f"{artista} {titulo}"
    opts = {"quiet":True,"skip_download":True,"extract_flat":True}
    try:
        with YoutubeDL(opts) as ydl:
            r = ydl.extract_info(f"ytsearch1:{q}", download=False)
        vid = r.get("entries",[{}])[0].get("id")
        return f"https://youtu.be/{vid}" if vid else "Não Encontrado"
    except Exception as e:
        print("❌ yt-dlp:", e)
        return "Não Encontrado"
