# recomendacao/recomendar.py

import os
import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import matplotlib.pyplot as plt
from config import EXPECTED_FEATURE_LENGTH, PASTA_RECOMENDACOES_IMG
from database.db import carregar_musicas

# Variáveis globais para o StandardScaler e PCA
# Serão inicializados e ajustados apenas UMA VEZ com todos os dados do banco
GLOBAL_SCALER = None
GLOBAL_PCA = None

def calcular_similaridade(distancia, escala=0.95):
    """
    Converte a distância cosseno (ou outra) em uma pontuação percentual de similaridade.
    Uma 'escala' menor → similaridade mais exigente.
    """
    similaridade = np.exp(-distancia / escala) * 100
    return round(min(100.0, similaridade), 1)

def aplicar_transformacoes(vetores, vetor_base):
    """
    Aplica normalização e, se disponível, redução de dimensionalidade com PCA.
    Retorna vetores transformados e vetor base transformado.
    """
    if GLOBAL_SCALER is None:
        print("❌ Erro: GLOBAL_SCALER não foi inicializado. Chame 'preparar_modelos_recomendacao' primeiro.")
        return None, None
        
    vetores_norm = GLOBAL_SCALER.transform(np.array(vetores, dtype=np.float64))
    vetor_base_norm = GLOBAL_SCALER.transform([vetor_base])

    if GLOBAL_PCA is not None:
        vetores_final = GLOBAL_PCA.transform(vetores_norm)
        vetor_base_final = GLOBAL_PCA.transform(vetor_base_norm)
    else:
        vetores_final = vetores_norm
        vetor_base_final = vetor_base_norm

    return vetores_final, vetor_base_final

def preparar_modelos_recomendacao(forcar_recalibragem=False):
    """
    Inicializa e ajusta os modelos globais de StandardScaler e PCA.
    """
    global GLOBAL_SCALER, GLOBAL_PCA
    
    if GLOBAL_SCALER is not None and not forcar_recalibragem:
        print("✅ Modelos de recomendação já estão prontos.")
        return

    todas_musicas_validas = carregar_musicas()
    if len(todas_musicas_validas) < 2:
        print("⚠️ Não há músicas suficientes para calibrar o modelo e recomendar.")
        return

    vetores_para_fit = np.array([m[1] for m in todas_musicas_validas], dtype=np.float64)
    nomes_validos = [m[0] for m in todas_musicas_validas]

    print("📊 Calibrando StandardScaler...")
    GLOBAL_SCALER = StandardScaler()
    GLOBAL_SCALER.fit(vetores_para_fit)

    # Se quiser usar PCA, inicialize e ajuste aqui também (opcional)
    # Exemplo para 95% de variância explicada:
    # print("📊 Calibrando PCA...")
    # GLOBAL_PCA = PCA(n_components=0.95)
    # GLOBAL_PCA.fit(GLOBAL_SCALER.transform(vetores_para_fit))
    
    if forcar_recalibragem:
        # Gera recomendações para todas as músicas após recalibragem
        os.makedirs(PASTA_RECOMENDACOES_IMG, exist_ok=True)
        for nome_musica, vetor in zip(nomes_validos, vetores_para_fit):
            if len(vetor) == EXPECTED_FEATURE_LENGTH:
                print(f"\n✨ Gerando recomendações para: {nome_musica}")
                recomendar_knn(nome_musica, vetor)
                caminho_plot = os.path.join(PASTA_RECOMENDACOES_IMG, f"{os.path.splitext(nome_musica)[0]}_recomendacoes.png")
                plot_recomendacoes(nome_musica, vetor, caminho_plot)
            else:
                print(f"⚠️ Pulando '{nome_musica}' (vetor inválido: {len(vetor)}).")
        print("\n✅ Recomendações e gráficos gerados com sucesso.")


def recomendar_knn(nome_base, vetor_base):
    musicas = carregar_musicas()
    if len(musicas) <= 1:
        print("⚠️ Não há músicas suficientes.")
        return []
    
    if GLOBAL_SCALER is None:
        print("❌ Modelos de ML não disponíveis. Execute `preparar_modelos_recomendacao`.")
        return []

    nomes, vetores, artistas, titulos, links = zip(*musicas)

    try:
        vetores_np = np.array(list(vetores), dtype=np.float64)
    except ValueError as e:
        print(f"❌ Erro ao converter vetores: {e}")
        return []

    vetor_base_np = np.array(vetor_base, dtype=np.float64)
    if len(vetor_base_np) != EXPECTED_FEATURE_LENGTH:
        print(f"❌ Tamanho do vetor base inválido: {len(vetor_base_np)}")
        return []

    idx = nomes.index(nome_base) if nome_base in nomes else -1
    
    vetores_comp = [v for i, v in enumerate(vetores) if i != idx]
    nomes_comp = [n for i, n in enumerate(nomes) if i != idx]
    artistas_comp = [a for i, a in enumerate(artistas) if i != idx]
    titulos_comp = [t for i, t in enumerate(titulos) if i != idx]
    links_comp = [l for i, l in enumerate(links) if i != idx]

    if not vetores_comp:
        return []

    vetores_reduzidos, vetor_base_reduzido = aplicar_transformacoes(vetores_comp, vetor_base_np)

    n_neighbors_val = min(3, len(vetores_reduzidos))
    model = NearestNeighbors(n_neighbors=n_neighbors_val, metric='cosine')
    model.fit(vetores_reduzidos)
    distancias, indices = model.kneighbors(vetor_base_reduzido)

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

    for bar, sim in zip(bars, similaridades):
        plt.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2, f"{sim:.1f}%", va='center')

    plt.tight_layout()
    plt.savefig(caminho_saida)
    plt.close()
    print(f"📊 Gráfico salvo em: {caminho_saida}")