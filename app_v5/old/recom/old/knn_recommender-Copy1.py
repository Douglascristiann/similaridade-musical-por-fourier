# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Tuple
from pathlib import Path
import os
import numpy as np  # import no nível de módulo (não reatribuir)

from app_v5.config import BLOCK_SCALER_PATH, BLOCK_WEIGHTS
from app_v5.database.db import carregar_matriz
from app_v5.audio.extrator_fft import extrair_features_completas, get_feature_blocks


# ------------------------- Scaler por blocos ------------------------- #
def _fit_block_scaler(X: np.ndarray) -> Dict[str, Dict[str, np.ndarray]]:
    """Calcula média/desvio por bloco de features e aplica proteção para std=0."""
    blocks = get_feature_blocks()
    scaler: Dict[str, Dict[str, np.ndarray]] = {}
    for name, sl in blocks.items():
        sub = X[:, sl]
        mu = np.nanmean(sub, axis=0)
        sd = np.nanstd(sub, axis=0)
        sd[sd == 0.0] = 1.0
        scaler[name] = {"mean": mu, "std": sd}
    return scaler


def _apply_block_scaler(X: np.ndarray, scaler: Dict[str, Dict[str, np.ndarray]]) -> np.ndarray:
    """Aplica o scaler por blocos + pesos por bloco."""
    Xs = X.copy()
    blocks = get_feature_blocks()
    for name, sl in blocks.items():
        info = scaler.get(name)
        if not info:
            continue
        mu = info["mean"]
        sd = info["std"]
        Xs[:, sl] = (Xs[:, sl] - mu) / sd
        # peso por bloco
        w = float(BLOCK_WEIGHTS.get(name, 1.0))
        Xs[:, sl] *= w
    return Xs


def _save_scaler(scaler: Dict[str, Dict[str, np.ndarray]]) -> None:
    """Salva o scaler em um .npz (compactado)."""
    BLOCK_SCALER_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        BLOCK_SCALER_PATH,
        **{f"{k}_mean": v["mean"] for k, v in scaler.items()},
        **{f"{k}_std": v["std"] for k, v in scaler.items()},
    )


def _load_scaler() -> Dict[str, Dict[str, np.ndarray]] | None:
    """Carrega o scaler do .npz, se existir."""
    if not Path(BLOCK_SCALER_PATH).exists():
        return None
    data = np.load(BLOCK_SCALER_PATH, allow_pickle=False)
    scaler: Dict[str, Dict[str, np.ndarray]] = {}
    for name in get_feature_blocks().keys():
        mkey, skey = f"{name}_mean", f"{name}_std"
        if mkey in data and skey in data:
            scaler[name] = {"mean": data[mkey], "std": data[skey]}
    return scaler


def preparar_base_escalada() -> Tuple[np.ndarray, List[int], List[Dict[str, Any]], Dict[str, Dict[str, np.ndarray]]]:
    """
    Carrega matriz do banco, ajusta (ou recarrega) scaler por blocos e devolve (Xs, ids, metas, scaler).
    Nunca reatribui 'np' localmente (evita UnboundLocalError).
    """
    X, ids, metas = carregar_matriz()
    if getattr(X, "shape", (0, 0))[0] == 0:
        return X, ids, metas, {}
    scaler = _load_scaler()
    if scaler is None:
        scaler = _fit_block_scaler(X)
        _save_scaler(scaler)
    Xs = _apply_block_scaler(X, scaler)
    return Xs, ids, metas, scaler


# ----------------------- Similaridade do cosseno ---------------------- #
def _cosine_sim_matrix(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Versão vetorizada com 'np' global (mantida para compatibilidade)."""
    A_norm = np.linalg.norm(A, axis=1, keepdims=True) + 1e-9
    b_norm = np.linalg.norm(b) + 1e-9
    return (A @ b) / (A_norm[:, 0] * b_norm)


def _cosine_sim_local(x_mat, q_vec) -> "np.ndarray":
    """
    Similaridade do cosseno sem depender do símbolo global 'np'.
    Usa um alias local 'np' para blindar contra qualquer uso acidental de 'np' como variável local.
    """
    import numpy as np  # alias local, nunca conflita com 'np'
    X = np.asarray(x_mat, dtype=float)
    q = np.asarray(q_vec, dtype=float).ravel()
    denom = (np.linalg.norm(X, axis=1) + 1e-12) * (np.linalg.norm(q) + 1e-12)
    return (X @ q) / denom


# ------------------------- Distância Euclidiana ----------------------- #
def _euclidean_dist_local(x_mat, q_vec) -> "np.ndarray":
    """
    Distância euclidiana vetorizada (menor = mais similar).
    Faz alinhamento conservador de dimensão se necessário.
    """
    import numpy as np
    X = np.asarray(x_mat, dtype=float)
    q = np.asarray(q_vec, dtype=float).ravel()
    if X.ndim != 2:
        X = np.atleast_2d(X)
    n = min(X.shape[1], q.shape[0])
    X = X[:, :n]
    q = q[:n]
    return np.linalg.norm(X - q, axis=1)


# -------------------------- Recomendação KNN -------------------------- #
def recomendar_por_audio(
    path_audio,
    k: int = 3,
    sr: int = 22050,
    excluir_nome: str | None = None,
    metric: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Gera recomendações a partir de um arquivo de áudio local.

    Blindagens:
      - Valida caminho (não tenta abrir diretório ".")
      - Evita qualquer dependência de 'np' local usando alias 'np' dentro da função
      - Similaridade por cosseno (padrão) OU por euclidiana (configurável)
        * cosine: maior = melhor
        * euclidean: menor distância => escore 1/(1+dist) (maior = melhor), mantendo o campo 'similaridade'
    """
    import librosa

    p = Path(path_audio).expanduser()
    # evita abrir diretório "." ou caminhos inválidos
    if str(p) in (".", "./") or p.is_dir() or (not p.exists()):
        return []

    # Base escalada
    Xs, ids, metas, scaler = preparar_base_escalada()
    n = getattr(Xs, "shape", (0,))[0] if Xs is not None else 0
    if n == 0:
        return []

    # Features do arquivo de consulta
    try:
        y, _sr = librosa.load(str(p), sr=sr, mono=True)
    except Exception:
        return []

    q = extrair_features_completas(y, _sr).reshape(1, -1)

    # Aplica scaler por blocos + pesos (alias local)
    if scaler:
        blocks = get_feature_blocks()
        for name, sl in blocks.items():
            if name in scaler:
                mu = np.asarray(scaler[name]["mean"], dtype=float)
                sd = np.asarray(scaler[name]["std"], dtype=float)
                q[:, sl] = (q[:, sl] - mu) / (sd + 1e-12)
                w = float(BLOCK_WEIGHTS.get(name, 1.0))
                q[:, sl] *= w

    # Escolha da métrica (padrão = cosine; pode sobrescrever por parâmetro ou env)
    chosen = (metric or os.getenv("SIMILARITY_METRIC") or "cosine").lower()

    if chosen == "euclidean":
        dists = _euclidean_dist_local(Xs, q[0])          # menor = melhor
        scores = 1.0 / (1.0 + dists)                     # normaliza para 0..1 (maior = melhor)
        order = np.argsort(-scores)
    else:
        # cosine (comportamento atual)
        scores = _cosine_sim_local(Xs, q[0])             # maior = melhor
        order = np.argsort(-scores)

    # Monta top-k
    recs: List[Dict[str, Any]] = []
    for idx in order:
        i = int(idx)
        meta = metas[i] or {}
        if excluir_nome and meta.get("nome") == excluir_nome:
            continue
        recs.append({
            "id": ids[i],
            "titulo": meta.get("titulo") or meta.get("nome"),
            "artista": meta.get("artista"),
            "similaridade": float(scores[i]),  # campo mantido
            # mantém o 'caminho' compatível (Spotify > YouTube), mas agora leva os dois campos:
            "caminho": (meta.get("link_spotify") or meta.get("spotify") or meta.get("caminho")
                        or meta.get("link_youtube") or meta.get("youtube")),
            "spotify": (meta.get("spotify") or meta.get("link_spotify")),
            "youtube": (meta.get("youtube") or meta.get("link_youtube")),
        })
        if len(recs) >= k:
            break

    return recs
