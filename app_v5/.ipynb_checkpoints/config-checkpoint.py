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
#DB_TABLE_NAME = "tb_musicas"   # mantém compat com sua base
DB_TABLE_NAME = "tb_musicas"

# Diretórios
ROOT_DIR      = Path(__file__).resolve().parent
DOWNLOADS_DIR = ROOT_DIR / "downloads"
CACHE_DIR     = ROOT_DIR / "cache"
COOKIEFILE_PATH = ROOT_DIR / "cache" / "cookies.txt"  # usado APENAS ao baixar do YouTube
MUSIC_DIR = Path(os.getenv("MUSIC_DIR", ROOT_DIR.parent / "audio")).resolve()

# Metadados externos (tokens/chaves)
# → Discogs (crie em https://www.discogs.com/settings/developers)
DISCOGS_TOKEN = "QZgdlkbRWFIbKlCVztBdCIvSYNqPKsyoLaasyyTD"

# → Spotify (Client Credentials)
SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID",     "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_MARKET        = os.getenv("SPOTIFY_MARKET", "BR")

#SIMILARITY_METRIC = "euclidean"
SIMILARITY_METRIC = os.getenv("SIMILARITY_METRIC", "euclidean").lower()
HIDE_NUMERIC_SIMILARITY = (os.getenv("HIDE_NUMERIC_SIMILARITY", "true").lower() == "true")
import os

# --- KNN base (já deve existir) ---
SIMILARITY_METRIC = os.getenv("SIMILARITY_METRIC", "euclidean").lower()
HIDE_NUMERIC_SIMILARITY = (os.getenv("HIDE_NUMERIC_SIMILARITY", "true").lower() == "true")

# --- Trilhos semânticos / Filtro ---
SEM_RERANK_ENABLE   = (os.getenv("SEM_RERANK_ENABLE", "true").lower() == "true")
SEM_TOPN            = int(os.getenv("SEM_TOPN", "200"))   # quantos candidatos usar no rerank

SEM_FILTER_ENABLE   = (os.getenv("SEM_FILTER_ENABLE", "true").lower() == "true")
SEM_MIN_CANDIDATOS  = int(os.getenv("SEM_MIN_CANDIDATOS", "50"))  # se filtrar e sobrar < isto, volta sem filtro
SEM_GENRE_STRICT    = (os.getenv("SEM_GENRE_STRICT", "false").lower() == "true")  # True = obrigar gênero igual

# Pesos/limiares das penalidades
SEM_GENRE_PENALTY   = float(os.getenv("SEM_GENRE_PENALTY", "0.35")) # 0.20

SEM_BPM_TOL         = float(os.getenv("SEM_BPM_TOL", "40"))   # diferença (bpm) p/ chegar no máx
SEM_BPM_MAX_PENALTY = float(os.getenv("SEM_BPM_MAX_PENALTY", "0.20"))

SEM_YEAR_TOL        = int(os.getenv("SEM_YEAR_TOL", "15"))    # anos de tolerância
SEM_YEAR_PENALTY    = float(os.getenv("SEM_YEAR_PENALTY", "0.10"))

SEM_MODE_PENALTY    = float(os.getenv("SEM_MODE_PENALTY", "0.10"))  # maior vs menor (quando existir)

# --- (Opcional) Tweak rápido de pesos por bloco ---
# Só aplicará se a chave existir em BLOCK_WEIGHTS.
BLOCK_WEIGHTS_TWEAKS = {
    "spectral_centroid": 1.20,   # ↑ brilho/ataque (separa rock de estilos suaves)
    "rolloff":           1.15,   # ↑ energia em altas
    "flatness":          1.10,   # ↑ aspereza/textura
    "onset_rate":        1.15,   # ↑ taxa de ataques
    "chroma":            0.95,   # ↓ harmonia pura (tende a aproximar estilos diferentes)
}

# ====== Trilhos: whitelist de gêneros relacionados (evita cruzar estilos) ======
# Mapeie seu gênero "raiz" para um conjunto permitido (sinônimos/parentes)
# GENRE_WHITELISTS = {
#     "rock": {"rock", "classic rock", "hard rock", "glam metal", "metal", "pop rock"},
#     "samba": {"samba", "pagode"},
#     "mpb": {"mpb", "bossa nova", "samba"},  # ajuste se quiser separar mais
#     "arrocha": {"arrocha", "sertanejo", "piseiro"},
#     "sertanejo": {"sertanejo", "arrocha", "piseiro"},
#     "forro": {"forro", "piseiro"},
#     "funk": {"funk", "funk carioca"},
#     "rap": {"rap", "hip hop", "trap"},
#     "pop": {"pop", "dance pop"},
#     "jazz": {"jazz", "swing", "bebop"},
# }

GENRE_WHITELISTS = {
    "rock": {"rock","pop rock","classic rock","hard rock","indie rock","alternative rock","metal"},
    "pop": {"pop","dance pop","electropop","latin pop","k-pop"},
    "rap": {"rap","hip hop","hip-hop","trap","pop rap"},
    "mpb": {"mpb","bossa nova","tropicalia"},
    "samba": {"samba","pagode","samba enredo","samba de raiz"},
    "sertanejo": {"sertanejo","sertanejo universitário","arrocha","piseiro"},
    "forro": {"forró","forro","xote","baião","pisadinha"},
    "funk": {"funk carioca","baile funk","brazilian funk","funk"},
    "eletronica": {"electronic","edm","house","deep house","trance","techno","drum & bass","dubstep","dance", "synthwave"},
    "jazz": {"jazz","latin jazz","swing","bebop","cool jazz"},
    "reggae": {"reggae","roots reggae","dancehall","ska","dub"},
    "country_folk": {"country","folk","americana","bluegrass","alt-country"},
}



# Torna o filtro mais forte
SEM_GENRE_STRICT = False                # obriga pertencer ao whitelist do gênero do query (se houver)
SEM_MIN_CANDIDATOS = 40                # se sobrar menos que isso, relaxa para não zerar

# ====== Corte por distância (proteção contra “longe demais”) ======
# Remove candidatos muito distantes do query (por quantil da distância desta consulta)
SEM_DIST_Q_CUTOFF = int(os.getenv("SEM_DIST_Q_CUTOFF", "85"))  # drop d > Q90
SEM_DIST_MIN_KEEP = int(os.getenv("SEM_DIST_MIN_KEEP", "60"))  # mas nunca deixe menos que isso

# ====== Exibição: ranking-only de verdade ======
HIDE_NUMERIC_SIMILARITY = True         # garante que a UI esconda o número

try:
    # Se existir BLOCK_WEIGHTS no mesmo arquivo, aplica override seguro:
    for _k, _v in BLOCK_WEIGHTS_TWEAKS.items():
        if _k in BLOCK_WEIGHTS:
            BLOCK_WEIGHTS[_k] = _v
except NameError:
    # Se BLOCK_WEIGHTS é definido em outro módulo, ignore (sem quebrar import).
    pass






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

LOG_DIR = Path("./logs")

# Flags de debug/rigidez (podem ser sobrescritas por variáveis de ambiente)
SEM_DEBUG_ENABLE = (os.getenv("SEM_DEBUG_ENABLE", "false").lower() == "true")
SEM_STRICT_LEVEL = int(os.getenv("SEM_STRICT_LEVEL", "1"))  # 0..3


