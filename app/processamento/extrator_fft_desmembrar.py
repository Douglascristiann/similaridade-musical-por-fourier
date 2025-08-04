# =================== IMPORTS ===================
import os
import sys
import numpy as np
import librosa
import librosa.display
#import matplotlib.pyplot as plt
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


def extrair_caracteristicas_e_spectrograma(path, artista, titulo, spectro_path=None):
    y, sr = preprocess_audio(path)
    if y is None:
        return np.zeros(EXPECTED_FEATURE_LENGTH), None
    features = extrair_features_completas(y, sr)
    nome_arquivo = os.path.splitext(os.path.basename(path))[0]
    registro_spectro = os.path.join(spectro_path, f"{nome_arquivo}_spectrograma.png")
    gerar_spectrograma(y, sr, registro_spectro, artista, titulo)
    return features
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
    - extrai características,
    - reconhece metadados,
    - salva no banco,
    - gera espectrogramas,
    - executa recomendações com gráfico.
    """
    #criar_tabela()

    # if not os.path.exists(saida_spectrogramas):
    #     os.makedirs(saida_spectrogramas)

    print("\n🔍 Iniciando extração de características...")

    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith((".mp3", ".wav")):
            caminho = os.path.join(pasta, arquivo)
            print(f"🎵 Processando: {arquivo}")

            meta = next((m for m in metadados if m.get("arquivo") == arquivo), None)
            if not meta:
                print(f"⚠️ Metadado não encontrado para '{arquivo}', pulando.")
                continue

            artista = meta.get("artista", "Desconhecido")
            titulo = meta.get("titulo", "Desconhecido")
            album = meta.get("album", "")
            genero = meta.get("genero", "")
            #estilo = meta.get("estilo", "")
            capa_album = meta.get("capa_album", "")
            link_youtube = meta.get("link_youtube", "")

            #caracs, _ = extrair_caracteristicas_e_spectrograma(caminho, artista, titulo, spectro_path=PASTA_SPECTROGRAMAS)

            caracs = extrair_caracteristicas_e_spectrograma(caminho, artista, titulo, spectro_path=PASTA_SPECTROGRAMAS)

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
    # os.makedirs(pasta_plot, exist_ok=True)

    # for nome_musica, vetor in zip(nomes_validos, vetores_para_fit):
    #     if len(vetor) == EXPECTED_FEATURE_LENGTH:
    #         print(f"\n✨ Gerando recomendações para: {nome_musica}")
    #         recomendar_knn(nome_musica, vetor)

    #         # Gera e salva gráfico de recomendações
    #         caminho_plot = os.path.join(pasta_plot, f"{os.path.splitext(nome_musica)[0]}_recomendacoes.png")
    #         plot_recomendacoes(nome_musica, vetor, caminho_plot)
    #     else:
    #         print(f"⚠️ Pulando '{nome_musica}' (vetor inválido: {len(vetor)}).")


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
