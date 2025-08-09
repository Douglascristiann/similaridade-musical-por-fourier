
from __future__ import annotations
from pathlib import Path as _Path
import os

# ===== Branding =====
APP_NAME = "FourierMatch"
APP_VERSION = "2.0.0-pt-mysql"

# ===== Universidade / Autores =====
ORG_TITLE = "Universidade Paulista — Curso de Sistemas de Informação"
CREATORS = [
    "Douglas Cristian da Cunha (N7970A0)",
    "Fábio Silva Matos Filho (N8947E9)",
]
TCC_TITLE = "Uma Abordagem Baseada em Análise Espectral para Recomendação Musical: Explorando a Transformada de Fourier como Alternativa aos Métodos Convencionais"

# ===== Pesos por bloco (aplicados ANTES do KNN, após padronização por bloco) =====
BLOCK_WEIGHTS: dict[str, float] = {
    # Timbre
    "mfcc": 0.35, "mfcc_delta": 0.35, "mfcc_delta2": 0.35, "spectral_contrast": 0.35,
    # Harmonia
    "chroma_h_ci": 0.45, "tiv6": 0.45, "tonnetz_h": 0.45,
    # Ritmo / espectrais percussivos
    "zcr_p": 0.20, "centroid_p": 0.20, "bandwidth_p": 0.20, "rolloff_p": 0.20,
    "tempo_bpm": 0.20, "tempo_var": 0.20,
}

# ===== Caminhos =====
BLOCK_SCALER_PATH = _Path(__file__).resolve().parent / "recom" / "block_scaler.npz"
DOWNLOADS_DIR = _Path(os.getenv("FM_DOWNLOADS_DIR", _Path.cwd() / "downloads"))

# ===== YouTube cookies (fixo; pode sobrescrever por env FM_COOKIES_PATH) =====
COOKIEFILE_PATH = _Path(os.getenv("FM_COOKIES_PATH", "/home/jovyan/work/cache/cookies/cookies.txt"))
