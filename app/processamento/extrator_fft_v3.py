import os
import time
import base64
import hashlib
import hmac
import asyncio

import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from tinytag import TinyTag
from sklearn.neighbors import NearestNeighbors
from shazamio import Shazam
import mysql.connector
import json
from yt_dlp import YoutubeDL
#--------------------mudança para yt_dlp----------------
#from bs4 import BeautifulSoup
#import requests




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
                    nome VARCHAR(255) NOT NULL,
                    caracteristicas TEXT NOT NULL,
                    artista VARCHAR(255),
                    titulo VARCHAR(255),
                    album VARCHAR(255),
                    genero VARCHAR(255),
                    capa_album TEXT,
                    link_youtube TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

def musica_existe(nome):
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM tb_musicas WHERE nome = %s", (nome,))
            return cur.fetchone() is not None

def inserir_musica(nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube):
    if musica_existe(nome):
        print(f"⚠️ Música '{nome}' já cadastrada.")
        return
    carac_str = ",".join(map(str, caracteristicas))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tb_musicas (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (nome, carac_str, artista, titulo, album, genero, capa_album, link_youtube))
            conn.commit()
            print(f"✅ Inserida no banco: {nome}")

def carregar_musicas():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nome, caracteristicas, artista, titulo, link_youtube FROM tb_musicas")
            rows = cur.fetchall()
    return [(nome, list(map(float, carac.split(","))), artista, titulo, link) for nome, carac, artista, titulo, link in rows]

# ============ BUSCA YOUTUBE ============


# ============ RECONHECIMENTO ============
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
            capa_url = track.get("images", {}).get("coverart")
            return artista, titulo, album, genero, capa_url
    except Exception as e:
        print("❌ Erro ShazamIO:", e)
    return ("Desconhecido",) * 5

def reconhecer_musica(path):
    return asyncio.run(reconhecer_shazam(path))

def buscar_youtube_link(artista, titulo):
    query = f"{artista} {titulo}"
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'extract_flat': True,  # << IGNORA detalhes que exigem login
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if 'entries' in result and result['entries']:
                video_id = result['entries'][0].get('id')
                if video_id:
                    return f"https://www.youtube.com/watch?v={video_id}"
    except Exception as e:
        print("❌ Erro yt_dlp (flat search):", e)
    return None
    
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
def recomendar_knn(nome_base, vetor_base):
    musicas = carregar_musicas()
    if len(musicas) <= 1:
        print("⚠️ Não há músicas suficientes para recomendar.")
        return

    nomes, vetores, artistas, titulos, links = zip(*musicas)
    idx = nomes.index(nome_base) if nome_base in nomes else -1
    vetores_comp = list(vetores)
    nomes_comp = list(nomes)
    artistas_comp = list(artistas)
    titulos_comp = list(titulos)
    links_comp = list(links)

    if idx >= 0:
        vetores_comp.pop(idx)
        nomes_comp.pop(idx)
        artistas_comp.pop(idx)
        titulos_comp.pop(idx)
        links_comp.pop(idx)

    model = NearestNeighbors(n_neighbors=min(3, len(vetores_comp)), metric='euclidean')
    model.fit(vetores_comp)
    distancias, indices = model.kneighbors([vetor_base])

    print(f"🎯 Recomendações para '{nome_base}':")
    for rank, (i, dist) in enumerate(zip(indices[0], distancias[0]), 1):
        link_txt = links_comp[i] if links_comp[i] else "Sem link"
        print(f"   {rank}. {titulos_comp[i]} — {artistas_comp[i]} (link: {link_txt}) [distância: {dist:.2f}]")

# ============ EXECUÇÃO ============
def processar_pasta(pasta, saida_spectrogramas):
    criar_tabela()
    if not os.path.exists(saida_spectrogramas):
        os.makedirs(saida_spectrogramas)

    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith((".mp3", ".wav")):
            caminho = os.path.join(pasta, arquivo)
            print(f"\n🎵 Processando: {arquivo}")
            artista, titulo, album, genero, capa_album = reconhecer_musica(caminho)
            link_youtube = buscar_youtube_link(artista, titulo)
            caracs = extrair_caracteristicas_e_spectrograma(caminho, saida_spectrogramas, artista, titulo)
            inserir_musica(arquivo, caracs, artista, titulo, album, genero, capa_album, link_youtube)
            recomendar_knn(arquivo, caracs)

if __name__ == "__main__":
    pasta_audio = "/home/jovyan/work/audio"
    pasta_spectrogramas = "/home/jovyan/work/spectrogramas"

    if not os.path.exists(pasta_audio):
        print(f"❌ Pasta não encontrada: {pasta_audio}")
    else:
        processar_pasta(pasta_audio, pasta_spectrogramas)