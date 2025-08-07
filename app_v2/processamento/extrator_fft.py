# processamento/extrator_fft.py

import os
import asyncio
import logging
import gc
import numpy as np

from config import EXPECTED_FEATURE_LENGTH, AUDIO_FOLDER
from API.reconhecimento_unificado import reconhecer_musica
from database.db import musica_existe, inserir_musica
from recomendacao.recomendar import preparar_modelos_recomendacao, recomendar_knn
from processamento.features import preprocess_audio, extrair_features_completas
from processamento.spectrograma import gerar_spectrograma
from utils.youtube import buscar_youtube_link

logger = logging.getLogger('extrator_fft')


def extrair_caracteristicas_e_spectrograma(path, pasta_out, artista, titulo):
    logger.info(f"[FEAT] Gerando features para: {path}")
    y, sr = preprocess_audio(path)
    if y is None:
        logger.warning(f"[FEAT] Pré-processamento falhou: {path}")
        return None, None

    features = extrair_features_completas(y, sr)

    nome_base = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(pasta_out, exist_ok=True)
    spec_path = os.path.join(pasta_out, f"{nome_base}.png")
    gerar_spectrograma(y, sr, spec_path, artista, titulo)
    logger.info(f"[SPEC] Spectrograma salvo em: {spec_path}")

    # libera áudio
    del y, sr
    gc.collect()

    return features, spec_path


def processar_audio_local(caminho_audio, skip_recommend=False, skip_db_check=False):
    nome = os.path.basename(caminho_audio)
    spec_dir = os.path.join(AUDIO_FOLDER, 'spectrogramas')
    spec_path = os.path.join(spec_dir, f"{os.path.splitext(nome)[0]}.png")

    # 1) Skip se já existe no DB OU já há espectrograma salvo
    if not skip_db_check and (musica_existe(nome) or os.path.exists(spec_path)):
        logger.info(f"[SKIP] '{nome}' já processado (DB ou espectrograma).")
        return

    logger.info(f"[PROC] Iniciando processamento: {nome}")

    # 2) reconhecimento
    try:
        artista, titulo, album, genero, capa_album = asyncio.run(
            reconhecer_musica(caminho_audio)
        )
        logger.info(f"[SHZ] {artista} — {titulo}")
    except Exception as e:
        logger.error(f"[SHZ] Reconhecimento falhou: {e}")
        return

    # 3) link YouTube
    try:
        link = buscar_youtube_link(artista, titulo) or "Não Encontrado"
        logger.info(f"[YTD] {link}")
    except Exception as e:
        link = "Não Encontrado"
        logger.error(f"[YTD] Falha ao buscar link: {e}")

    # 4) features + espectrograma
    features, _ = extrair_caracteristicas_e_spectrograma(
        caminho_audio, spec_dir, artista, titulo
    )
    if features is None or len(features) != EXPECTED_FEATURE_LENGTH:
        logger.error(
            f"[FEAT] Vetor inválido: "
            f"{None if features is None else len(features)}/{EXPECTED_FEATURE_LENGTH}"
        )
        return

    # 5) inserção no banco
    try:
        inserir_musica(nome, features, artista, titulo, album, genero, capa_album, link)
        logger.info(f"[DB] '{nome}' inserido com sucesso.")
    except Exception as e:
        logger.error(f"[DB] Falha ao inserir '{nome}': {e}")
        return

    # limpa features
    del features
    gc.collect()

    # 6) recomendações
    if not skip_recommend:
        preparar_modelos_recomendacao()
        try:
            recomendar_knn(nome, features)
        except Exception as e:
            logger.error(f"[REC] Falha ao gerar recomendações: {e}")
