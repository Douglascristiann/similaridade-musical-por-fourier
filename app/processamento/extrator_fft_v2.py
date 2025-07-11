import os
import time
import base64
import hashlib
import hmac
import asyncio
import requests
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from tinytag import TinyTag
from sklearn.neighbors import NearestNeighbors
from shazamio import Shazam
import mysql.connector

# ============ CONFIGURAÇÕES ============
DB_CONFIG = {
    "user": "root",
    "password": "managerffti8p68",
    "host": "db",
    "port": 3306,
    "database": "dbmusicadata"
}

ACR_CFG = {
    'host': 'identify-us-west-2.acrcloud.com',
    'access_key': 'YkVlGYYdQrGM9qk0',
    'access_secret': 'rUU8B5mPIrTZGcFViDzgHXOuaCzVG7Qv'
}

AUDD_TOKEN = "194e979e8e5d531ffd6d54941f5b7977"

# ============ BANCO DE DADOS ============
def conectar():
    return mysql.connector.connect(**DB_CONFIG)

def criar_tabela():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tb_musicas (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(255) NOT NULL UNIQUE,
                    caminho TEXT,
                    caracteristicas TEXT NOT NULL,
                    artista VARCHAR(255),
                    titulo VARCHAR(255),
                    album VARCHAR(255),
                    genero VARCHAR(255),
                    capa_album TEXT,
                    links TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

def musica_existe(nome):
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM tb_musicas WHERE nome = %s", (nome,))
            return cur.fetchone() is not None

def inserir_musica(nome, caminho, caracteristicas, artista, titulo, album, genero, capa_album, links):
    if musica_existe(nome):
        print(f"⚠️ Música '{nome}' já cadastrada.")
        return
    carac_str = ",".join(map(str, caracteristicas))
    links_str = json.dumps(links, ensure_ascii=False) if links else "{}"
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tb_musicas (nome, caminho, caracteristicas, artista, titulo, album, genero, capa_album, links)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (nome, caminho, carac_str, artista, titulo, album, genero, capa_album, links_str))
            conn.commit()
            print(f"✅ Inserida no banco: {nome}")

def carregar_musicas():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nome, caracteristicas FROM tb_musicas")
            rows = cur.fetchall()
    return {nome: list(map(float, carac.split(","))) for nome, carac in rows}

# ============ RECONHECIMENTO MUSICAL ============
import json

async def reconhecer_shazam(path):
    try:
        shazam = Shazam()
        result = await shazam.recognize(path)
        if result.get("track"):
            track = result["track"]
            artista = track.get("subtitle", "Desconhecido")
            titulo = track.get("title", "Desconhecido")
            album = track.get("sections", [{}])[0].get("metadata", [{}])[0].get("text", "Desconhecido")
            genero = track.get("genres", {}).get("primary", "Desconhecido")

            images = track.get("images", {})
            capa_url = images.get("coverart") or images.get("background") or None

            links = {}
            hub = track.get("hub", {})
            if hub:
                actions = hub.get("actions", [])
                for action in actions:
                    uri = action.get("uri", "")
                    tipo = action.get("type", "").lower()
                    if "spotify" in uri:
                        links["spotify"] = uri
                    elif tipo in ["applemusic", "apple_music"]:
                        links["apple_music"] = uri
                    elif "youtube" in uri:
                        links["youtube"] = uri

            print(f"✅ Shazam reconheceu: '{titulo}' de {artista}")
            if capa_url:
                print(f"🎨 Capa do álbum: {capa_url}")
            if links:
                print(f"🔗 Links para ouvir:")
                for serv, url in links.items():
                    print(f"   - {serv}: {url}")

            return artista, titulo, album, genero, capa_url, links
    except Exception as e:
        print("❌ Erro ShazamIO:", e)
    return ("Desconhecido",) * 6

def identificar_acr(caminho):
    try:
        timestamp = int(time.time())
        string_to_sign = "\n".join(["POST", "/v1/identify", ACR_CFG['access_key'], "audio", "1", str(timestamp)])
        sign = base64.b64encode(hmac.new(ACR_CFG['access_secret'].encode(), string_to_sign.encode(), hashlib.sha1).digest()).decode()

        with open(caminho, 'rb') as f:
            sample = f.read()

        payload = {
            "access_key": ACR_CFG['access_key'],
            "timestamp": timestamp,
            "signature": sign,
            "data_type": "audio",
            "signature_version": "1",
            "sample_bytes": len(sample)
        }
        files = {"sample": sample}

        res = requests.post(f"https://{ACR_CFG['host']}/v1/identify", data=payload, files=files, timeout=10)
        music = res.json().get("metadata", {}).get("music", [])
        if music:
            m = music[0]
            return (
                m["artists"][0]["name"],
                m["title"],
                m.get("album", {}).get("name", "Desconhecido"),
                m.get("genres", [{}])[0].get("name", "Desconhecido"),
                None,   # capa_album não disponível
                {}      # links vazios
            )
    except Exception as e:
        print("❌ Erro ACRCloud:", e)
    return ("Desconhecido",) * 6

def identificar_audd(caminho):
    try:
        with open(caminho, 'rb') as f:
            files = {'file': f}
            data = {'api_token': AUDD_TOKEN, 'return': 'apple_music,spotify'}
            r = requests.post('https://api.audd.io/', data=data, files=files, timeout=10).json()
            result = r.get("result")
            if result:
                return (
                    result.get("artist", "Desconhecido"),
                    result.get("title", "Desconhecido"),
                    result.get("album", "Desconhecido"),
                    result.get("genre", "Desconhecido"),
                    None,
                    {}
                )
    except Exception as e:
        print("❌ Erro AudD:", e)
    return ("Desconhecido",) * 6

def identificar_metadado(caminho):
    try:
        tag = TinyTag.get(caminho)
        return (
            tag.artist or "Desconhecido",
            tag.title or "Desconhecido",
            tag.album or "Desconhecido",
            tag.genre or "Desconhecido",
            None,
            {}
        )
    except:
        return ("Desconhecido",) * 6

def reconhecer_musica(caminho):
    resultado = asyncio.run(reconhecer_shazam(caminho))
    if any(r != "Desconhecido" for r in resultado[:4]):
        return resultado

    for metodo in [identificar_acr, identificar_audd, identificar_metadado]:
        resultado = metodo(caminho)
        if any(r != "Desconhecido" for r in resultado[:4]):
            return resultado

    return resultado

# ============ EXTRAÇÃO DE FEATURES ============
def preprocess_audio(path, sr=22050):
    y, _ = librosa.load(path, sr=sr, mono=True)
    y = librosa.util.normalize(y)
    y, _ = librosa.effects.trim(y, top_db=20)
    return y, sr

def extrair_mfcc(y, sr, n_mfcc=13):
    return np.mean(librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc), axis=1)

def gerar_spectrograma(y, sr, path_out, artista=None, titulo=None):
    plt.figure(figsize=(10, 4))
    S = librosa.stft(y)
    S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
    librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='log', cmap='magma')
    plt.colorbar(format='%+2.0f dB')
    plt.title(f"{titulo or 'Desconhecido'} — {artista or 'Desconhecido'}")
    plt.tight_layout()
    plt.savefig(path_out)
    plt.close()

def extrair_caracteristicas_e_spectrograma(path, output_folder, artista, titulo):
    y, sr = preprocess_audio(path)
    mfcc_vect = extrair_mfcc(y, sr)
    nome_arquivo = os.path.splitext(os.path.basename(path))[0]
    spectro_path = os.path.join(output_folder, f"{nome_arquivo}_spectrograma.png")
    gerar_spectrograma(y, sr, spectro_path, artista, titulo)
    print(f"📸 Espectrograma salvo em: {spectro_path}")
    return mfcc_vect

# ============ RECOMENDAÇÃO ============
def recomendar_knn(nome_base, vetor_base, k=3):
    musicas = carregar_musicas()
    if len(musicas) <= 1:
        print("⚠️ Não há músicas suficientes para recomendar.")
        return

    nomes = list(musicas.keys())
    vetores = list(musicas.values())

    if nome_base in nomes:
        idx = nomes.index(nome_base)
        nomes.pop(idx)
        vetores.pop(idx)

    if not vetores:
        print("⚠️ Nenhum outro vetor para comparação.")
        return

    model = NearestNeighbors(n_neighbors=min(k, len(vetores)), metric='euclidean')
    model.fit(vetores)
    distancias, indices = model.kneighbors([vetor_base])

    print(f"🎯 Recomendações para '{nome_base}':")
    for rank, (i, dist) in enumerate(zip(indices[0], distancias[0]), 1):
        print(f"   {rank}. {nomes[i]} (distância: {dist:.2f})")

# ============ EXECUÇÃO ============
def processar_pasta(pasta, saida_spectrogramas):
    criar_tabela()
    if not os.path.exists(saida_spectrogramas):
        os.makedirs(saida_spectrogramas)

    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith((".mp3", ".wav")):
            caminho = os.path.join(pasta, arquivo)
            print(f"\n🎵 Processando: {arquivo}")

            artista, titulo, album, genero, capa_album, links = reconhecer_musica(caminho)

            caracs = extrair_caracteristicas_e_spectrograma(
                caminho, saida_spectrogramas, artista, titulo
            )

            inserir_musica(arquivo, caminho, caracs, artista, titulo, album, genero, capa_album, links)
            recomendar_knn(arquivo, caracs, k=3)

if __name__ == "__main__":
    pasta_audio = "/home/jovyan/work/audio"
    pasta_spectrogramas = "/home/jovyan/work/spectrogramas"

    if not os.path.exists(pasta_audio):
        print(f"❌ Pasta não encontrada: {pasta_audio}")
    else:
        processar_pasta(pasta_audio, pasta_spectrogramas)
