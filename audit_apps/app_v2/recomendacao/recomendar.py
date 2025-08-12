# recomendacao/recomendar.py

import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from database.db import carregar_musicas
from config import EXPECTED_FEATURE_LENGTH

GLOBAL_SCALER = None

def calcular_similaridade(d, escala=0.95):
    return np.exp(-d / escala) * 100

def preparar_modelos_recomendacao(forcar_recalibragem=False):
    global GLOBAL_SCALER
    mus = carregar_musicas()
    if not mus:
        return
    vet = np.array([m[1] for m in mus], dtype=np.float64)
    if forcar_recalibragem or GLOBAL_SCALER is None:
        GLOBAL_SCALER = StandardScaler().fit(vet)

def recomendar_knn(nome_base, vetor_base):
    mus = carregar_musicas()
    if len(mus) < 2:
        print("⚠️ Poucas músicas para recomendar.")
        return []

    nomes, vets, arts, tits, links = zip(*mus)
    base_np = np.array(vetor_base, dtype=np.float64)
    if len(base_np) != EXPECTED_FEATURE_LENGTH:
        print("⚠️ Vetor base inválido.")
        return []

    if GLOBAL_SCALER is None:
        preparar_modelos_recomendacao()

    # Prepara conjunto sem a música base
    comp = [(n, v, a, l) for n, v, a, l in zip(nomes, vets, arts, links) if n != nome_base]
    vs   = np.array([x[1] for x in comp], dtype=np.float64)
    br   = GLOBAL_SCALER.transform([base_np])[0]

    # Executa KNN
    knn = NearestNeighbors(n_neighbors=min(3, len(vs)), metric='cosine')
    knn.fit(GLOBAL_SCALER.transform(vs))
    dists, idxs = knn.kneighbors([br])

    # Imprime top 3 em uma linha cada
    print("\n🎯 Top 3 Recomendações:")
    resultados = []
    for rank, (i, dist) in enumerate(zip(idxs[0], dists[0]), 1):
        title, artist, link = comp[i][0], comp[i][2], comp[i][3]
        sim = round(calcular_similaridade(dist), 1)
        print(f"{rank}) {title} — {artist} — {sim}% — {link}")
        resultados.append((title, artist, sim, link))

    return resultados
