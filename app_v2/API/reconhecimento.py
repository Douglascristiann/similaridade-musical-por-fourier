# API/reconhecimento.py

import asyncio
import requests
import soundfile as sf
import librosa
from tinytag import TinyTag
from shazamio import Shazam
from config import AUDD_TOKEN

# =================== PRÉ-PROCESSAMENTO SHAZAM ===================
def preparar_trecho_para_shazam(y, sr):
    """Prepara um trecho de áudio para reconhecimento pelo Shazam."""
    y_norm = librosa.util.normalize(y)
    y_trim, _ = librosa.effects.trim(y_norm, top_db=20)
    if sr != 44100:
        y_trim = librosa.resample(y_trim, orig_sr=sr, target_sr=44100)
        sr = 44100
    return y_trim, sr

async def tentar_reconhecer(shazam, arquivo, tentativas=3):
    """Tenta reconhecer um arquivo de áudio usando a API do Shazam, com retentativas."""
    for tentativa in range(tentativas):
        try:
            result = await shazam.recognize(arquivo)
            return result
        except Exception as e:
            print(f"❌ Erro ShazamIO na tentativa {tentativa+1}: {e}")
            await asyncio.sleep(1) # Pequena pausa antes de retentar
    return None

async def reconhecer_shazam_trechos(path):
    """Tenta reconhecer uma música usando o Shazam, analisando múltiplos trechos."""
    y, sr = librosa.load(path, sr=None)
    duracao_total = librosa.get_duration(path=path)
    shazam = Shazam()

    trecho_duracao = 15 # Duração de cada trecho a ser analisado
    passo = 10 # Pula 10 segundos para o próximo trecho
    num_trechos = max(1, int((duracao_total - trecho_duracao) / passo) + 1)
    print(f"🔎 Analisando {num_trechos} trechos para Shazam...")

    for i in range(num_trechos):
        start = i * passo
        end = min(start + trecho_duracao, duracao_total)
        if start >= end:
            break

        trecho = y[int(start * sr):int(end * sr)]
        trecho_preparado, sr_preparado = preparar_trecho_para_shazam(trecho, sr)

        tmp = f"/tmp/shazam_trecho_{i}.wav"
        sf.write(tmp, trecho_preparado, sr_preparado, subtype='PCM_16')

        result = await tentar_reconhecer(shazam, tmp)
        if result and result.get("track"):
            track = result["track"]
            artista = track.get("subtitle", "Não Encontrado")
            titulo = track.get("title", "Não Encontrado")

            album = "Não Encontrado"
            sections = track.get("sections", [])
            if sections and isinstance(sections, list):
                metadata = sections[0].get("metadata", [])
                if metadata and isinstance(metadata, list):
                    album = metadata[0].get("text", "Não Encontrado")

            genero = track.get("genres", {}).get("primary", "Não Encontrado")
            capa_url = track.get("images", {}).get("coverart", "Não Encontrado")
            print(f"✅ Shazam reconheceu: {artista} - {titulo}")
            return artista, titulo, album, genero, capa_url

    return None

# =================== OUTRAS APIS ===================
def reconhecer_audd(path):
    """Tenta reconhecer uma música usando a API do AudD."""
    try:
        with open(path, 'rb') as f:
            files = {'file': f}
            data = {'api_token': AUDD_TOKEN, 'return': 'apple_music,spotify'}
            r = requests.post('https://api.audd.io/', data=data, files=files, timeout=10).json()
            result = r.get("result")
            if result:
                return (
                    result.get("artist", "Não Encontrado"),
                    result.get("title", "Não Encontrado"),
                    result.get("album", "Não Encontrado"),
                    result.get("genre", "Não Encontrado"),
                    "Não Encontrado" # AudD não retorna capa_album diretamente
                )
    except Exception as e:
        print("\u274c Erro AudD:", e)
    return ("Não Encontrado",) * 5

def reconhecer_metadado(path):
    """Tenta reconhecer uma música lendo seus metadados (tags ID3)."""
    try:
        tag = TinyTag.get(path)
        return (
            tag.artist or "Não Encontrado",
            tag.title or "Não Encontrado",
            tag.album or "Não Encontrado",
            tag.genre or "Não Encontrado",
            "Não Encontrado" # TinyTag não retorna capa_album URL
        )
    except:
        return ("Não Encontrado",) * 5

async def reconhecer_musica(path):
    """Reconhece a música usando múltiplas APIs de forma sequencial."""
    metadado = reconhecer_metadado(path)
    if metadado and metadado[0] != "Não Encontrado":
        print("✅ Metadados ID3 encontrados!")
        return metadado

    audd = reconhecer_audd(path)
    if audd and audd[0] != "Não Encontrado":
        print("✅ AudD reconheceu a música!")
        return audd
        
    shazam = await reconhecer_shazam_trechos(path)
    if shazam and shazam[0] != "Não Encontrado":
        return shazam

    print("❌ Nenhuma API conseguiu reconhecer a música.")
    return ("Não Encontrado",) * 5