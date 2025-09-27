# app_v5/recom/knn_recommender.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
import os, re, json, datetime
import numpy as np
import logging

# =========================
# Imports do Projeto
# =========================
from app_v5.recom.penalties import PenaltyEngine, GenrePenalty
from app_v5.database.db import carregar_matriz
from app_v5.audio.extrator_fft import extrair_features_completas, get_feature_blocks

# =========================
# CONFIG (com fallbacks seguros)
# =========================
try:
    from app_v5.config import (
        BLOCK_SCALER_PATH, BLOCK_WEIGHTS, SIMILARITY_METRIC, HIDE_NUMERIC_SIMILARITY,
        SEM_TOPN, LOG_DIR, SEM_DEBUG_ENABLE, SEM_STRICT_LEVEL, BLOCK_WEIGHTS_TWEAKS
    )
except Exception:
    BLOCK_SCALER_PATH = Path("./.cache/block_scaler.npz")
    BLOCK_WEIGHTS = {}
    SIMILARITY_METRIC = "euclidean"
    #SIMILARITY_METRIC = "cosseno"
    HIDE_NUMERIC_SIMILARITY = True
    SEM_TOPN = 200
    LOG_DIR = Path("./logs")
    SEM_DEBUG_ENABLE = True
    SEM_STRICT_LEVEL = 2
    BLOCK_WEIGHTS_TWEAKS = {}

# =========================
# METADATA (Importação dinâmica)
# =========================
get_query_metadata = None
try:
    from app_v5.services.metadata import get_query_metadata_live as get_query_metadata
except ImportError:
    pass

# =========================
# SCALER POR BLOCOS
# =========================
def _fit_block_scaler(X: np.ndarray) -> Dict[str, Dict[str, np.ndarray]]:
    blocks = get_feature_blocks()
    scaler: Dict[str, Dict[str, np.ndarray]] = {}
    for name, sl in blocks.items():
        sub = X[:, sl]
        mu = np.nanmean(sub, axis=0)
        sd = np.nanstd(sub, axis=0)
        sd[sd == 0.0] = 1.0
        scaler[name] = {"mean": mu, "std": sd}
    return scaler

def _apply_block_weight(name: str) -> float:
    base = float(BLOCK_WEIGHTS.get(name, 1.0))
    if isinstance(BLOCK_WEIGHTS_TWEAKS, dict) and name in BLOCK_WEIGHTS_TWEAKS:
        try:
            return float(BLOCK_WEIGHTS_TWEAKS[name])
        except (ValueError, TypeError):
            return base
    return base

def _apply_block_scaler(X: np.ndarray, scaler: Dict[str, Dict[str, np.ndarray]]) -> np.ndarray:
    Xs = X.copy()
    blocks = get_feature_blocks()
    for name, sl in blocks.items():
        if name in scaler:
            mu, sd = scaler[name]["mean"], scaler[name]["std"]
            Xs[:, sl] = (Xs[:, sl] - mu) / (sd + 1e-9)
            Xs[:, sl] *= _apply_block_weight(name)
    return Xs

def _save_scaler(scaler: Dict[str, Dict[str, np.ndarray]]) -> None:
    BLOCK_SCALER_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        BLOCK_SCALER_PATH,
        **{f"{k}_mean": v["mean"] for k, v in scaler.items()},
        **{f"{k}_std": v["std"] for k, v in scaler.items()},
    )

def _load_scaler() -> Optional[Dict[str, Dict[str, np.ndarray]]]:
    if not BLOCK_SCALER_PATH.exists(): return None
    try:
        data = np.load(BLOCK_SCALER_PATH, allow_pickle=False)
        scaler: Dict[str, Dict[str, np.ndarray]] = {}
        for name in get_feature_blocks().keys():
            mkey, skey = f"{name}_mean", f"{name}_std"
            if mkey in data and skey in data:
                scaler[name] = {"mean": data[mkey], "std": data[skey]}
        return scaler
    except Exception:
        return None

def preparar_base_escalada() -> Tuple[np.ndarray, List[int], List[Dict[str, Any]], Dict[str, Dict[str, np.ndarray]]]:
    X, ids, metas = carregar_matriz()
    if not metas:
        return np.array([]), [], [], {}
    
    scaler = _load_scaler()
    if scaler is None:
        scaler = _fit_block_scaler(X)
        _save_scaler(scaler)
        
    Xs = _apply_block_scaler(X, scaler)
    return Xs, ids, metas, scaler

# =========================
# FUNÇÕES DE DISTÂNCIA
# =========================
def _cosine_sim_local(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # Garante que 'b' seja 2D para a transposição
    if b.ndim == 1:
        b = b.reshape(1, -1)
    # Normaliza os vetores para evitar problemas com magnitude
    norm_a = np.linalg.norm(a, axis=1, keepdims=True)
    norm_b = np.linalg.norm(b, axis=1, keepdims=True)
    # Adiciona epsilon para evitar divisão por zero
    return np.dot(a / (norm_a + 1e-9), (b / (norm_b + 1e-9)).T).flatten()


def _euclidean_dist_local(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.linalg.norm(a - b, axis=1)

# =========================
# FUNÇÕES AUXILIARES DE METADADOS
# =========================
def _get_first(v: Any) -> Optional[str]:
    if v is None: return None
    if isinstance(v, (list, tuple)):
        return str(v[0]) if v else None
    return str(v)

def _norm_text(s: Optional[str]) -> Optional[str]:
    return s.strip().lower() if s else None

def _extract_candidate_semantics(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai e normaliza metadados relevantes de um candidato."""
    return {
        "genero": meta.get("genero"),
        "artista": _norm_text(_get_first(meta.get("artista"))),
    }

def _bootstrap_query_semantics_from_candidates(
    order: np.ndarray, metas: List[Dict[str, Any]], topn: int = 5
) -> Dict[str, Any]:
    """Cria uma semântica de query baseada nos vizinhos mais próximos."""
    genres = []
    for i in order[:topn]:
        meta = metas[i]
        g = meta.get("genero")
        if g:
            # Se o gênero for uma lista ou tupla, estende a lista
            if isinstance(g, (list, tuple)):
                genres.extend(g)
            else:
                genres.append(g)
    
    # Pega o gênero mais comum entre os top N vizinhos
    most_common_genre = max(set(genres), key=genres.count) if genres else "unknown"
    
    return {"genero": most_common_genre}

def _canonical_track_key(meta: Dict[str, Any], db_id: int) -> str:
    """Cria uma chave única para uma faixa para evitar duplicatas."""
    artist = _norm_text(str(meta.get("artista", ""))) or ""
    title = _norm_text(str(meta.get("titulo", ""))) or ""
    if artist and title:
        return f"{artist}|{title}"
    return f"id|{db_id}"

# =========================
# LÓGICA DE RECOMENDAÇÃO PRINCIPAL
# =========================
def build_penalty_engine(strict_level: int) -> PenaltyEngine:
    """Constrói o motor de penalidades com base no nível de rigidez."""
    weight = 0.5 + (strict_level * 0.25)
    penalties = [
        GenrePenalty(strict_level=strict_level, weight=weight)
    ]
    return PenaltyEngine(penalties, shadow_mode=False)

def recomendar_por_audio(
    path_audio: str,
    k: int = 3,
    sr: int = 22050,
    excluir_nome: str | None = None,
    metric: str | None = None,
    query_meta: Optional[Dict[str,Any]] = None,
    strict_level: Optional[int] = None,
    debug: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    import librosa
    
    lvl = SEM_STRICT_LEVEL if strict_level is None else int(strict_level)
    dbg = SEM_DEBUG_ENABLE if debug is None else bool(debug)
    
    p = Path(path_audio).expanduser()
    if not p.exists() or p.is_dir(): return []

    Xs, ids, metas, scaler = preparar_base_escalada()
    if not metas: return []

    y, _sr = librosa.load(str(p), sr=sr, mono=True)
    q = extrair_features_completas(y, _sr).reshape(1, -1)
    
    if scaler: q = _apply_block_scaler(q, scaler)

    chosen_metric = (metric or SIMILARITY_METRIC).lower()
    dists = np.zeros(len(Xs), dtype=float)

    if chosen_metric == "euclidean":
        dists = _euclidean_dist_local(Xs, q)
        base_scores = 1.0 / (1.0 + dists)
    else: # cosine
        base_scores = _cosine_sim_local(Xs, q)
        dists = 1.0 - base_scores
    
    order = np.argsort(-base_scores)
    
    qsem = _extract_candidate_semantics(query_meta or {})
    if not qsem.get("genero"):
        qsem = _bootstrap_query_semantics_from_candidates(order, metas, topn=10)

    engine = build_penalty_engine(lvl)
    final_scores = {}
    diag_map = {} if dbg else None

    for i in range(len(Xs)):
        cand_meta = metas[i]
        penalty, reasons = engine.apply(qsem, cand_meta)
        final_score = base_scores[i] - penalty
        final_scores[i] = final_score

        if dbg:
            diag_map[i] = {
                "distance": float(dists[i]),
                "base_score": float(base_scores[i]), 
                "penalty_total": float(penalty),
                "final_like": float(final_score), 
                "reasons": reasons,
                "query_sem": qsem, 
                "cand_sem": _extract_candidate_semantics(cand_meta)
            }

    final_order = sorted(final_scores, key=final_scores.get, reverse=True)
    
    recs, seen_keys = [], set()
    
    for idx in final_order:
        if len(recs) >= k: break
        
        meta = metas[idx]
        if excluir_nome and meta.get("nome") == excluir_nome: continue
            
        key = _canonical_track_key(meta, ids[idx])
        if key in seen_keys: continue
        seen_keys.add(key)
        
        rec = {
            "id": ids[idx], "titulo": meta.get("titulo") or meta.get("nome"),
            "artista": meta.get("artista"), "rank": len(recs) + 1,
            "similaridade": float(final_scores[idx]),
            "similaridade_oculta": HIDE_NUMERIC_SIMILARITY,
            "caminho": (meta.get("caminho") or meta.get("link_spotify") or meta.get("youtube")),
            "spotify": meta.get("spotify"), "youtube": meta.get("youtube"),
        }
        if dbg:
            rec["debug"] = diag_map.get(idx)

        recs.append(rec)
    
    return recs