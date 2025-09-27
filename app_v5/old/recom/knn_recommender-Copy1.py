# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
import os, re, json, datetime
import numpy as np
import logging

# =========================
# CONFIG
# =========================
try:
    from app_v5.config import (
        BLOCK_SCALER_PATH, BLOCK_WEIGHTS, SIMILARITY_METRIC, HIDE_NUMERIC_SIMILARITY,
        SEM_FILTER_ENABLE, SEM_MIN_CANDIDATOS, SEM_GENRE_STRICT,
        SEM_RERANK_ENABLE, SEM_TOPN,
        SEM_GENRE_PENALTY, SEM_BPM_TOL, SEM_BPM_MAX_PENALTY, SEM_YEAR_TOL, SEM_YEAR_PENALTY, SEM_MODE_PENALTY,
        BLOCK_WEIGHTS_TWEAKS,
        GENRE_WHITELISTS,
        SEM_DIST_Q_CUTOFF, SEM_DIST_MIN_KEEP,
        LOG_DIR, SEM_DEBUG_ENABLE, SEM_STRICT_LEVEL,
    )
except Exception as e:
    logging.warning(f"Não foi possível importar configs, usando defaults: {e}")
    # Fallback defaults
    BLOCK_SCALER_PATH = Path("./.cache/block_scaler.npz")
    BLOCK_WEIGHTS = {}
    SIMILARITY_METRIC = "euclidean"
    HIDE_NUMERIC_SIMILARITY = True
    SEM_FILTER_ENABLE = True
    SEM_MIN_CANDIDATOS = 50
    SEM_GENRE_STRICT = True
    SEM_RERANK_ENABLE = True
    SEM_TOPN = 200
    SEM_GENRE_PENALTY = 0.20
    SEM_BPM_TOL = 40.0
    SEM_BPM_MAX_PENALTY = 0.20
    SEM_YEAR_TOL = 15
    SEM_YEAR_PENALTY = 0.10
    SEM_MODE_PENALTY = 0.10
    BLOCK_WEIGHTS_TWEAKS = {}
    GENRE_WHITELISTS = {}
    SEM_DIST_Q_CUTOFF = 90
    SEM_DIST_MIN_KEEP = 60
    LOG_DIR = Path("./logs")
    SEM_DEBUG_ENABLE = False
    SEM_STRICT_LEVEL = 1

from app_v5.database.db import carregar_matriz
from app_v5.audio.extrator_fft import extrair_features_completas, get_feature_blocks

# =========================
# METADATA (fluxo atual)
# =========================
get_query_metadata = None
try:
    from app_v5.services.metadata import get_query_metadata_live
    get_query_metadata = get_query_metadata_live
    logging.info("Função de metadados ao vivo importada com sucesso.")
except ImportError:
    logging.warning("Não foi possível importar 'get_query_metadata_live'. A busca de metadados em tempo real pode falhar.")


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
            Xs[:, sl] = (Xs[:, sl] - mu) / sd
            Xs[:, sl] *= _apply_block_weight(name)
    return Xs

def _save_scaler(scaler: Dict[str, Dict[str, np.ndarray]]) -> None:
    BLOCK_SCALER_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        BLOCK_SCALER_PATH,
        **{f"{k}_mean": v["mean"] for k, v in scaler.items()},
        **{f"{k}_std": v["std"] for k, v in scaler.items()},
    )

def _load_scaler() -> Dict[str, Dict[str, np.ndarray]] | None:
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
    if getattr(X, "shape", (0, 0))[0] == 0:
        return X, ids, metas, {}
    scaler = _load_scaler()
    if scaler is None:
        scaler = _fit_block_scaler(X)
        _save_scaler(scaler)
    Xs = _apply_block_scaler(X, scaler)
    return Xs, ids, metas, scaler


# =========================
# MÉTRICAS
# =========================
def _cosine_sim_local(x_mat, q_vec) -> "np.ndarray":
    X = np.asarray(x_mat, dtype=float)
    q = np.asarray(q_vec, dtype=float).ravel()
    denom = (np.linalg.norm(X, axis=1) + 1e-12) * (np.linalg.norm(q) + 1e-12)
    return (X @ q) / denom

def _euclidean_dist_local(x_mat, q_vec) -> "np.ndarray":
    X = np.asarray(x_mat, dtype=float)
    q = np.asarray(q_vec, dtype=float).ravel()
    if X.ndim != 2: X = np.atleast_2d(X)
    n = min(X.shape[1], q.shape[0])
    return np.linalg.norm(X[:, :n] - q[:n], axis=1)


# =========================
# HELPERS DE METADADOS
# =========================
def _get_first(meta: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for k in keys:
        if k in meta and meta[k] not in (None, "", "null"):
            return meta[k]
    return None

def _norm_text(x: Any) -> str:
    s = str(x).strip().lower()
    return re.sub(r"\s+", " ", s)

def _norm_genre(x: Any) -> Optional[str]:
    if x is None: return None
    raw_genres = []
    if isinstance(x, (list, tuple, set)):
        raw_genres.extend(str(t) for t in x)
    else:
        raw_genres.extend(re.split(r"[,/;|]+", str(x).lower()))

    clean_genres = [g.strip() for g in raw_genres if g and g.strip()]
    return clean_genres[0] if clean_genres else None

def _parse_number(x: Any) -> Optional[float]:
    if isinstance(x, (int, float)): return float(x)
    if x is None: return None
    m = re.search(r"[-+]?\d+(\.\d+)?", str(x))
    return float(m.group()) if m else None

def _norm_mode(x: Any) -> Optional[str]:
    if x is None: return None
    s = _norm_text(x)
    if any(t in s for t in ["minor", "menor"]): return "minor"
    if any(t in s for t in ["major", "maior"]): return "major"
    return None

def _extract_candidate_semantics(meta: Dict[str,Any]) -> Dict[str,Any]:
    # Corrigido para procurar 'genres' também
    genre_raw = _get_first(meta, ["gênero", "genero", "genre", "genres", "estilo", "style"])
    bpm_raw = _get_first(meta, ["bpm", "tempo"])
    year_raw = _get_first(meta, ["ano", "year", "release_year"])
    mode_raw = _get_first(meta, ["mode", "modo", "scale", "tom"])
    return {
        "genre": _norm_genre(genre_raw),
        "bpm": _parse_number(bpm_raw),
        "year": int(_parse_number(year_raw)) if _parse_number(year_raw) is not None else None,
        "mode": _norm_mode(mode_raw),
    }

def _try_query_semantics_from_metadata(path_audio: str) -> Dict[str,Any]:
    if callable(get_query_metadata):
        try:
            logging.info("Enriquecendo metadados da faixa de consulta em tempo real...")
            raw, msg = get_query_metadata(Path(path_audio))
            logging.info(msg)
            if isinstance(raw, dict):
                return _extract_candidate_semantics(raw)
        except Exception as e:
            logging.warning(f"Não foi possível enriquecer os metadados da consulta: {e}")
    else:
        logging.warning("Função 'get_query_metadata' não está disponível para busca em tempo real.")
    return {}

def _bootstrap_query_semantics_from_candidates(order: np.ndarray, metas: List[Dict[str,Any]], topn: int = 100) -> Dict[str,Any]:
    idxs = list(order[:min(len(order), topn)])
    genres, bpms, years, modes = [], [], [], []
    for i in idxs:
        csem = _extract_candidate_semantics(metas[i] or {})
        if csem.get("genre"): genres.append(csem["genre"])
        if csem.get("bpm") is not None: bpms.append(float(csem["bpm"]))
        if csem.get("year") is not None: years.append(int(csem["year"]))
        if csem.get("mode"): modes.append(csem["mode"])
    from collections import Counter
    return {
        "genre": Counter(genres).most_common(1)[0][0] if genres else None,
        "bpm": float(np.median(bpms)) if bpms else None,
        "year": int(np.median(years)) if years else None,
        "mode": Counter(modes).most_common(1)[0][0] if modes else None,
    }

# =========================
# GENRES
# =========================
def _genre_group(g: Optional[str]) -> Optional[str]:
    if not g: return None
    g_norm = _norm_genre(g)
    for root, allowed in GENRE_WHITELISTS.items():
        if g_norm in allowed:
            return root
    return g_norm

def _same_genre_lane(g_query: Optional[str], g_cand: Optional[str]) -> bool:
    if not g_query or not g_cand: return False
    return _genre_group(g_query) == _genre_group(g_cand)

# =========================
# DEDUP
# =========================
_SPOT_RE = re.compile(r"(spotify:track:|open\.spotify\.com/track/)([A-Za-z0-9]+)")
_YT_RE_V = re.compile(r"[?&]v=([A-Za-z0-9_\-]{11})")
_YT_RE_S = re.compile(r"youtu\.be/([A-Za-z0-9_\-]{11})")

def _extract_id(url: Optional[str], regexes: list) -> Optional[str]:
    if not url: return None
    for r in regexes:
        m = r.search(str(url))
        if m: return m.group(m.lastindex)
    return None

def _canonical_track_key(meta: Dict[str,Any], fallback_id: Optional[Any]=None) -> str:
    sp_id = _extract_id(_get_first(meta, ["spotify", "link_spotify"]), [_SPOT_RE])
    yt_id = _extract_id(_get_first(meta, ["youtube", "link_youtube"]), [_YT_RE_V, _YT_RE_S])
    if sp_id: return f"sp:{sp_id}"
    if yt_id: return f"yt:{yt_id}"
    title = _norm_text(_get_first(meta, ["titulo", "title", "nome"]) or "")
    artist = _norm_text(_get_first(meta, ["artista", "artist"]) or "")
    if title or artist: return f"ta:{title}|{artist}"
    return f"id:{fallback_id}"

def _dedup_order_by_key(order: np.ndarray, metas: List[Dict[str,Any]], ids: List[int]) -> np.ndarray:
    seen, out = set(), []
    for idx in order:
        i = int(idx)
        key = _canonical_track_key(metas[i] or {}, ids[i] if i < len(ids) else None)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return np.asarray(out, dtype=int)


# =========================
# STRICTNESS & FILTERS
# =========================
def _resolve_strict_params(level: int) -> Dict[str, Any]:
    lvl = max(0, min(int(level), 3))
    base = {
        "genre_penalty": SEM_GENRE_PENALTY, "bpm_tol": SEM_BPM_TOL, "bpm_max_pen": SEM_BPM_MAX_PENALTY,
        "year_tol": SEM_YEAR_TOL, "year_penalty": SEM_YEAR_PENALTY, "mode_penalty": SEM_MODE_PENALTY,
        "dist_q": SEM_DIST_Q_CUTOFF, "min_keep": SEM_DIST_MIN_KEEP,
        "genre_strict": SEM_GENRE_STRICT, "min_cand": SEM_MIN_CANDIDATOS,
    }
    if lvl == 0:
        return {**base, "genre_strict": False, "genre_penalty": max(0.10, base["genre_penalty"] - 0.2)}
    if lvl == 2:
        return {**base, "dist_q": max(80, base["dist_q"] - 5), "genre_penalty": min(0.6, base["genre_penalty"] + 0.15)}
    if lvl == 3:
        return {**base, "dist_q": max(75, base["dist_q"] - 10), "genre_penalty": min(0.85, base["genre_penalty"] + 0.3)}
    return base

def _apply_distance_cutoff(order: np.ndarray, dists: np.ndarray, dist_q: int, min_keep: int) -> np.ndarray:
    if len(order) <= min_keep: return order
    try:
        dc = np.percentile(dists[order], int(dist_q))
        kept = order[dists[order] <= dc]
        return kept if len(kept) >= min_keep else order[:min_keep]
    except Exception:
        return order

def _apply_semantic_filter(order: np.ndarray, metas: List[Dict[str,Any]], qsem: Dict[str,Any], genre_strict: bool, min_cand: int) -> np.ndarray:
    if not SEM_FILTER_ENABLE or not qsem.get("genre"): return order
    kept = [i for i in order if _same_genre_lane(qsem.get("genre"), _extract_candidate_semantics(metas[i] or {}).get("genre"))]
    return np.asarray(kept, dtype=int) if kept and (len(kept) >= min_cand or genre_strict) else order

def _apply_semantic_rerank(order: np.ndarray, dists: np.ndarray, metas: List[Dict[str,Any]], qsem: Dict[str,Any], P: Dict[str, Any], debug: bool) -> Tuple[np.ndarray, Optional[Dict[int, Dict[str,Any]]]]:
    if not SEM_RERANK_ENABLE: return order, None
    cand, diag = order[:min(len(order), SEM_TOPN)], {} if debug else None
    base_score = 1.0 / (1.0 + dists[cand])
    penalties = np.zeros_like(base_score)
    for idx, i in enumerate(cand):
        csem = _extract_candidate_semantics(metas[i] or {})
        p, reasons = 0.0, []
        if qsem.get("genre") and csem.get("genre") and not _same_genre_lane(qsem["genre"], csem["genre"]):
            p += P["genre_penalty"]; reasons.append(f"genre_out(+{P['genre_penalty']:.2f})")
        if qsem.get("bpm") is not None and csem.get("bpm") is not None:
            diff = abs(qsem["bpm"] - csem["bpm"])
            if diff > P["bpm_tol"]:
                add = min(diff / P["bpm_tol"], 1.0) * P["bpm_max_pen"]
                p += add; reasons.append(f"bpm_diff={diff:.1f}(+{add:.2f})")
        if qsem.get("year") is not None and csem.get("year") is not None and abs(qsem["year"] - csem["year"]) > P["year_tol"]:
            p += P["year_penalty"]; reasons.append(f"year_out(+{P['year_penalty']:.2f})")
        if qsem.get("mode") and csem.get("mode") and qsem["mode"] != csem["mode"]:
            p += P["mode_penalty"]; reasons.append(f"mode_out(+{P['mode_penalty']:.2f})")
        penalties[idx] = p
        if debug: diag[i] = {"distance": float(dists[i]), "base_score": float(base_score[idx]), "penalty_total": p, "reasons": reasons, "cand_sem": csem}
    final = base_score - penalties
    new_order = cand[np.argsort(final)[::-1]]
    return np.concatenate([new_order, np.setdiff1d(order, new_order, assume_unique=True)]), diag


# =========================
# LOGGING
# =========================
def _dump_log(payload: Dict, path_audio: str):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = re.sub(r"[^\w\-.]+", "_", Path(path_audio).stem)[:80] or "track"
        log_path = LOG_DIR / f"recs_{stem}_{ts}.json"
        with log_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        # Link to last log for convenience
        (LOG_DIR / "last_debug.json").unlink(missing_ok=True)
        (LOG_DIR / "last_debug.json").symlink_to(log_path)
    except Exception as e:
        logging.error(f"Falha ao salvar log de debug: {e}")


# =========================
# RECOMENDAÇÃO PRINCIPAL
# =========================
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
    """
    Gera recomendações a partir de um arquivo de áudio local.
    - Métrica padrão: euclidiana (SIMILARITY_METRIC em config.py)
    - Trilhos: prioriza mesmo gênero, depois preenche com os melhores resultados gerais.
    - Dedup: remove duplicados por Spotify/YouTube/(título,artista)
    - Exibição: ranking-only se HIDE_NUMERIC_SIMILARITY=True
    - Ajuste gradual: SEM_STRICT_LEVEL (0..3) mais rígido => menos falsos positivos
    - Debug opcional: inclui motivos/penalidades no payload e grava em ./logs
    """
    import librosa

    # parâmetros efetivos (rigidez e debug)
    lvl = SEM_STRICT_LEVEL if strict_level is None else int(strict_level)
    P = _resolve_strict_params(lvl)
    dbg = SEM_DEBUG_ENABLE if debug is None else bool(debug)

    p = Path(path_audio).expanduser()
    if str(p) in (".", "./") or p.is_dir() or (not p.exists()):
        return []

    # Base escalada
    Xs, ids, metas, scaler = preparar_base_escalada()
    n = getattr(Xs, "shape", (0,))[0] if Xs is not None else 0
    if n == 0:
        return []

    # Audio -> features da query
    try:
        y, _sr = librosa.load(str(p), sr=sr, mono=True)
    except Exception:
        return []
    q = extrair_features_completas(y, _sr).reshape(1, -1)

    # aplica scaler por blocos + pesos (com tweaks)
    if scaler:
        blocks = get_feature_blocks()
        for name, sl in blocks.items():
            if name in scaler:
                mu = np.asarray(scaler[name]["mean"], dtype=float)
                sd = np.asarray(scaler[name]["std"], dtype=float)
                q[:, sl] = (q[:, sl] - mu) / (sd + 1e-12)
                q[:, sl] *= _apply_block_weight(name)

    # métrica base
    chosen = (metric or os.getenv("SIMILARITY_METRIC") or SIMILARITY_METRIC or "euclidean").lower()

    # calcula métricas (uma vez)
    dists = _euclidean_dist_local(Xs, q[0])
    sims  = _cosine_sim_local(Xs, q[0])

    # ordem base
    if chosen == "euclidean":
        order = np.argsort(dists)
        sims_display = (1.0 / (1.0 + dists)) * 100.0
    else:
        order = np.argsort(-sims)
        sims_display = np.clip(sims, 0.0, 1.0) * 100.0

    # === TRILHOS: metadados do fluxo atual ===
    qsem = _extract_candidate_semantics(query_meta or {})
    if not any(qsem.values()):
        qmd = _try_query_semantics_from_metadata(str(p))
        # Atualiza 'qsem' apenas com os valores que não foram preenchidos antes
        for k2, v2 in qmd.items():
            if qsem.get(k2) in (None, "") and v2 not in (None, ""):
                qsem[k2] = v2
            
    # Como último recurso, infere a semântica a partir dos vizinhos mais próximos
    if not any(qsem.values()):
        qsem = _bootstrap_query_semantics_from_candidates(order, metas, topn=100)
    

    # === DISTANCE CUTOFF: remove outliers (por quantil) ===
    order = _apply_distance_cutoff(order, dists, dist_q=P["dist_q"], min_keep=P["min_keep"])

    # === Filtro por gênero (whitelist) - AQUI USADO APENAS PARA O RERANK DECIDIR A PENALIDADE ===
    # A separação explícita será feita no final
    order_filtrado = _apply_semantic_filter(order, metas, qsem,
                                           genre_strict=False, # Não remove os outros, apenas para rerank
                                           min_cand=0)

    # === Rerank por penalidades ===
    # order_reranked, diag_map = _apply_semantic_rerank(
    #     order_filtrado, dists, metas, qsem,
    #     genre_penalty=P["genre_penalty"],
    #     bpm_tol=P["bpm_tol"], bpm_max_pen=P["bpm_max_pen"],
    #     year_tol=P["year_tol"], year_penalty=P["year_penalty"],
    #     mode_penalty=P["mode_penalty"],
    #     debug=dbg
    # )
    order_reranked, diag_map = _apply_semantic_rerank(
        order_filtrado, dists, metas, qsem, P, dbg
    )

    # === DEDUP por chave canônica (Spotify/YouTube/título+artista) ===
    order_final = _dedup_order_by_key(order_reranked, metas, ids)

    # === Monta lista final com prioridade de gênero ===
    recs_genre = []
    recs_other = []

    for i in order_final:
        meta = metas[i] or {}
        if excluir_nome and meta.get("nome") == excluir_nome:
            continue

        similaridade_val = 0.0 if HIDE_NUMERIC_SIMILARITY else float(sims_display[i])

        rec = {
            "id": ids[i],
            "titulo": meta.get("titulo") or meta.get("nome"),
            "artista": meta.get("artista"),
            "similaridade": similaridade_val,
            "similaridade_oculta": HIDE_NUMERIC_SIMILARITY,
            "caminho": (meta.get("link_spotify") or meta.get("spotify") or meta.get("caminho")
                        or meta.get("link_youtube") or meta.get("youtube")),
            "spotify": (meta.get("spotify") or meta.get("link_spotify")),
            "youtube": (meta.get("youtube") or meta.get("link_youtube")),
        }

        # Adiciona info de debug se necessário
        if dbg and diag_map and i in diag_map:
            d = diag_map[i]
            rec["debug"] = {
                "strict_level": lvl, "distance": float(d["distance"]), "base_score": float(d["base_score"]),
                "penalty_total": float(d["penalty_total"]), "final_like": float(d["base_score"] - d["penalty_total"]),
                "reasons": d["reasons"], "query_sem": qsem, "cand_sem": d["cand_sem"],
            }
        
        # Separa na lista correta
        csem = _extract_candidate_semantics(meta)
        if qsem.get("genre") and _same_genre_lane(qsem["genre"], csem.get("genre")):
            recs_genre.append(rec)
        else:
            recs_other.append(rec)

    # Combina as listas, dando prioridade ao mesmo gênero, e corta em K
    final_recs = (recs_genre + recs_other)[:k]
    
    # Adiciona o rank final
    for rank, item in enumerate(final_recs, 1):
        item["rank"] = rank

    # === LOG DE DEBUG EM ./logs ===
    if dbg:
        log_payload = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "query_file": str(Path(path_audio)),
            "strict_level": lvl,
            "metric": chosen,
            "query_sem": qsem,
            "top_k": k,
            "items": final_recs,
        }
        _dump_log(log_payload, path_audio)

    return final_recs