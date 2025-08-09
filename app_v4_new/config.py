# app_v4_new/config.py — configuração central (agora DENTRO do pacote)

from pathlib import Path as _Path
import os

# ===== Branding =====
APP_NAME = "FourierMatch"
APP_VERSION = "4.0.1-internal-config"

# ===== MySQL =====
DB_CONFIG = {
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "managerffti8p68"),
    "host":     os.getenv("DB_HOST", "db"),   # se não for Docker, troque para "localhost"
    "port":     int(os.getenv("DB_PORT", "3306")),
    "database": os.getenv("DB_NAME", "dbmusicadata"),
}

# ===== Vetor de features =====
# O extrator desta versão gera 157 dimensões; mantenha 157 para 1:1 com a tabela nova.
EXPECTED_FEATURE_LENGTH = int(os.getenv("EXPECTED_FEATURE_LENGTH", "157"))

# ===== Pesos por bloco (padronização por bloco + KNN) =====
BLOCK_WEIGHTS: dict[str, float] = {
    # Timbre
    "mfcc": 0.35, "mfcc_delta": 0.35, "mfcc_delta2": 0.35, "spectral_contrast": 0.35,
    # Harmonia
    "chroma_h_ci": 0.45, "tiv6": 0.45, "tonnetz_h": 0.45,
    # Ritmo / espectrais percussivos
    "zcr_p": 0.20, "centroid_p": 0.20, "bandwidth_p": 0.20, "rolloff_p": 0.20,
    "tempo_bpm": 0.20, "tempo_var": 0.20,
}

# Onde salvar/carregar o scaler (dentro do pacote)
BLOCK_SCALER_PATH = _Path(__file__).resolve().parent / "recom" / "block_scaler.npz"

# ===== YouTube (cookies + downloads) =====
COOKIEFILE_PATH = _Path(os.getenv("FM_COOKIES_PATH", "/home/jovyan/work/cache/cookies/cookies.txt"))
DOWNLOADS_DIR   = _Path(os.getenv("FM_DOWNLOADS_DIR", _Path.cwd() / "downloads"))

# ===== APIs (opcional) =====
AUDD_TOKEN    = os.getenv("AUDD_TOKEN", "")
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN", "")

# Pasta de áudio local (opcional)
AUDIO_FOLDER = os.getenv("AUDIO_FOLDER", "/home/jovyan/work/audio")

# === Controle de limpeza automática dos downloads ===
AUTO_DELETE_DOWNLOADED = True  # apaga .mp3 e .info.json baixados após processar

# === Hiperparâmetros da recomendação robusta ===
MIN_N_FOR_SCALER = int(os.getenv("FM_MIN_N_FOR_SCALER", "20"))  # abaixo disso: centr. por bloco + L2
SIM_CALIB_SAMPLE_PAIRS = int(os.getenv("FM_SIM_CAL_SAMPLES", "2000"))  # amostras p/ calibrar distribuição
TEMPO_PENALTY_SIGMA = float(os.getenv("FM_TEMPO_SIGMA", "0.22"))       # quão forte penaliza diferença de BPM

