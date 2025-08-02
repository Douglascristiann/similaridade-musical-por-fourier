# processamento/extrator_fft.py

import os
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from config import EXPECTED_FEATURE_LENGTH, PASTA_SPECTROGRAMAS
from database.db import inserir_musica
from API.reconhecimento import reconhecer_musica
# Remova a linha abaixo para evitar a importação circular
# from API.processar_links import buscar_youtube_link
import asyncio

# ... (todas as outras funções de extração de features, preprocessamento, etc.)

def processar_audio_local(caminho):
    """Processa um arquivo de áudio local, extraindo metadados, features e salvando no banco."""
    print(f"🎵 Processando arquivo local: {caminho}")

    # Reconhecimento e busca de link do youtube
    # A busca do link precisa ser feita em outro lugar, por exemplo, no próprio processar_links.py
    # Ou a chamada à API de reconhecimento já retorna o link.
    artista, titulo, album, genero, capa_album = asyncio.run(reconhecer_musica(caminho))
    link_youtube = 'Não Encontrado' # Ou o valor retornado pela API

    # Extração de features e geração de espectrograma
    y, sr = preprocess_audio(caminho)
    if y is None:
        return
        
    features = extrair_features_completas(y, sr)
    
    nome_arquivo = os.path.splitext(os.path.basename(caminho))[0]
    spectro_path = os.path.join(PASTA_SPECTROGRAMAS, f"{nome_arquivo}_spectrograma.png")
    gerar_spectrograma(y, sr, spectro_path, artista, titulo)
    print(f"📸 Espectrograma salvo em: {spectro_path}")

    # Inserção no banco
    if len(features) == EXPECTED_FEATURE_LENGTH:
        inserir_musica(nome_arquivo, features, artista, titulo, album, genero, capa_album, link_youtube)
    else:
        print(f"❌ Vetor de características inconsistente ({len(features)}), não será inserido no banco.")
    
# A função processar_audio_youtube não é mais necessária aqui.
# A lógica de download deve estar em processar_links.py.