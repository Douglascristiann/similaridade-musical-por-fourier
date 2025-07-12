# =================== IMPORTS ===================
import os
import asyncio
import requests
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
import soundfile as sf
from librosa.feature.rhythm import tempo
from tinytag import TinyTag
from sklearn.neighbors import NearestNeighbors
from shazamio import Shazam
from yt_dlp import YoutubeDL
import mysql.connector
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# =================== CONFIGURAÇÃO ===================
DB_CONFIG = {
    "user": "root",
    "password": "managerffti8p68",
    "host": "db",
    "port": 3306,
    "database": "dbmusicadata"
}

AUDD_TOKEN = "194e979e8e5d531ffd6d54941f5b7977"

# =================== BANCO DE DADOS ===================
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
        print(f"⚠️ Música '{nome}' já cadastrada.\n🔗 Link: '{link_youtube}'")
        return

    carac_str = ",".join(map(str, caracteristicas))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tb_musicas (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                nome,
                carac_str,
                artista or "Não Encontrado",
                titulo or "Não Encontrado",
                album or "Não Encontrado",
                genero or "Não Encontrado",
                capa_album or "Não Encontrado",
                link_youtube or "Não Encontrado"
            ))
            conn.commit()
            print(f"✅ Inserida no banco: {nome}")
            print(f"🔗 Link da Musíca: {link_youtube}")

def carregar_musicas():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nome, caracteristicas, artista, titulo, link_youtube FROM tb_musicas")
            rows = cur.fetchall()
    return [(nome, list(map(float, carac.split(","))), artista, titulo, link) for nome, carac, artista, titulo, link in rows]


# =================== PRÉ-PROCESSAMENTO SHAZAM ===================
def preparar_trecho_para_shazam(y, sr):
    y_norm = librosa.util.normalize(y)
    y_trim, _ = librosa.effects.trim(y_norm, top_db=20)
    if sr != 44100:
        y_trim = librosa.resample(y_trim, orig_sr=sr, target_sr=44100)
        sr = 44100
    return y_trim, sr

async def tentar_reconhecer(shazam, arquivo, tentativas=3):
    for tentativa in range(tentativas):
        try:
            result = await shazam.recognize(arquivo)
            return result
        except Exception as e:
            print(f"❌ Erro ShazamIO na tentativa {tentativa+1}: {e}")
            await asyncio.sleep(1)
    return None

async def reconhecer_shazam_trechos(path):
    y, sr = librosa.load(path, sr=None)
    duracao_total = librosa.get_duration(path=path)
    shazam = Shazam()

    trecho_duracao = 15
    passo = 10
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
                    "Não Encontrado"
                )
    except Exception as e:
        print("\u274c Erro AudD:", e)
    return ("Não Encontrado",) * 5

def reconhecer_metadado(path):
    try:
        tag = TinyTag.get(path)
        return (
            tag.artist or "Não Encontrado",
            tag.title or "Não Encontrado",
            tag.album or "Não Encontrado",
            tag.genre or "Não Encontrado",
            "Não Encontrado"
        )
    except:
        return ("Não Encontrado",) * 5

# =================== RECONHECIMENTO UNIFICADO ===================
async def reconhecer_musica(path):
    resultado = await reconhecer_shazam_trechos(path)
    if resultado:
        return resultado

    print("⚠️ Shazam não encontrou. Tentando outras APIs.")
    resultado = reconhecer_audd(path)
    if any(r != "Não Encontrado" for r in resultado):
        return resultado

    return reconhecer_metadado(path)

# =================== BUSCA YOUTUBE ===================
def buscar_youtube_link(artista, titulo):
    if artista == "Não Encontrado" or titulo == "Não Encontrado":
        return "Não Encontrado"

    query = f"{artista} {titulo}"
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'extract_flat': True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if 'entries' in result and result['entries']:
                video_id = result['entries'][0].get('id')
                if video_id:
                    return f"https://www.youtube.com/watch?v={video_id}"
    except Exception as e:
        print("\u274c Erro yt_dlp:", e)
    return "Não Encontrado"

# =================== EXTRAÇÃO DE FEATURES ===================
def preprocess_audio(path, sr=22050):
    y, _ = librosa.load(path, sr=sr, mono=True)
    y = librosa.util.normalize(y)
    y, _ = librosa.effects.trim(y, top_db=20)
    return y, sr

def extrair_features_completas(y, sr):
    mfcc = np.mean(librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13), axis=1)
    chroma = np.mean(librosa.feature.chroma_stft(y=y, sr=sr), axis=1)
    tonnetz = np.mean(librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr), axis=1)
    contrast = np.mean(librosa.feature.spectral_contrast(y=y, sr=sr), axis=1)
    tempo = librosa.beat.tempo(y=y, sr=sr)[0]
    return np.concatenate([mfcc, chroma, tonnetz, contrast, [tempo]])

def gerar_spectrograma(y, sr, path_out, artista=None, titulo=None):
    plt.figure(figsize=(10, 4))
    S = librosa.stft(y)
    S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
    librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='log', cmap='magma')
    plt.colorbar(format='%+2.0f dB')
    plt.title(f"{titulo or 'Não Encontrado'} — {artista or 'Não Encontrado'}")
    plt.tight_layout()
    plt.savefig(path_out)
    plt.close()

def extrair_caracteristicas_e_spectrograma(path, output_folder, artista, titulo):
    y, sr = preprocess_audio(path)
    features = extrair_features_completas(y, sr)
    nome_arquivo = os.path.splitext(os.path.basename(path))[0]
    spectro_path = os.path.join(output_folder, f"{nome_arquivo}_spectrograma.png")
    gerar_spectrograma(y, sr, spectro_path, artista, titulo)
    print(f"📸 Espectrograma salvo em: {spectro_path}")
    return features

# =================== RECOMENDAÇÃO ===================
def calcular_similaridade(distancia, escala=50):
    return round(np.exp(-distancia / escala) * 100, 1)

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
        nome_exibido = titulos_comp[i] if titulos_comp[i] != "Não Encontrado" else nomes_comp[i]
        link_txt = links_comp[i] if links_comp[i] != "Não Encontrado" else "Sem link"
        similaridade = calcular_similaridade(dist)
        print(f"   {rank}. {nome_exibido} — {artistas_comp[i]} (link: {link_txt}) [similaridade: {similaridade:.1f}%]")

# =================== EXECUÇÃO ===================
def processar_pasta(pasta, saida_spectrogramas):
    criar_tabela()
    if not os.path.exists(saida_spectrogramas):
        os.makedirs(saida_spectrogramas)

    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith((".mp3", ".wav")):
            caminho = os.path.join(pasta, arquivo)
            print(f"\n🎵 Processando: {arquivo}")

            artista, titulo, album, genero, capa_album = asyncio.run(reconhecer_musica(caminho))
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
