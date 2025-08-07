# processamento/extrator_fft.py

import os
import numpy as np
import asyncio
import logging

from API.reconhecimento_unificado import reconhecer_musica
from database.db import inserir_musica, musica_existe
from recomendacao.recomendar import preparar_modelos_recomendacao, recomendar_knn
from processamento.features import preprocess_audio, extrair_features_completas
from processamento.spectrograma import gerar_spectrograma
from utils.youtube import buscar_youtube_link
import config  # traz AUDIO_FOLDER de config.py

logger = logging.getLogger('extrator_fft')


def extrair_caracteristicas_e_spectrograma(path, pasta_out, artista, titulo):
    logger.info(f"[PROC] Gerando features e espectrograma para: {path}")
    y, sr = preprocess_audio(path)
    if y is None:
        return np.zeros(config.EXPECTED_FEATURE_LENGTH), None

    features = extrair_features_completas(y, sr)
    nome_base = os.path.splitext(os.path.basename(path))[0]
    spec_path = os.path.join(pasta_out, f"{nome_base}.png")
    gerar_spectrograma(y, sr, spec_path, artista, titulo)
    logger.info(f"[SPEC] Spectrograma salvo em: {spec_path}")

    return features, spec_path


def processar_audio_local(caminho_audio, skip_recommend=False, skip_db_check=False):
    """
    Processa um arquivo de áudio:
      1) Verifica no banco (se skip_db_check=False)
      2) Reconhece metadados
      3) Busca link YouTube
      4) Extrai features + espectrograma
      5) Insere no banco
      6) (Opcional) Gera recomendações
    """
    nome = os.path.basename(caminho_audio)

    # 1️⃣ Checa existência no banco
    if not skip_db_check and musica_existe(nome):
        logger.warning(f"⚠️ '{nome}' já cadastrado no banco. Pulando.")
        return

    logger.info(f"[PROC] Iniciando processamento: {nome}")

    # 2️⃣ Reconhecimento
    artista, titulo, album, genero, capa = asyncio.run(
        reconhecer_musica(caminho_audio)
    )
    logger.info(f"[SHZ] Reconhecido: {artista} — {titulo}")

    # 3️⃣ YouTube
    link = buscar_youtube_link(artista, titulo)
    logger.info(f"[YTD] Link YouTube: {link}")

    # 4️⃣ Features + espectrograma
    pasta_spec = os.path.join(config.AUDIO_FOLDER, 'spectrogramas')
    features, _ = extrair_caracteristicas_e_spectrograma(
        caminho_audio, pasta_spec, artista, titulo
    )
    if len(features) != config.EXPECTED_FEATURE_LENGTH:
        logger.error(f"❌ Features inconsistentes: {len(features)}/{config.EXPECTED_FEATURE_LENGTH}")
        return

    # 5️⃣ Inserção no banco
    inserir_musica(nome, features, artista, titulo, album, genero, capa, link)
    logger.info(f"[DB] '{nome}' inserido com sucesso.")

    # 6️⃣ Recomendações
    if not skip_recommend:
        preparar_modelos_recomendacao()
        recomendar_knn(nome, features)
