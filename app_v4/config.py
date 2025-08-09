
from __future__ import annotations
from pathlib import Path as _Path
import os

# ==== Nome e versão do produto ====
APP_NAME = "FourierMatch"
APP_VERSION = "1.2.0-pt"

# ==== Pesos por bloco (aplicados ANTES do KNN) ====
BLOCK_WEIGHTS: dict[str, float] = {
    # Timbre
    "mfcc": 0.35, "mfcc_delta": 0.35, "mfcc_delta2": 0.35, "spectral_contrast": 0.35,
    # Harmonia
    "chroma_h_ci": 0.45, "tiv6": 0.45, "tonnetz_h": 0.45,
    # Ritmo / espectrais percussivos
    "zcr_p": 0.20, "centroid_p": 0.20, "bandwidth_p": 0.20, "rolloff_p": 0.20,
    "tempo_bpm": 0.20, "tempo_var": 0.20,
}

# Onde persistir o scaler
BLOCK_SCALER_PATH = _Path(__file__).resolve().parent / "recom" / "block_scaler.npz"

# Expor tamanho esperado do vetor (após 1º run)
try:
    from .audio.feature_schema import load_schema, SCHEMA_PATH as _SCHEMA_PATH  # type: ignore
    _schema = load_schema(_SCHEMA_PATH)
    EXPECTED_FEATURE_LENGTH = int(_schema["total"]) if _schema else None
except Exception:
    EXPECTED_FEATURE_LENGTH = None

# ==== Tokens de API (via ambiente/.env) ====
# AUDD_API_TOKEN=...
# DISCOGS_TOKEN=...
# SHAZAM_ENABLE=true    # requer shazamio
AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN", "")
DISCOGS_TOKEN  = os.getenv("DISCOGS_TOKEN", "")
SHAZAM_ENABLE  = os.getenv("SHAZAM_ENABLE", "true").lower() in {"1","true","yes","on"}
