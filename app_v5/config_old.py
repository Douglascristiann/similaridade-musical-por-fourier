# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import os

# Identidade
APP_NAME    = "FourierMatch"
APP_VERSION = "v4.1.0-modular"

# === DB (ajuste se necessário) ===
DB_CONFIG = {
    "user":     "root",
    "password": "managerffti8p68",
    "host":     "db",     # ou "localhost"
    "port":     3306,
    "database": "dbmusicadata",
}
DB_TABLE_NAME = "tb_musicas"   # mantém compat com sua base

# Diretórios
ROOT_DIR      = Path(__file__).resolve().parent
DOWNLOADS_DIR = ROOT_DIR / "downloads"
CACHE_DIR     = ROOT_DIR / "cache"
COOKIEFILE_PATH = ROOT_DIR / "cache" / "cookies.txt"  # usado APENAS ao baixar do YouTube

# Metadados externos (tokens/chaves)
# → Discogs (crie em https://www.discogs.com/settings/developers)
DISCOGS_TOKEN = "QZgdlkbRWFIbKlCVztBdCIvSYNqPKsyoLaasyyTD"

# → Spotify (Client Credentials)
SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID",     "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_MARKET        = os.getenv("SPOTIFY_MARKET", "BR")

# Regras de metadado
STRICT_METADATA          = True   # exige artista+título confiáveis
INSERT_ON_LOW_CONFIDENCE = False  # se True, grava usando hints quando não for “confiável”

# Recomendações
BLOCK_WEIGHTS = {
    # Timbre
    "mfcc": 0.35, "mfcc_delta": 0.35, "mfcc_delta2": 0.35,
    # Harmonia
    "chroma": 0.45, "tonnetz": 0.45,
    # Tonalidade global
    "spectral_contrast": 0.35,
    # Ritmo/percussivo
    "percussive": 0.20, "tempo": 0.20,
}

BLOCK_SCALER_PATH = ROOT_DIR / "recom" / "block_scaler.npz"

# Comprimento esperado do vetor final (garantido por extrator_fft)
EXPECTED_FEATURE_LENGTH = 161

# Backfill de YouTube (sem cookies) — limites seguros para não tomar 429
YT_BACKFILL_LIMIT      = 5     # máximo de candidatos por busca
YT_BACKFILL_RETRIES    = 2     # troca client + backoff leve
YT_BACKFILL_THROTTLE_S = 1.2   # intervalo mínimo entre buscas

# Limpesa pós-processamento
AUTO_DELETE_DOWNLOADED = True  # remove .mp3 baixado após extrair features
