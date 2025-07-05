import os
import time
import json
import hmac
import base64
import hashlib
import requests
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
import mysql.connector
from tinytag import TinyTag
from sklearn.neighbors import NearestNeighbors

# ==========================
# CONFIGURAÇÕES
# ==========================

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

# ==========================
# BANCO DE DADOS
# ==========================

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
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

def musica_existe(nome):
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM tb_musicas WHERE nome = %s", (nome,))
            return cur.fetchone() is not None

def inserir_musica(nome, caminho, caracteristicas, artista, titulo, album, genero):
    if musica_existe(nome):
        print(f"⚠️ Música '{nome}' já cadastrada.")
        return
    carac_str = ",".join(map(str, caracteristicas))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tb_musicas (nome, caminho, caracteristicas, artista, titulo, album, genero)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (nome, caminho, carac_str, artista, titulo, album, genero))
            conn.commit()
            print(f"✅ Inserida no banco: {nome}")

def carregar_musicas():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nome, caracteristicas FROM tb_musicas")
            rows = cur.fetchall()
    musicas = {}
    for nome, carac_str in rows:
        vetor = list(map(float, carac_str.split(",")))
        musicas[nome] = vetor
    return musicas

# ==========================
# APIs DE RECONHECIMENTO
# ==========================

def assinar_acr(timestamp):
    s = "\n".join(["POST", "/v1/identify", ACR_CFG['access_key'], "audio", "1", str(timestamp)])
    h = hmac.new(ACR_CFG['access_secret'].encode(), s.encode(), hashlib.sha1).digest()
    return base64.b64encode(h).decode()

def identificar_acr(caminho):
    timestamp = int(time.time())
    signature = assinar_acr(timestamp)
    url = f"https://{ACR_CFG['host']}/v1/identify"

    with open(caminho, 'rb') as f:
        sample = f.read()

    payload = {
        "access_key": ACR_CFG['access_key'],
        "timestamp": timestamp,
        "signature": signature,
        "data_type": "audio",
        "signature_version": "1",
        "sample_bytes": len(sample)
    }
    files = {"sample": sample}

    try:
        res = requests.post(url, data=payload, files=files, timeout=10)
        data = res.json()
        music = data.get("metadata", {}).get("music", [])
        if music and music[0].get("score", 0) >= 80:
            m = music[0]
            return (
                m["artists"][0]["name"],
                m["title"],
                m.get("album", {}).get("name", "Desconhecido"),
                m.get("genres", [{}])[0].get("name", "Desconhecido")
            )
    except Exception as e:
        print(f"❌ Erro ACRCloud: {e}")
    return None

def identificar_audd(caminho):
    try:
        files = {'file': open(caminho, 'rb')}
        data = {'api_token': AUDD_TOKEN, 'return': 'apple_music,spotify'}
        res = requests.post('https://api.audd.io/', data=data, files=files, timeout=10)
        r = res.json()
        if r.get("status") == "success" and r.get("result"):
            result = r["result"]
            return (
                result.get("artist", "Desconhecido"),
                result.get("title", "Desconhecido"),
                result.get("album", "Desconhecido"),
                result.get("genre", "Desconhecido")
            )
    except Exception as e:
        print(f"❌ Erro AudD: {e}")
    return None

def identificar_metadado(caminho):
    try:
        tag = TinyTag.get(caminho)
        return (
            tag.artist or "Desconhecido",
            tag.title or "Desconhecido",
            tag.album or "Desconhecido",
            tag.genre or "Desconhecido"
        )
    except:
        return ("Desconhecido",) * 4

def reconhecer_musica(caminho):
    for metodo in [identificar_acr, identificar_audd, identificar_metadado]:
        resultado = metodo(caminho)
        if resultado and any(r != "Desconhecido" for r in resultado):
            print(f"🔍 Reconhecida: {resultado[0]} - {resultado[1]}")
            return resultado
    return ("Desconhecido",) * 4

# ==========================
# PRÉ-PROCESSAMENTO E FEATURES
# ==========================

def preprocess_audio(path, sr=22050):
    y, _ = librosa.load(path, sr=sr, mono=True)
    y = librosa.util.normalize(y)
    y, _ = librosa.effects.trim(y, top_db=20)
    return y, sr

def extrair_mfcc(y, sr, n_mfcc=13):
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
    return np.mean(mfcc, axis=1)

def gerar_spectrograma(y, sr, path_out, artista=None, titulo=None):
    plt.figure(figsize=(10, 4))
    S = librosa.stft(y)
    S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
    librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='log', cmap='magma')
    plt.colorbar(format='%+2.0f dB')
    if artista and titulo:
        plt.title(f"{titulo} — {artista}")
    else:
        plt.title("Espectrograma")
    plt.tight_layout()
    plt.savefig(path_out)
    plt.close()

def extrair_caracteristicas_e_spectrograma(path, output_folder, artista, titulo, n_mfcc=13):
    y, sr = preprocess_audio(path)
    mfcc_vect = extrair_mfcc(y, sr, n_mfcc=n_mfcc)

    nome_arquivo = os.path.splitext(os.path.basename(path))[0]
    filename = f"{nome_arquivo}_spectrograma.png"
    spectro_path = os.path.join(output_folder, filename)

    gerar_spectrograma(y, sr, spectro_path, artista, titulo)
    print(f"📸 Espectrograma salvo em: {spectro_path}")

    return mfcc_vect

# ==========================
# RECOMENDAÇÃO VIA KNN
# ==========================

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
        recomendado = nomes[i]
        print(f"   {rank}. {recomendado} (distância: {dist:.2f})")

# ==========================
# MAIN
# ==========================

def processar_pasta(pasta, spectrogramas_output):
    criar_tabela()
    if not os.path.exists(spectrogramas_output):
        os.makedirs(spectrogramas_output)

    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith((".mp3", ".wav")):
            caminho = os.path.join(pasta, arquivo)
            print(f"\n🎵 Processando: {arquivo}")

            artista, titulo, album, genero = reconhecer_musica(caminho)

            caracs = extrair_caracteristicas_e_spectrograma(
                caminho,
                spectrogramas_output,
                artista,
                titulo
            )

            inserir_musica(arquivo, caminho, caracs, artista, titulo, album, genero)
            recomendar_knn(arquivo, caracs, k=3)

if __name__ == "__main__":
    pasta_audio = "/home/jovyan/work/audio"
    pasta_spectrogramas = "/home/jovyan/work/spectrogramas"

    if not os.path.exists(pasta_audio):
        print(f"❌ Pasta não encontrada: {pasta_audio}")
    else:
        processar_pasta(pasta_audio, pasta_spectrogramas)
