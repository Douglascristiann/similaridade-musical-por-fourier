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
    os.makedirs(pasta_out, exist_ok=True)
    nome_base = os.path.splitext(os.path.basename(path))[0]
    spec_path = os.path.join(pasta_out, f"{nome_base}.png")
    gerar_spectrograma(y, sr, spec_path, artista, titulo)
    logger.info(f"[SPEC] Spectrograma salvo em: {spec_path}")

    # libera áudio da memória
    del y, sr
    gc.collect()
    return features, spec_path

def processar_audio_local(caminho_audio, skip_recommend=False):
    nome = os.path.basename(caminho_audio)

    # 1) Checa existência no DB antes de tudo
    if musica_existe(nome):
        logger.info(f"[SKIP] '{nome}' já cadastrado. Pulando.")
        return

    logger.info(f"[PROC] Iniciando: {nome}")

    # 2) Reconhecimento unificado (Discogs → Shazam → AudD → Tags)
    try:
        artista, titulo, album, genero, capa = asyncio.run(
            reconhecer_musica(caminho_audio)
        )
        logger.info(f"[META] {artista} — {titulo} | Álbum: {album} | Gênero: {genero}")
    except Exception as e:
        logger.error(f"[META] Falha no reconhecimento: {e}")
        return

    # 3) Busca link YouTube
    try:
        link = buscar_youtube_link(artista, titulo) or "Não Encontrado"
        logger.info(f"[YTD] {link}")
    except Exception as e:
        link = "Não Encontrado"
        logger.error(f"[YTD] Falha ao buscar link: {e}")

    # 4) Extrai features + gera espectrograma
    pasta_spec = os.path.join(AUDIO_FOLDER, 'spectrogramas')
    features, _ = extrair_caracteristicas_e_spectrograma(
        caminho_audio, pasta_spec, artista, titulo
    )
    if features is None or len(features) != EXPECTED_FEATURE_LENGTH:
        logger.error(f"[FEAT] Vetor inválido: "
                     f"{None if features is None else len(features)}/{EXPECTED_FEATURE_LENGTH}")
        return

    # 5) Insere no banco
    try:
        inserir_musica(nome, features, artista, titulo, album, genero, capa, link)
        logger.info(f"[DB] '{nome}' inserido com sucesso.")
    except Exception as e:
        logger.error(f"[DB] Falha ao inserir '{nome}': {e}")
        return

    # 6) Gera recomendações (usa o vetor antes de liberar)
    if not skip_recommend:
        preparar_modelos_recomendacao()
        try:
            recomendar_knn(nome, features)
        except Exception as e:
            logger.error(f"[REC] Falha nas recomendações: {e}")

    # 7) Limpeza final de memória
    del features
    gc.collect()
