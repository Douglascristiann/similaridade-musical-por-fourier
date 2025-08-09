
from __future__ import annotations
from pathlib import Path
import numpy as np
import librosa

from .block_scaler import load_or_fit_scaler
from ..audio.extrator_fft import extrair_features_completas
from ..storage.mysql_db import load_feature_matrix, insert_track
from ..config_app import BLOCK_SCALER_PATH, BLOCK_WEIGHTS

def cosine_knn(Xs: np.ndarray, q: np.ndarray, k: int = 10) -> tuple[np.ndarray, np.ndarray]:
    Xn = Xs / (np.linalg.norm(Xs, axis=1, keepdims=True) + 1e-12)
    qn = q / (np.linalg.norm(q) + 1e-12)
    sims = Xn @ qn
    k = min(k, len(sims))
    idx = np.argpartition(-sims, k-1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return idx, sims[idx]

def preparar_base_escalada():
    X, ids, metas = load_feature_matrix()
    scaler = load_or_fit_scaler(X, save_path=BLOCK_SCALER_PATH)
    Xs = scaler.transform_matrix(X, weights=BLOCK_WEIGHTS).astype(np.float32)
    return Xs, ids, metas, scaler

def recomendar_por_audio(audio_path: str | Path, k: int = 3, sr: int = 22050, excluir_caminho: str | None = None):
    Xs, ids, metas, scaler = preparar_base_escalada()
    y, _sr = librosa.load(str(audio_path), sr=sr, mono=True)
    q_raw = extrair_features_completas(y, _sr)
    q = scaler.transform_vector(q_raw, weights=BLOCK_WEIGHTS).astype(np.float32)
    idx, sims = cosine_knn(Xs, q, k + 5)  # pega alguns a mais para poder filtrar o próprio arquivo

    out = []
    for j, s in zip(idx, sims):
        meta = dict(metas[j])
        # Se for o mesmo caminho/nome, pula
        if excluir_caminho and (excluir_caminho in (meta.get("caminho") or "", meta.get("nome") or "")):
            continue
        meta["similaridade"] = float(s)
        out.append(meta)
        if len(out) == k:
            break
    return out

def formatar_percentual(sim: float) -> str:
    pct = max(-1.0, min(1.0, sim)) * 100.0
    return f"{pct:.1f}%"
