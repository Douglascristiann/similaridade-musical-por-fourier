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
EXPECTED_FEATURE_LENGTH = 40 * 3 + 12 + 6 + 7 + 1 # = 120 + 12 + 6 + 7 + 1 = 146

# Nome da tabela do banco de dados a ser usada
DB_TABLE_NAME = "tb_musicas_v2" # Usaremos a nova tabela v2

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

def musica_existe(nome):
    """Verifica se uma música já existe na tabela do banco de dados."""
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {DB_TABLE_NAME} WHERE nome = %s", (nome,))
            return cur.fetchone() is not None

def inserir_musica(nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube):
    """Insere as informações de uma música e suas características no banco de dados."""
    if len(caracteristicas) != EXPECTED_FEATURE_LENGTH:
        print(f"❌ Erro: Características da música '{nome}' têm tamanho incorreto ({len(caracteristicas)}). Esperado: {EXPECTED_FEATURE_LENGTH}. Não será inserida na '{DB_TABLE_NAME}'.")
        return

    if musica_existe(nome):
        print(f"⚠️ Música '{nome}' já cadastrada em '{DB_TABLE_NAME}'.\n🔗 Link: '{link_youtube}'")
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
            print(f"✅ Inserida no banco '{DB_TABLE_NAME}': {nome}")
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
    """Extrai um conjunto completo de características de áudio."""
    if y is None or sr is None:
        return np.array([]) # Retorna array vazio se pré-processamento falhou

    try:
        # MFCCs (Mel-frequency cepstral coefficients) e suas derivadas
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
        mfcc_delta = librosa.feature.delta(mfcc)
        mfcc_delta2 = librosa.feature.delta(mfcc, order=2)

        mfcc_mean = np.mean(mfcc, axis=1)
        mfcc_delta_mean = np.mean(mfcc_delta, axis=1)
        mfcc_delta2_mean = np.mean(mfcc_delta2, axis=1)

        # Chroma Feature (representação da intensidade de cada uma das 12 classes de pitch cromáticas)
        chroma = np.mean(librosa.feature.chroma_stft(y=y, sr=sr), axis=1)
        # Tonnetz (rede de tons, representa a estrutura harmônica)
        tonnetz = np.mean(librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr), axis=1)
        # Contraste Espectral (diferença entre picos e vales do espectro)
        contrast = np.mean(librosa.feature.spectral_contrast(y=y, sr=sr), axis=1)
        
        # Tempo (BPM)
        try:
            tempo_val = librosa.beat.tempo(y=y, sr=sr)[0]
        except Exception as e:
            print(f"⚠️ Erro ao calcular tempo, usando 0: {e}")
            tempo_val = 0.0

        features_list = [mfcc_mean, mfcc_delta_mean, mfcc_delta2_mean, chroma, tonnetz, contrast, [tempo_val]]
        
        # Concatena todas as características em um único vetor
        final_features = np.concatenate(features_list)
        
        # Garante que o vetor final tenha o tamanho esperado.
        # Se for menor (ex: áudio muito curto), preenche com zeros. Se for maior (muito raro), trunca.
        if len(final_features) != EXPECTED_FEATURE_LENGTH:
            print(f"⚠️ Ajustando tamanho do vetor de features: {len(final_features)} -> {EXPECTED_FEATURE_LENGTH}")
            if len(final_features) < EXPECTED_FEATURE_LENGTH:
                padding = np.zeros(EXPECTED_FEATURE_LENGTH - len(final_features))
                final_features = np.concatenate([final_features, padding])
            else:
                final_features = final_features[:EXPECTED_FEATURE_LENGTH]
        
        return final_features

    except Exception as e:
        print(f"❌ Erro ao extrair features completas: {e}")
        # Em caso de falha total na extração, retorna um vetor de zeros com o tamanho esperado
        return np.zeros(EXPECTED_FEATURE_LENGTH)

def gerar_spectrograma(y, sr, path_out, artista=None, titulo=None):
    """Gera e salva um espectrograma para o áudio."""
    if y is None or sr is None:
        print(f"❌ Não foi possível gerar espectrograma para {path_out}, áudio inválido.")
        return

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
    """Combina o pré-processamento, extração de features e geração de espectrograma."""
    y, sr = preprocess_audio(path)
    if y is None:
        return np.zeros(EXPECTED_FEATURE_LENGTH) # Retorna zeros se pré-processamento falhou

    features = extrair_features_completas(y, sr)
    nome_arquivo = os.path.splitext(os.path.basename(path))[0]
    spectro_path = os.path.join(output_folder, f"{nome_arquivo}_spectrograma.png")
    gerar_spectrograma(y, sr, spectro_path, artista, titulo)
    print(f"📸 Espectrograma salvo em: {spectro_path}")
    return features

# =================== RECOMENDAÇÃO ===================
def calcular_similaridade(distancia, escala=0.5): # <-- ESCALA AJUSTADA PARA 0.5
    """
    Converte a distância (cosseno) em um percentual de similaridade.
    Uma 'escala' menor torna a similaridade mais sensível à distância,
    fazendo com que os percentuais caiam mais rapidamente, resultando em recomendações mais "rigorosas".
    """
    return round(np.exp(-distancia / escala) * 100, 1)

# Variáveis globais para o StandardScaler e PCA
# Serão inicializados e ajustados apenas UMA VEZ com todos os dados do banco
GLOBAL_SCALER = None
GLOBAL_PCA = None

def inicializar_modelos_ml(vetores_caracteristicas):
    """
    Inicializa e ajusta o StandardScaler e o PCA globalmente, uma única vez,
    com base em todos os vetores de características disponíveis.
    """
    global GLOBAL_SCALER, GLOBAL_PCA

    if len(vetores_caracteristicas) == 0:
        print("⚠️ Sem vetores de características para inicializar os modelos ML. Pulando inicialização.")
        GLOBAL_SCALER = None
        GLOBAL_PCA = None
        return

    # Só inicializa e treina se ainda não foram (ou se foram resetados)
    if GLOBAL_SCALER is None or GLOBAL_PCA is None:
        print("Preparando modelos de StandardScaler e PCA...")
        
        # 1. NORMALIZAÇÃO: Escalonamento dos vetores de características
        GLOBAL_SCALER = StandardScaler()
        vetores_normalizados = GLOBAL_SCALER.fit_transform(vetores_caracteristicas)

        # 2. REDUÇÃO DE DIMENSIONALIDADE com PCA
        GLOBAL_PCA = PCA(n_components=0.95) # Retém componentes que explicam 95% da variância
        
        # Verificações de segurança para PCA (precisa de pelo menos 2 amostras/features)
        if vetores_normalizados.shape[0] < 2:
            print("⚠️ Poucas amostras para PCA. Pulando PCA para esta sessão.")
            GLOBAL_PCA = None
        elif vetores_normalizados.shape[1] < 2:
             print("⚠️ Poucas features para PCA. Pulando PCA para esta sessão.")
             GLOBAL_PCA = None
        else:
            GLOBAL_PCA.fit(vetores_normalizados)
            print(f"📊 Dimensões originais: {vetores_caracteristicas.shape[1]}, Dimensões após PCA: {GLOBAL_PCA.n_components_}")
    else:
        print("Modelos de StandardScaler e PCA já inicializados.")

def recomendar_knn(nome_base, vetor_base):
    """Gera recomendações de músicas similares usando KNN."""
    musicas = carregar_musicas() # Carrega TODAS as músicas com características consistentes da nova tabela
    
    if len(musicas) <= 1:
        print("⚠️ Não há músicas suficientes (com características consistentes) para recomendar.")
        return

    nomes, vetores, artistas, titulos, links = zip(*musicas)

    try:
        vetores_np = np.array(list(vetores), dtype=np.float64)
    except ValueError as e:
        print(f"❌ Erro ao converter vetores para numpy array: {e}")
        print("Isso geralmente acontece se as características armazenadas no banco de dados ainda tiverem tamanhos inconsistentes.")
        print("Tente limpar e recarregar suas músicas na nova tabela.")
        return

    inicializar_modelos_ml(vetores_np) # Garante que modelos estão prontos

    if GLOBAL_SCALER is None:
        print("❌ Modelos ML não foram inicializados. Não é possível recomendar.")
        return

    idx = nomes.index(nome_base) if nome_base in nomes else -1

    # Cria cópias das listas para remover a música base sem afetar as originais
    vetores_comp = list(vetores)
    nomes_comp = list(nomes)
    artistas_comp = list(artistas)
    titulos_comp = list(titulos)
    links_comp = list(links)

    if idx >= 0:
        # Remove a música base para não recomendá-la a si mesma
        vetores_comp.pop(idx)
        nomes_comp.pop(idx)
        artistas_comp.pop(idx)
        titulos_comp.pop(idx)
        links_comp.pop(idx)

    if not vetores_comp:
        print("⚠️ Não há músicas suficientes para recomendar após remover a música base.")
        return

    # Garante que o vetor base também seja um numpy array e do tipo correto
    vetor_base_np = np.array(vetor_base, dtype=np.float64)
    # Garante que o vetor base tem o tamanho esperado
    if len(vetor_base_np) != EXPECTED_FEATURE_LENGTH:
        print(f"❌ Erro: O vetor base '{nome_base}' tem tamanho incorreto ({len(vetor_base_np)}). Esperado: {EXPECTED_FEATURE_LENGTH}. Não é possível recomendar.")
        return

    # 1. NORMALIZAÇÃO: Usa o scaler GLOBAL já ajustado
    vetores_normalizados = GLOBAL_SCALER.transform(np.array(vetores_comp, dtype=np.float64))
    vetor_base_normalizado = GLOBAL_SCALER.transform([vetor_base_np])

    # 2. REDUÇÃO DE DIMENSIONALIDADE com PCA: Usa o PCA GLOBAL já ajustado (se disponível)
    if GLOBAL_PCA is not None:
        vetores_reduzidos = GLOBAL_PCA.transform(vetores_normalizados)
        vetor_base_reduzido = GLOBAL_PCA.transform(vetor_base_normalizado)
    else: # Se PCA não foi usado (ex: poucas amostras), continua com os vetores normalizados
        vetores_reduzidos = vetores_normalizados
        vetor_base_reduzido = vetor_base_normalizado

    # 3. MODELO KNN: K-Nearest Neighbors com métrica de cosseno
    # n_neighbors_val: Garante que não tente encontrar mais vizinhos do que existem
    n_neighbors_val = min(3, len(vetores_reduzidos))
    if n_neighbors_val == 0:
        print("⚠️ Não há músicas suficientes para aplicar KNN. (Isso não deveria acontecer se já foi verificado antes)")
        return

    model = NearestNeighbors(n_neighbors=n_neighbors_val, metric='cosine')
    model.fit(vetores_reduzidos)
    distancias, indices = model.kneighbors(vetor_base_reduzido)

    print(f"🎯 Recomendações para '{nome_base}':")
    for rank, (i, dist) in enumerate(zip(indices[0], distancias[0]), 1):
        nome_exibido = titulos_comp[i] if titulos_comp[i] != "Não Encontrado" else nomes_comp[i]
        link_txt = links_comp[i] if links_comp[i] != "Não Encontrado" else "Sem link"
        similaridade = calcular_similaridade(dist)
        print(f"    {rank}. {nome_exibido} — {artistas_comp[i]} (link: {link_txt}) [similaridade: {similaridade:.1f}%]")

# =================== EXECUÇÃO ===================
def processar_pasta(pasta, saida_spectrogramas):
    """
    Processa todos os arquivos de áudio em uma pasta:
    extrai características, reconhece metadados, salva no banco e gera recomendações.
    """
    criar_tabela() # Garante que a tb_musicas_v2 exista
    if not os.path.exists(saida_spectrogramas):
        os.makedirs(saida_spectrogramas)

    print("\nIniciando extração e salvamento de características de áudio...")
    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith((".mp3", ".wav")):
            caminho = os.path.join(pasta, arquivo)
            print(f"🎵 Extraindo características para: {arquivo}")
            artista, titulo, album, genero, capa_album = asyncio.run(reconhecer_musica(caminho))
            link_youtube = buscar_youtube_link(artista, titulo)
            caracs = extrair_caracteristicas_e_spectrograma(caminho, saida_spectrogramas, artista, titulo)
            
            # Só insere se as características têm o tamanho esperado (146)
            if len(caracs) == EXPECTED_FEATURE_LENGTH:
                inserir_musica(arquivo, caracs, artista, titulo, album, genero, capa_album, link_youtube)
            else:
                print(f"❌ Pulando inserção de '{arquivo}' devido a características de tamanho inconsistente ({len(caracs)}).")
    print("\nExtração e salvamento de características concluídos.")

    print("\nIniciando processo de recomendação...")
    # Carrega todas as músicas válidas (com 146 features) UMA VEZ para otimizar
    todas_musicas_validas = carregar_musicas() 

    # Cria um dicionário para acesso rápido às características por nome de arquivo
    caracteristicas_por_nome = {m[0]: m[1] for m in todas_musicas_validas}

    # Inicializa os modelos ML (StandardScaler e PCA) com todos os dados válidos
    if len(todas_musicas_validas) > 0:
        vetores_para_fit = np.array([m[1] for m in todas_musicas_validas], dtype=np.float64)
        inicializar_modelos_ml(vetores_para_fit)

    # Agora, para cada arquivo na pasta, tenta gerar recomendações
    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith((".mp3", ".wav")):
            nome_arquivo_completo = arquivo
            caracs_musica_atual = caracteristicas_por_nome.get(nome_arquivo_completo)
            
            if caracs_musica_atual is not None:
                # Validação final do tamanho do vetor base antes de recomendar
                if len(caracs_musica_atual) == EXPECTED_FEATURE_LENGTH:
                    print(f"\n✨ Gerando recomendações para: {nome_arquivo_completo}")
                    recomendar_knn(nome_arquivo_completo, caracs_musica_atual)
                else:
                    print(f"❌ Pulando recomendação para '{nome_arquivo_completo}' devido a características de tamanho inconsistente ({len(caracs_musica_atual)}).")
            else:
                print(f"⚠️ Características para '{nome_arquivo_completo}' não encontradas (ou inconsistentes) na nova tabela. Pulando recomendação.")


if __name__ == "__main__":
    pasta_audio = "/home/jovyan/work/audio"
    pasta_spectrogramas = "/home/jovyan/work/spectrogramas"
    

    # Garante que as pastas existam
    if not os.path.exists(pasta_audio):
        print(f"❌ Pasta de áudio não encontrada: {pasta_audio}")
        print("Por favor, crie a pasta e coloque suas músicas lá.")
    else:
        processar_pasta(pasta_audio, pasta_spectrogramas)