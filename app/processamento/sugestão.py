import librosa
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors

EXPECTED_FEATURE_LENGTH = 146  # Atualizado conforme novas features
GLOBAL_SCALER = None
GLOBAL_PCA = None

# =================== EXTRAÇÃO DE FEATURES ===================
def preprocess_audio(path, sr=22050):
    """Carrega e pré-processa um arquivo de áudio (normaliza e remove silêncios)."""
    try:
        y, _ = librosa.load(path, sr=sr, mono=True)
        y = librosa.util.normalize(y)
        y, _ = librosa.effects.trim(y, top_db=20)
        # Garante que o áudio não seja muito curto após o trim
        if len(y) < sr * 0.1:
            print(f"⚠️ Áudio muito curto após trim: {path}.")
            return None, None
        return y, sr
    except Exception as e:
        print(f"❌ Erro ao pré-processar áudio {path}: {e}")
        return None, None

def extrair_features_avancadas(y, sr):
    if y is None or sr is None:
        return np.zeros(EXPECTED_FEATURE_LENGTH)

    try:
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
        mfcc_delta = librosa.feature.delta(mfcc)
        mfcc_delta2 = librosa.feature.delta(mfcc, order=2)

        features = [
            np.mean(mfcc, axis=1),
            np.mean(mfcc_delta, axis=1),
            np.mean(mfcc_delta2, axis=1),
            np.mean(librosa.feature.chroma_stft(y=y, sr=sr), axis=1),
            np.mean(librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr), axis=1),
            np.mean(librosa.feature.spectral_contrast(y=y, sr=sr), axis=1),
            [librosa.beat.tempo(y=y, sr=sr)[0]]
        ]

        final = np.concatenate(features)
        if len(final) < EXPECTED_FEATURE_LENGTH:
            final = np.pad(final, (0, EXPECTED_FEATURE_LENGTH - len(final)))
        return final
    except Exception as e:
        print(f"❌ Erro ao extrair features: {e}")
        return np.zeros(EXPECTED_FEATURE_LENGTH)

def inicializar_modelos_ml(vetores):
    global GLOBAL_SCALER, GLOBAL_PCA
    try:
        GLOBAL_SCALER = StandardScaler()
        vetores_norm = GLOBAL_SCALER.fit_transform(vetores)
        GLOBAL_PCA = PCA(n_components=0.95)
        GLOBAL_PCA.fit(vetores_norm)
        print("✅ Modelos (Scaler + PCA) inicializados.")
    except Exception as e:
        print(f"❌ Erro ao inicializar modelos: {e}")

def calcular_similaridade(dist_cos):
    return (1 - dist_cos) * 100

def recomendar_knn(nome_base, vetor_base):
    musicas = carregar_musicas()
    if len(musicas) <= 1:
        print("⚠️ Poucas músicas para recomendar.")
        return

    nomes, vetores, artistas, titulos, links = zip(*musicas)

    try:
        vetores_np = np.array(vetores, dtype=np.float64)
    except Exception as e:
        print(f"❌ Erro ao converter vetores: {e}")
        return

    inicializar_modelos_ml(vetores_np)
    if GLOBAL_SCALER is None:
        print("❌ Modelos não inicializados.")
        return

    idx = nomes.index(nome_base) if nome_base in nomes else -1
    nomes_comp, vetores_comp = list(nomes), list(vetores)
    artistas_comp, titulos_comp, links_comp = list(artistas), list(titulos), list(links)

    if idx >= 0:
        nomes_comp.pop(idx)
        vetores_comp.pop(idx)
        artistas_comp.pop(idx)
        titulos_comp.pop(idx)
        links_comp.pop(idx)

    if not vetores_comp:
        print("⚠️ Nenhuma música restante.")
        return

    vetor_base_np = np.array(vetor_base, dtype=np.float64)
    if len(vetor_base_np) != EXPECTED_FEATURE_LENGTH:
        print("❌ Vetor base com tamanho incorreto.")
        return

    X = GLOBAL_SCALER.transform(vetores_comp)
    X_base = GLOBAL_SCALER.transform([vetor_base_np])

    if GLOBAL_PCA:
        X = GLOBAL_PCA.transform(X)
        X_base = GLOBAL_PCA.transform(X_base)

    k = min(7, len(X))
    model = NearestNeighbors(n_neighbors=k, metric='cosine')
    model.fit(X)
    dist, idxs = model.kneighbors(X_base)

    print(f"🎧 Recomendações para '{nome_base}':")
    for rank, (i, d) in enumerate(zip(idxs[0], dist[0]), 1):
        nome = titulos_comp[i] if titulos_comp[i] != "Não Encontrado" else nomes_comp[i]
        print(f"   {rank}. {nome} — {artistas_comp[i]} [similaridade: {calcular_similaridade(d):.1f}%] | link: {links_comp[i]}")
