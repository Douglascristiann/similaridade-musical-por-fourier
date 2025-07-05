import os
import time
import json
import hmac
import base64
import hashlib
import requests
import numpy as np
import librosa
import mysql.connector
from scipy.spatial.distance import euclidean
from tinytag import TinyTag

# Configuração do banco de dados
DB_CONFIG = {
    "user": "root",
    "password": "managerffti8p68",
    "host": "db",
    "port": 3306,
    "database": "dbmusicadata"
}

# ACRCloud
ACR_CFG = {
    'host': 'identify-us-west-2.acrcloud.com',
    'access_key': 'YkVlGYYdQrGM9qk0',
    'access_secret': 'rUU8B5mPIrTZGcFViDzgHXOuaCzVG7Qv'
}

# AudD
AUDD_TOKEN = "194e979e8e5d531ffd6d54941f5b7977"

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
                    frequencias TEXT NOT NULL,
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

def inserir_musica(nome, caminho, freq, artista, titulo, album, genero):
    if musica_existe(nome):
        print(f"⚠️ Música '{nome}' já cadastrada.")
        return
    freq_str = ",".join(map(str, freq))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tb_musicas (nome, caminho, frequencias, artista, titulo, album, genero)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (nome, caminho, freq_str, artista, titulo, album, genero))
            conn.commit()
            print(f"✅ Inserida: {nome}")

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

def preprocess_audio(path, sr=22050):
    y, _ = librosa.load(path, sr=sr, mono=True)
    y = librosa.util.normalize(y)
    y, _ = librosa.effects.trim(y, top_db=20)
    return y, sr

def extrair_caracteristicas(path, n=20):
    y, sr = preprocess_audio(path)
    fft_result = np.fft.fft(y)
    freqs = np.fft.fftfreq(len(fft_result), 1 / sr)
    mags = np.abs(fft_result)
    top_indices = np.argsort(mags)[-n:]
    return np.sort(freqs[top_indices])

def carregar_musicas():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nome, frequencias FROM tb_musicas")
            rows = cur.fetchall()
    return {nome: list(map(float, freq_str.split(","))) for nome, freq_str in rows}

def recomendar_musica(nome_base, vetor_base):
    musicas = carregar_musicas()
    candidatos = [(nome, euclidean(vetor_base, vetor)) for nome, vetor in musicas.items() if nome != nome_base]
    if candidatos:
        recomendado, dist = min(candidatos, key=lambda x: x[1])
        print(f"🎯 Recomendação: {recomendado} (distância: {dist:.2f})")
    else:
        print("⚠️ Nenhuma outra música cadastrada.")

def processar_pasta(pasta):
    criar_tabela()
    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith((".mp3", ".wav")):
            caminho = os.path.join(pasta, arquivo)
            print(f"\n🎵 Processando: {arquivo}")
            freq = extrair_caracteristicas(caminho)
            artista, titulo, album, genero = reconhecer_musica(caminho)
            inserir_musica(arquivo, caminho, freq, artista, titulo, album, genero)
            recomendar_musica(arquivo, freq)

if __name__ == "__main__":
    pasta = "/home/jovyan/work/audio"
    if not os.path.exists(pasta):
        print(f"❌ Pasta não encontrada: {pasta}")
    else:
        processar_pasta(pasta)
