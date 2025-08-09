
from __future__ import annotations
from pathlib import Path
import numpy as np
import librosa

from .block_scaler import load_or_fit_scaler
from ..audio.extrator_fft import extrair_features_completas
from ..database.db import carregar_matriz, upsert_musica
from config import BLOCK_WEIGHTS, BLOCK_SCALER_PATH  # usa o SEU config.py (raiz)

def cosine_knn(Xs: np.ndarray, q: np.ndarray, k: int = 10) -> tuple[np.ndarray, np.ndarray]:
    Xn = Xs / (np.linalg.norm(Xs, axis=1, keepdims=True) + 1e-12)
    qn = q / (np.linalg.norm(q) + 1e-12)
    sims = Xn @ qn
    k = min(k, len(sims))
    idx = np.argpartition(-sims, k-1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return idx, sims[idx]

def preparar_base_escalada():
    X, ids, metas = carregar_matriz()
    scaler = load_or_fit_scaler(X, save_path=BLOCK_SCALER_PATH)
    from config import BLOCK_WEIGHTS as BW  # garante leitura atual
    Xs = scaler.transform_matrix(X, weights=BW).astype(np.float32)
    return Xs, ids, metas, scaler

def recomendar_por_audio(audio_path: str | Path, k: int = 3, sr: int = 22050, excluir_nome: str | None = None):
    Xs, ids, metas, scaler = preparar_base_escalada()
    y, _sr = librosa.load(str(audio_path), sr=sr, mono=True)
    q_raw = extrair_features_completas(y, _sr)
    from config import BLOCK_WEIGHTS as BW
    q = scaler.transform_vector(q_raw, weights=BW).astype(np.float32)
    idx, sims = cosine_knn(Xs, q, k + 5)

    out = []
    for j, s in zip(idx, sims):
        meta = dict(metas[j])
        if excluir_nome and excluir_nome == meta.get("nome"):
            continue
        meta["similaridade"] = float(s)
        out.append(meta)
        if len(out) == k:
            break
    return out

def formatar_percentual(sim: float) -> str:
    pct = max(-1.0, min(1.0, sim)) * 100.0
    return f"{pct:.1f}%"
