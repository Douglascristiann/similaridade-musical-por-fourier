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
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
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

# Define o número esperado de características após a extração
# n_mfcc (40) * 3 (mfcc, delta, delta2) + chroma (12) + tonnetz (6) + contrast (7) + tempo (1)
EXPECTED_FEATURE_LENGTH = 40 * 3 + 12 + 6 + 6 + 1 + 1 + 1 + 1 + 1  # = 161

# Nome da tabela do banco de dados a ser usada
DB_TABLE_NAME = "tb_musicas_v3" # Usaremos a nova tabela v2

# =================== BANCO DE DADOS ===================
def conectar():
    """Estabelece uma conexão com o banco de dados MySQL."""
    return mysql.connector.connect(**DB_CONFIG)

def criar_tabela():
    """Cria a tabela de músicas no banco de dados, se ela não existir."""
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_NAME} (
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
            print(f"✅ Tabela '{DB_TABLE_NAME}' verificada/criada com sucesso.")

def musica_existe(titulo):
    """Verifica se uma música já existe na tabela do banco de dados."""
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {DB_TABLE_NAME} WHERE nome = %s", (titulo,))
            return cur.fetchone() is not titulo

def inserir_musica(nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube):
    """Insere as informações de uma música e suas características no banco de dados."""
    if len(caracteristicas) != EXPECTED_FEATURE_LENGTH:
        print(f"❌ Erro: Características da música '{nome}' têm tamanho incorreto ({len(caracteristicas)}). Esperado: {EXPECTED_FEATURE_LENGTH}. Não será inserida na '{DB_TABLE_NAME}'.")
        return

    if musica_existe(titulo):
        print(f"⚠️ Música '{titulo}' já cadastrada em '{DB_TABLE_NAME}'.\n🔗 Link: '{link_youtube}'")
        return

    carac_str = ",".join(map(str, caracteristicas))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {DB_TABLE_NAME} (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
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
            print(f"✅ Inserida no banco '{DB_TABLE_NAME}': {titulo}")
            print(f"🔗 Link da Musíca: {link_youtube}")

def carregar_musicas():
    """Carrega todas as músicas com características consistentes do banco de dados."""
    with conectar() as conn:
        with conn.cursor() as cur:
            # Filtra músicas com o número correto de características (garantindo consistência)
            cur.execute(f"SELECT nome, caracteristicas, artista, titulo, link_youtube FROM {DB_TABLE_NAME} WHERE LENGTH(caracteristicas) - LENGTH(REPLACE(caracteristicas, ',', '')) + 1 = {EXPECTED_FEATURE_LENGTH}")
            rows = cur.fetchall()
    return [(nome, list(map(float, carac.split(","))), artista, titulo, link) for nome, carac, artista, titulo, link in rows]


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

# =================== RECONHECIMENTO UNIFICADO ===================
async def reconhecer_musica(path):
    """Tenta reconhecer uma música usando Shazam, AudD ou metadados, nesta ordem."""
    resultado = await reconhecer_shazam_trechos(path)
    if resultado:
        return resultado

    print("⚠️ Shazam não encontrou. Tentando outras APIs.")
    resultado = reconhecer_audd(path)
    if any(r != "Não Encontrado" for r in resultado): # Se AudD encontrou algo (não tudo "Não Encontrado")
        return resultado

    return reconhecer_metadado(path) # Última tentativa com metadados locais

# =================== BUSCA YOUTUBE ===================
def buscar_youtube_link(artista, titulo):
    """Busca um link do YouTube para uma música."""
    if artista == "Não Encontrado" or titulo == "Não Encontrado":
        return "Não Encontrado"

    query = f"{artista} {titulo}"
    ydl_opts = {
        'quiet': True, # Suprime a saída do yt-dlp
        'skip_download': True, # Não baixa o vídeo
        'extract_flat': True, # Extrai apenas informações básicas rapidamente
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if 'entries' in result and result['entries']:
                video_id = result['entries'][0].get('id')
                if video_id:
                    return f"https://www.youtube.com/watch?v={video_id}" # Formato do seu link exemplo
    except Exception as e:
        print("\u274c Erro yt_dlp:", e)
    return "Não Encontrado"

# =================== EXTRAÇÃO DE FEATURES ===================
def preprocess_audio(path, sr=22050):
    """Carrega e pré-processa um arquivo de áudio (normaliza e remove silêncios)."""
    try:
        y, _ = librosa.load(path, sr=sr, mono=True)
        y = librosa.util.normalize(y)
        y, _ = librosa.effects.trim(y, top_db=20)
        # Garante que o áudio não seja muito curto após o trim
        if len(y) < sr * 0.1: # Mínimo de 0.1 segundos de áudio para processamento
            print(f"⚠️ Áudio muito curto após trim: {path}. Pode causar problemas na extração de features.")
            return None, None # Retorna None para indicar falha
        return y, sr
    except Exception as e:
        print(f"❌ Erro ao pré-processar áudio {path}: {e}")
        return None, None

def extrair_features_completas(y, sr):
    """
    Extrai um conjunto completo de características de áudio para análise musical e comparação de similaridade.
    Inclui MFCCs, cromas, harmonia, contraste, tempo, energia, brilho e taxa de cruzamentos por zero.
    """
    if y is None or sr is None or len(y) < sr * 0.2:
        return np.zeros(EXPECTED_FEATURE_LENGTH)

    try:
        # MFCC e derivadas
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
        mfcc_delta = librosa.feature.delta(mfcc)
        mfcc_delta2 = librosa.feature.delta(mfcc, order=2)

        mfcc_mean = np.mean(mfcc, axis=1)
        mfcc_delta_mean = np.mean(mfcc_delta, axis=1)
        mfcc_delta2_mean = np.mean(mfcc_delta2, axis=1)

        # Chroma
        chroma = np.mean(librosa.feature.chroma_stft(y=y, sr=sr), axis=1)

        # Tonnetz
        tonnetz = np.mean(librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr), axis=1)

        # Spectral Contrast
        contrast = np.mean(librosa.feature.spectral_contrast(y=y, sr=sr), axis=1)

        # Tempo (BPM)
        try:
            tempo_val = librosa.beat.tempo(y=y, sr=sr)[0]
        except Exception as e:
            print(f"⚠️ Erro ao calcular tempo: {e}")
            tempo_val = 0.0

        # Root Mean Square Energy
        rms = np.mean(librosa.feature.rms(y=y))

        # Zero-Crossing Rate
        zcr = np.mean(librosa.feature.zero_crossing_rate(y))

        # Spectral Rolloff
        rolloff = np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr))

        # Spectral Bandwidth
        bandwidth = np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr))

        # Junta tudo
        features = [
            mfcc_mean,
            mfcc_delta_mean,
            mfcc_delta2_mean,
            chroma,
            tonnetz,
            contrast,
            [tempo_val],
            [rms],
            [zcr],
            [rolloff],
            [bandwidth]
        ]

        final_features = np.concatenate(features)

        # Ajuste de tamanho
        if len(final_features) != EXPECTED_FEATURE_LENGTH:
            print(f"⚠️ Ajustando vetor de features: {len(final_features)} → {EXPECTED_FEATURE_LENGTH}")
            final_features = np.pad(final_features, (0, max(0, EXPECTED_FEATURE_LENGTH - len(final_features))))[:EXPECTED_FEATURE_LENGTH]

        return final_features

    except Exception as e:
        print(f"❌ Erro ao extrair features completas: {e}")
        return np.zeros(EXPECTED_FEATURE_LENGTH)

def gerar_spectrograma(y, sr, path_out, artista=None, titulo=None, modo='stft'):
    """
    Gera e salva um espectrograma logarítmico para o áudio.
    modo = 'stft' ou 'mel'
    """
    if y is None or sr is None:
        print(f"❌ Não foi possível gerar espectrograma para {path_out}, áudio inválido.")
        return

    # Garante que a pasta exista
    os.makedirs(os.path.dirname(path_out), exist_ok=True)

    plt.figure(figsize=(10, 4))

    if modo == 'mel':
        S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128)
        S_db = librosa.power_to_db(S, ref=np.max)
        librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='mel', cmap='magma')
    else:
        S = librosa.stft(y)
        S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
        librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='log', cmap='magma')

    plt.colorbar(format='%+2.0f dB')
    plt.title(f"{titulo or 'Sem Título'} — {artista or 'Desconhecido'}", fontsize=12)
    plt.tight_layout()
    plt.savefig(path_out, dpi=120)
    plt.close()

# def extrair_caracteristicas_e_spectrograma(path, output_folder, artista, titulo):
#     """Combina o pré-processamento, extração de features e geração de espectrograma."""
#     y, sr = preprocess_audio(path)
#     if y is None:
#         return np.zeros(EXPECTED_FEATURE_LENGTH) # Retorna zeros se pré-processamento falhou

#     features = extrair_features_completas(y, sr)
#     nome_arquivo = os.path.splitext(os.path.basename(path))[0]
#     spectro_path = os.path.join(output_folder, f"{nome_arquivo}_spectrograma.png")
#     gerar_spectrograma(y, sr, spectro_path, artista, titulo)
#     print(f"📸 Espectrograma salvo em: {spectro_path}")
#     return features
def extrair_caracteristicas_e_spectrograma(path, output_folder, artista, titulo):
    y, sr = preprocess_audio(path)
    if y is None:
        return np.zeros(EXPECTED_FEATURE_LENGTH), None

    features = extrair_features_completas(y, sr)
    nome_arquivo = os.path.splitext(os.path.basename(path))[0]
    spectro_path = os.path.join(output_folder, f"{nome_arquivo}_spectrograma.png")
    gerar_spectrograma(y, sr, spectro_path, artista, titulo)
    print(f"📸 Espectrograma salvo em: {spectro_path}")
    return features, spectro_path

# =================== RECOMENDAÇÃO ===================
def calcular_similaridade(distancia, escala=0.95):
    """
    Converte a distância cosseno (ou outra) em uma pontuação percentual de similaridade.
    Uma 'escala' menor → similaridade mais exigente.
    """
    similaridade = np.exp(-distancia / escala) * 100
    return round(min(100.0, similaridade), 1)

# Variáveis globais para o StandardScaler e PCA
# Serão inicializados e ajustados apenas UMA VEZ com todos os dados do banco
GLOBAL_SCALER = None
GLOBAL_PCA = None

def aplicar_transformacoes(vetores, vetor_base):
    """
    Aplica normalização e, se disponível, redução de dimensionalidade com PCA.
    Retorna vetores transformados e vetor base transformado.
    """
    vetores_norm = GLOBAL_SCALER.transform(np.array(vetores, dtype=np.float64))
    vetor_base_norm = GLOBAL_SCALER.transform([vetor_base])

    if GLOBAL_PCA is not None:
        vetores_final = GLOBAL_PCA.transform(vetores_norm)
        vetor_base_final = GLOBAL_PCA.transform(vetor_base_norm)
    else:
        vetores_final = vetores_norm
        vetor_base_final = vetor_base_norm

    return vetores_final, vetor_base_final


def recomendar_knn(nome_base, vetor_base):
    musicas = carregar_musicas()
    if len(musicas) <= 1:
        print("⚠️ Não há músicas suficientes.")
        return []

    nomes, vetores, artistas, titulos, links = zip(*musicas)

    try:
        vetores_np = np.array(list(vetores), dtype=np.float64)
    except ValueError as e:
        print(f"❌ Erro ao converter vetores: {e}")
        return []

    vetor_base_np = np.array(vetor_base, dtype=np.float64)  # <<<<< COLOQUE ANTES!

    # Aqui agora pode chamar
    aplicar_transformacoes(vetores_np, vetor_base_np)

    if GLOBAL_SCALER is None:
        print("❌ Modelos ML não disponíveis.")
        return []

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

    if not vetores_comp:
        return []

    vetor_base_np = np.array(vetor_base, dtype=np.float64)

    if len(vetor_base_np) != EXPECTED_FEATURE_LENGTH:
        print(f"❌ Tamanho do vetor base inválido: {len(vetor_base_np)}")
        return []

    # Aplica transformações
    vetores_reduzidos, vetor_base_reduzido = aplicar_transformacoes(vetores_comp, vetor_base_np)

    # KNN
    n_neighbors_val = min(3, len(vetores_reduzidos))
    model = NearestNeighbors(n_neighbors=n_neighbors_val, metric='cosine')
    model.fit(vetores_reduzidos)
    distancias, indices = model.kneighbors(vetor_base_reduzido)

    # Retorna resultados
    resultados = []
    for rank, (i, dist) in enumerate(zip(indices[0], distancias[0]), 1):
        similaridade = calcular_similaridade(dist)
        resultados.append({
            "rank": rank,
            "titulo": titulos_comp[i] if titulos_comp[i] != "Não Encontrado" else nomes_comp[i],
            "artista": artistas_comp[i],
            "link": links_comp[i],
            "similaridade": similaridade
        })

    print(f"🎯 Recomendações para '{nome_base}':")
    for rec in resultados:
        print(f"    {rec['rank']}. {rec['titulo']} — {rec['artista']} (link: {rec['link']}) [similaridade: {rec['similaridade']}%]")

    return resultados


# =================== EXECUÇÃO ===================
def processar_pasta(pasta, saida_spectrogramas, pasta_plot):
    """
    Processa todos os arquivos de áudio em uma pasta:
    - extrai características,
    - reconhece metadados,
    - salva no banco,
    - gera espectrogramas,
    - executa recomendações com gráfico.
    """
    criar_tabela()

    if not os.path.exists(saida_spectrogramas):
        os.makedirs(saida_spectrogramas)

    print("\n🔍 Iniciando extração de características...")
    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith((".mp3", ".wav")):
            caminho = os.path.join(pasta, arquivo)
            print(f"🎵 Processando: {arquivo}")

            artista, titulo, album, genero, capa_album = asyncio.run(reconhecer_musica(caminho))
            link_youtube = buscar_youtube_link(artista, titulo)
            caracs, _ = extrair_caracteristicas_e_spectrograma(caminho, saida_spectrogramas, artista, titulo)

            if len(caracs) == EXPECTED_FEATURE_LENGTH:
                inserir_musica(arquivo, caracs, artista, titulo, album, genero, capa_album, link_youtube)
            else:
                print(f"❌ Vetor inconsistente para '{arquivo}' ({len(caracs)}), pulando.")

    print("\n✅ Extração finalizada. Preparando recomendações...")

    todas_musicas_validas = carregar_musicas()
    if len(todas_musicas_validas) < 2:
        print("⚠️ Não há músicas suficientes para recomendar.")
        return

    vetores_para_fit = np.array([m[1] for m in todas_musicas_validas], dtype=np.float64)
    nomes_validos = [m[0] for m in todas_musicas_validas]

    global GLOBAL_SCALER, GLOBAL_PCA

    # Ajusta o scaler global
    GLOBAL_SCALER = StandardScaler()
    GLOBAL_SCALER.fit(vetores_para_fit)

    # Se quiser usar PCA, inicialize e ajuste aqui também (opcional)
    # Exemplo para 95% de variância explicada:
    # GLOBAL_PCA = PCA(n_components=0.95)
    # GLOBAL_PCA.fit(GLOBAL_SCALER.transform(vetores_para_fit))

    # Usa o primeiro vetor como base só para aplicar_transformacoes
    vetor_base = todas_musicas_validas[0][1]
    _, _ = aplicar_transformacoes(vetores_para_fit, vetor_base)


    # Gera recomendações para cada música e salva o gráfico
    os.makedirs(pasta_plot, exist_ok=True)

    for nome_musica, vetor in zip(nomes_validos, vetores_para_fit):
        if len(vetor) == EXPECTED_FEATURE_LENGTH:
            print(f"\n✨ Gerando recomendações para: {nome_musica}")
            recomendar_knn(nome_musica, vetor)

            # Gera e salva gráfico de recomendações
            caminho_plot = os.path.join(pasta_plot, f"{os.path.splitext(nome_musica)[0]}_recomendacoes.png")
            plot_recomendacoes(nome_musica, vetor, caminho_plot)
        else:
            print(f"⚠️ Pulando '{nome_musica}' (vetor inválido: {len(vetor)}).")


def plot_recomendacoes(nome_base, vetor_base, caminho_saida):
    """
    Gera um gráfico com as recomendações mais próximas para uma música base e salva como imagem.
    """
    musicas = carregar_musicas()
    nomes, vetores, artistas, titulos, links = zip(*musicas)

    if nome_base not in nomes:
        print(f"⚠️ Música base '{nome_base}' não encontrada.")
        return

    vetores_np = np.array(vetores, dtype=np.float64)
    _, vetor_base_transformado = aplicar_transformacoes(vetores_np, vetor_base)

    vetores_comp = [v for i, v in enumerate(vetores) if nomes[i] != nome_base]
    nomes_comp = [n for n in nomes if n != nome_base]
    titulos_comp = [t for i, t in enumerate(titulos) if nomes[i] != nome_base]
    artistas_comp = [a for i, a in enumerate(artistas) if nomes[i] != nome_base]

    vetores_comp_transf, _ = aplicar_transformacoes(vetores_comp, vetor_base)
    model = NearestNeighbors(n_neighbors=min(5, len(vetores_comp)), metric="cosine")
    model.fit(vetores_comp_transf)
    distancias, indices = model.kneighbors(vetor_base_transformado)

    nomes_plot = [f"{titulos_comp[i]} — {artistas_comp[i]}" for i in indices[0]]
    similaridades = [calcular_similaridade(d) for d in distancias[0]]

    # Plot
    plt.figure(figsize=(10, 5))
    bars = plt.barh(nomes_plot, similaridades, color="skyblue")
    plt.xlabel("Similaridade (%)")
    plt.title(f"🎧 Recomendações para: {nome_base}")
    plt.xlim(0, 100)
    plt.gca().invert_yaxis()

    # Adiciona os valores
    for bar, sim in zip(bars, similaridades):
        plt.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2, f"{sim:.1f}%", va='center')

    plt.tight_layout()
    plt.savefig(caminho_saida)
    plt.close()
    print(f"📊 Gráfico salvo em: {caminho_saida}")

if __name__ == "__main__":
    pasta_audio = "/home/jovyan/work/audio"
    pasta_spectrogramas = "/home/jovyan/work/cache/spectrogramas"
    pasta_recomendacoes = "/home/jovyan/work/cache/spectrogramas/recomendacoes_img"
    pasta_linksytube = "/home/jovyan/work/cache/links_youtube"

    # Garante que as pastas existam
    os.makedirs(pasta_spectrogramas, exist_ok=True)
    os.makedirs(pasta_recomendacoes, exist_ok=True)
    os.makedirs(pasta_linksytube, exist_ok=True)

    if not os.path.exists(pasta_audio):
        print(f"❌ Pasta de áudio não encontrada: {pasta_audio}")
        print("Por favor, crie a pasta e coloque suas músicas lá.")
    else:
        processar_pasta(pasta_audio, pasta_spectrogramas, pasta_recomendacoes)
