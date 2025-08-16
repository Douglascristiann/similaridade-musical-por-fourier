# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Tuple
import numpy as np
from pathlib import Path

from app_v5.config import BLOCK_SCALER_PATH, BLOCK_WEIGHTS
from app_v5.database.db import carregar_matriz
from app_v5.audio.extrator_fft import extrair_features_completas, get_feature_blocks

def _fit_block_scaler(X: np.ndarray) -> Dict[str, Dict[str, np.ndarray]]:
    blocks = get_feature_blocks()
    scaler = {}
    for name, sl in blocks.items():
        sub = X[:, sl]
        mu = np.nanmean(sub, axis=0)
        sd = np.nanstd(sub, axis=0)
        sd[sd == 0.0] = 1.0
        scaler[name] = {"mean": mu, "std": sd}
    return scaler

def _apply_block_scaler(X: np.ndarray, scaler: Dict[str, Dict[str, np.ndarray]]) -> np.ndarray:
    Xs = X.copy()
    blocks = get_feature_blocks()
    for name, sl in blocks.items():
        if name not in scaler: 
            continue
        mu = scaler[name]["mean"]; sd = scaler[name]["std"]
        Xs[:, sl] = (Xs[:, sl] - mu) / sd
        # peso por bloco
        w = float(BLOCK_WEIGHTS.get(name, 1.0))
        Xs[:, sl] *= w
    return Xs

def _save_scaler(scaler: Dict[str, Dict[str, np.ndarray]]):
    BLOCK_SCALER_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        BLOCK_SCALER_PATH,
        **{f"{k}_mean": v["mean"] for k, v in scaler.items()},
        **{f"{k}_std":  v["std"]  for k, v in scaler.items()},
    )

def _load_scaler() -> Dict[str, Dict[str, np.ndarray]] | None:
    if not Path(BLOCK_SCALER_PATH).exists():
        return None
    data = np.load(BLOCK_SCALER_PATH, allow_pickle=False)
    scaler = {}
    for name in get_feature_blocks().keys():
        mkey, skey = f"{name}_mean", f"{name}_std"
        if mkey in data and skey in data:
            scaler[name] = {"mean": data[mkey], "std": data[skey]}
    return scaler

def preparar_base_escalada() -> Tuple[np.ndarray, List[int], List[Dict[str,Any]], Dict]:
    X, ids, metas = carregar_matriz()
    if X.shape[0] == 0:
        return X, ids, metas, {}
    scaler = _load_scaler()
    if scaler is None:
        scaler = _fit_block_scaler(X)
        _save_scaler(scaler)
    Xs = _apply_block_scaler(X, scaler)
    return Xs, ids, metas, scaler

def _cosine_sim_matrix(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    # normaliza
    A_norm = np.linalg.norm(A, axis=1, keepdims=True) + 1e-9
    b_norm = np.linalg.norm(b) + 1e-9
    sims = (A @ b) / (A_norm[:, 0] * b_norm)
    return sims

def recomendar_por_audio(path_audio, k: int = 3, sr: int = 22050, excluir_nome: str | None = None) -> List[Dict[str, Any]]:
    """
    Gera recomendações a partir de um arquivo de áudio local.
    Correções:
      - Valida caminho (não tenta abrir diretório ".")
      - Retorna [] silenciosamente se o arquivo não existir
    """
    from pathlib import Path
    import librosa
    import numpy as np

    p = Path(path_audio).expanduser()
    if str(p) in (".", "./") or (not p.exists()) or p.is_dir():
        # nada a recomendar – evita erro 'IsADirectoryError: "."'
        return []

    # Base escalada (carrega matriz do banco e aplica scaler por blocos)
    Xs, ids, metas, scaler = preparar_base_escalada()
    if Xs is None or getattr(Xs, "shape", (0,))[0] == 0:
        return []

    # Extrai features do arquivo de consulta
    try:
        y, _sr = librosa.load(str(p), sr=sr, mono=True)
    except Exception:
        # Caso raro: tenta backend alternativo do librosa (audioread) já é usado automaticamente;
        # se falhar, retornamos vazio para não quebrar fluxo do menu.
        return []

    q = extrair_features_completas(y, _sr).reshape(1, -1)

    # Aplica scaler por blocos + pesos
    if scaler:
        blocks = get_feature_blocks()
        for name, sl in blocks.items():
            if name in scaler:
                mu = scaler[name]["mean"]
                sd = scaler[name]["std"]
                q[:, sl] = (q[:, sl] - mu) / sd
                w = float(BLOCK_WEIGHTS.get(name, 1.0))
                q[:, sl] *= w

    # Similaridade por cosseno
    sims = _cosine_sim_matrix(Xs, q[0])
    order = np.argsort(-sims)

    # Monta top-k
    recs: List[Dict[str, Any]] = []
    for idx in order:
        meta = metas[idx]
        if excluir_nome and meta.get("nome") == excluir_nome:
            continue
        recs.append({
            "id": ids[idx],
            "titulo": meta.get("titulo"),
            "artista": meta.get("artista"),
            "caminho": meta.get("caminho"),
            "similaridade": float(sims[idx]),
        })
        if len(recs) >= k:
            break
    return recs
