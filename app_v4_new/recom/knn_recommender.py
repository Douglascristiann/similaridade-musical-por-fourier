from __future__ import annotations
from pathlib import Path
import numpy as np
import librosa

from .block_scaler import load_or_fit_scaler
from ..audio.extrator_fft import extrair_features_completas
from ..database.db import carregar_matriz
from app_v4_new.config import BLOCK_WEIGHTS, BLOCK_SCALER_PATH
from ..audio.feature_schema import load_schema, SCHEMA_PATH

_MIN_N_FOR_SCALER = 12  # abaixo disso, usar L2 por bloco (mais estável com base pequena)

def _schema_slices() -> tuple[list[str], dict[str, slice]]:
    sch = load_schema(SCHEMA_PATH)
    order = list(sch["order"])
    lengths = {k: int(v) for k, v in sch["lengths"].items()}
    sls = {}
    start = 0
    for name in order:
        L = lengths[name]
        sls[name] = slice(start, start + L)
        start += L
    return order, sls

def _blockwise_l2(X: np.ndarray, weights: dict[str, float]) -> np.ndarray:
    order, sls = _schema_slices()
    Xn = X.copy().astype(np.float32, copy=False)
    for name in order:
        sl = sls[name]
        B = Xn[:, sl]
        nrm = np.linalg.norm(B, axis=1, keepdims=True) + 1e-12
        B /= nrm
        if name in weights:
            B *= float(weights[name])
        Xn[:, sl] = B
    return Xn

def _blockwise_l2_vec(x: np.ndarray, weights: dict[str, float]) -> np.ndarray:
    order, sls = _schema_slices()
    xn = x.copy().astype(np.float32, copy=False)
    for name in order:
        sl = sls[name]
        b = xn[sl]
        nrm = (np.linalg.norm(b) + 1e-12)
        b = b / nrm
        if name in weights:
            b = b * float(weights[name])
        xn[sl] = b
    return xn

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
    if X.shape[0] < _MIN_N_FOR_SCALER:
        # Base pequena: L2 por bloco + pesos
        Xs = _blockwise_l2(X, BLOCK_WEIGHTS)
        scaler = None
        return Xs, ids, metas, scaler
    # Base razoável: z-score por bloco + pesos
    scaler = load_or_fit_scaler(X, save_path=BLOCK_SCALER_PATH)
    Xs = scaler.transform_matrix(X, weights=BLOCK_WEIGHTS).astype(np.float32)
    return Xs, ids, metas, scaler

def recomendar_por_audio(audio_path: str | Path, k: int = 3, sr: int = 22050, excluir_nome: str | None = None):
    Xs, ids, metas, scaler = preparar_base_escalada()
    y, _sr = librosa.load(str(audio_path), sr=sr, mono=True)
    q_raw = extrair_features_completas(y, _sr)
    if scaler is None:
        q = _blockwise_l2_vec(q_raw, BLOCK_WEIGHTS)
    else:
        q = scaler.transform_vector(q_raw, weights=BLOCK_WEIGHTS).astype(np.float32)
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
    """Converte similaridade [-1..1] em string de percentual, ex: 0.87 -> '87.0%'."""
    pct = max(-1.0, min(1.0, float(sim))) * 100.0
    return f"{pct:.1f}%"
