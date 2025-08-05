# =================== IMPORTS ===================
import os
import sys
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from librosa.feature.rhythm import tempo
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import warnings
from config import EXPECTED_FEATURE_LENGTH, PASTA_SPECTROGRAMAS
from spectrograma_caracteristicas import gerar_spectrograma
warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.append(os.path.join(os.path.dirname(__file__), "DB"))

from consulta_insercao import inserir_musica, carregar_musicas
from config import PASTA_RECOMENDACOES_IMG

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


def extrair_caracteristicas_e_spectrograma(path, output_folder, artista, titulo):
    """
    Combina o pré-processamento, extração de features e geração de espectrograma.
    Retorna (features, caminho_do_espectrograma).
    """
    # 1) Pré-processamento
    y, sr = preprocess_audio(path)
    if y is None:
        # se falhar, vetor zero e sem espectrograma
        return np.zeros(EXPECTED_FEATURE_LENGTH), None

    # 2) Extração de features puros
    features = extrair_features_completas(y, sr)

    # 3) Monta e salva o espectrograma
    nome_arquivo = os.path.splitext(os.path.basename(path))[0]
    spectro_path = os.path.join(output_folder, f"{nome_arquivo}_spectrograma.png")
    gerar_spectrograma(y, sr, spectro_path, artista, titulo)
    print(f"📸 Espectrograma salvo em: {spectro_path}")

    # 4) Retorna o vetor e o caminho do arquivo gerado
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
def processar_pasta(pasta, metadados):
    """
    Processa todos os arquivos de áudio em uma pasta:
    - extrai características (features e espectrograma),
    - salva no banco,
    - prepara recomendações.
    """
    # Garante que tabela e pastas existam
    criar_tabela()
    os.makedirs(PASTA_SPECTROGRAMAS, exist_ok=True)
    os.makedirs(PASTA_PLOT, exist_ok=True)

    print("\n🔍 Iniciando extração de características...")

    for arquivo in os.listdir(pasta):
        if not arquivo.lower().endswith((".mp3", ".wav")):
            continue

        caminho = os.path.join(pasta, arquivo)
        print(f"🎵 Processando: {arquivo}")

        # Busca metadados pelo nome de arquivo
        meta = next((m for m in metadados if m.get("arquivo") == arquivo), None)
        if not meta:
            print(f"⚠️ Metadado não encontrado para '{arquivo}', pulando.")
            continue

        artista     = meta.get("artista", "Desconhecido")
        titulo      = meta.get("titulo",  "Desconhecido")
        album       = meta.get("album",   "")
        genero      = meta.get("genero",  "")
        capa_album  = meta.get("capa_album", "")
        link_youtube= meta.get("link_youtube", "")

        # === CORREÇÃO AQUI: extrai features e espectrograma em duas variáveis ===
        caracs, spectro = extrair_caracteristicas_e_spectrograma(
            caminho,
            PASTA_SPECTROGRAMAS,
            artista,
            titulo
        )

        # Verifica integridade do vetor
        if len(caracs) != EXPECTED_FEATURE_LENGTH:
            print(f"❌ Vetor inconsistente para '{arquivo}' ({len(caracs)}), pulando.")
            continue

        # Insere no banco
        inserir_musica(
            arquivo,
            caracs,
            artista,
            titulo,
            album,
            genero,
            capa_album,
            link_youtube
        )

    print("\n✅ Extração finalizada. Preparando recomendações...")

    todas_musicas = carregar_musicas()
    if len(todas_musicas) < 2:
        print("⚠️ Não há músicas suficientes para recomendar.")
        return

    # Prepara vetores e nomes para o scaler
    vetores = np.array([m[1] for m in todas_musicas], dtype=np.float64)
    nomes   = [m[0] for m in todas_musicas]

    global GLOBAL_SCALER, GLOBAL_PCA
    GLOBAL_SCALER = StandardScaler().fit(vetores)
    # Se desejar usar PCA, descomente:
    # GLOBAL_PCA = PCA(n_components=0.95)
    # GLOBAL_PCA.fit(GLOBAL_SCALER.transform(vetores))

    # Exemplo de uso de aplicar_transformacoes (opcional)
    vetor_base = vetores[0]
    _, _ = aplicar_transformacoes(vetores, vetor_base)

    # Geração de gráficos de recomendação
    for nome_musica, vetor in zip(nomes, vetores):
        if len(vetor) != EXPECTED_FEATURE_LENGTH:
            print(f"⚠️ Pulando '{nome_musica}' (vetor inválido: {len(vetor)}).")
            continue

        print(f"\n✨ Gerando recomendações para: {nome_musica}")
        recomendar_knn(nome_musica, vetor)

        caminho_plot = os.path.join(
            PASTA_RECOMENDACOES_IMG,
            f"{os.path.splitext(nome_musica)[0]}_recomendacoes.png"
        )
        plot_recomendacoes(nome_musica, vetor, caminho_plot)


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

# if __name__ == "__main__":
#     pasta_audio = "/home/jovyan/work/audio"
#     pasta_spectrogramas = "/home/jovyan/work/cache/spectrogramas"
#     pasta_recomendacoes = "/home/jovyan/work/cache/spectrogramas/recomendacoes_img"
#     pasta_linksytube = "/home/jovyan/work/cache/links_youtube"

    # Garante que as pastas existam
    # os.makedirs(pasta_spectrogramas, exist_ok=True)
    # os.makedirs(pasta_recomendacoes, exist_ok=True)
    # os.makedirs(pasta_linksytube, exist_ok=True)

    # if not os.path.exists(pasta_audio):
    #     print(f"❌ Pasta de áudio não encontrada: {pasta_audio}")
    #     print("Por favor, crie a pasta e coloque suas músicas lá.")
    # else:
    #     processar_pasta(pasta_audio, pasta_spectrogramas, pasta_recomendacoes)
