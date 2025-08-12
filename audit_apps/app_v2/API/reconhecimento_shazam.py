# API/reconhecimento_shazam.py

import librosa
import soundfile as sf
import asyncio
from shazamio import Shazam

def preparar_trecho_para_shazam(y, sr):
    y_norm = librosa.util.normalize(y)
    y_trim, _ = librosa.effects.trim(y_norm, top_db=20)
    if sr != 44100:
        y_trim = librosa.resample(y_trim, orig_sr=sr, target_sr=44100)
        sr = 44100
    return y_trim, sr

async def tentar_reconhecer(shazam, arquivo, tentativas=3):
    for i in range(tentativas):
        try:
            return await shazam.recognize(arquivo)
        except Exception as e:
            print(f"❌ Erro Shazam({i+1}): {e}")
            await asyncio.sleep(1)
    return None

async def reconhecer_shazam_trechos(path):
    y, sr = librosa.load(path, sr=None)
    dur = librosa.get_duration(path=path)
    shazam = Shazam()

    dur_t, passo = 15, 10
    n = max(1, int((dur - dur_t) / passo) + 1)
    print(f"🔎 {n} trechos Shazam…")

    for i in range(n):
        start, end = i * passo, min(i * passo + dur_t, dur)
        trecho = y[int(start * sr):int(end * sr)]
        tp, sr2 = preparar_trecho_para_shazam(trecho, sr)
        tmp = f"/tmp/sz_{i}.wav"
        sf.write(tmp, tp, sr2, subtype="PCM_16")

        res = await tentar_reconhecer(shazam, tmp)
        if res and res.get("track"):
            t = res["track"]
            artista = t.get("subtitle", "Não Encontrado")
            titulo  = t.get("title", "Não Encontrado")

            # Extração segura de álbum
            album = "Não Encontrado"
            sections = t.get("sections", [])
            if isinstance(sections, list) and sections:
                metadata = sections[0].get("metadata", [])
                if isinstance(metadata, list) and metadata:
                    album = metadata[0].get("text", "Não Encontrado")

            genero = t.get("genres", {}).get("primary", "Não Encontrado")
            capa   = t.get("images", {}).get("coverart", "Não Encontrado")

            print(f"✅ Shazam: {artista} – {titulo}")
            return artista, titulo, album, genero, capa

    return None
