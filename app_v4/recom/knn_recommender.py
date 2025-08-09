
from __future__ import annotations
from pathlib import Path
import numpy as np
import librosa

from .block_scaler import load_or_fit_scaler
from ..audio.extrator_fft import extrair_features_completas
from ..storage.db_utils import load_feature_matrix, default_db_path
from ..config import BLOCK_SCALER_PATH, BLOCK_WEIGHTS

def cosine_knn(Xs: np.ndarray, q: np.ndarray, k: int = 10) -> tuple[np.ndarray, np.ndarray]:
    Xn = Xs / (np.linalg.norm(Xs, axis=1, keepdims=True) + 1e-12)
    qn = q / (np.linalg.norm(q) + 1e-12)
    sims = Xn @ qn
    k = min(k, len(sims))
    idx = np.argpartition(-sims, k-1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return idx, sims[idx]

def preparar_base_escalada(db_path: str | Path | None = None):
    if db_path is None:
        db_path = default_db_path()
    X, ids, metas = load_feature_matrix(db_path)
    scaler = load_or_fit_scaler(X, save_path=BLOCK_SCALER_PATH)
    from ..config import BLOCK_WEIGHTS
    Xs = scaler.transform_matrix(X, weights=BLOCK_WEIGHTS).astype(np.float32)
    return Xs, ids, metas, scaler

def recomendar_por_id(db_path: str | Path, song_id: int, k: int = 10) -> list[dict]:
    Xs, ids, metas, scaler = preparar_base_escalada(db_path)
    id2idx = {i: j for j, i in enumerate(ids)}
    if song_id not in id2idx:
        raise KeyError(f"id {song_id} not found in DB.")
    q = Xs[id2idx[song_id]]
    idx, sims = cosine_knn(Xs, q, k+1)
    out = []
    for j, s in zip(idx, sims):
        if ids[j] == song_id:
            continue
        meta = dict(metas[j]); meta["similaridade"] = float(s); meta["index"] = int(j)
        out.append(meta)
        if len(out) == k:
            break
    return out

def recomendar_por_audio(db_path: str | Path, audio_path: str | Path, k: int = 10, sr: int = 22050) -> list[dict]:
    Xs, ids, metas, scaler = preparar_base_escalada(db_path)
    y, _sr = librosa.load(str(audio_path), sr=sr, mono=True)
    q_raw = extrair_features_completas(y, _sr)
    from ..config import BLOCK_WEIGHTS
    q = scaler.transform_vector(q_raw, weights=BLOCK_WEIGHTS).astype(np.float32)
    idx, sims = cosine_knn(Xs, q, k)
    return [dict(metas[j], similaridade=float(s), index=int(j)) for j, s in zip(idx, sims)]
