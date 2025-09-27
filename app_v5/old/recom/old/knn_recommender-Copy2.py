# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
import os, re
import numpy as np  # não reatribuir

# =========================
# CONFIG
# =========================
# Tenta importar config da app e, em fallback, da raiz
try:
    from app_v5.config import (
        BLOCK_SCALER_PATH, BLOCK_WEIGHTS, SIMILARITY_METRIC, HIDE_NUMERIC_SIMILARITY,
        SEM_FILTER_ENABLE, SEM_MIN_CANDIDATOS, SEM_GENRE_STRICT,
        SEM_RERANK_ENABLE, SEM_TOPN,
        SEM_GENRE_PENALTY, SEM_BPM_TOL, SEM_BPM_MAX_PENALTY, SEM_YEAR_TOL, SEM_YEAR_PENALTY, SEM_MODE_PENALTY,
        BLOCK_WEIGHTS_TWEAKS,
        GENRE_WHITELISTS,
        SEM_DIST_Q_CUTOFF, SEM_DIST_MIN_KEEP,
    )
except Exception:
    # defaults caso não existam no config.py
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
    BLOCK_WEIGHTS_TWEAKS = {
        "spectral_centroid": 1.20,
        "rolloff":           1.15,
        "flatness":          1.10,
        "onset_rate":        1.15,
        "chroma":            0.95,
    }
    GENRE_WHITELISTS = {
        "rock": {"rock","classic rock","hard rock","glam metal","metal","pop rock"},
        "samba":{"samba","pagode"},
        "mpb": {"mpb","bossa nova","samba"},
        "arrocha":{"arrocha","sertanejo","piseiro"},
        "sertanejo":{"sertanejo","arrocha","piseiro"},
        "forro":{"forro","piseiro"},
        "funk":{"funk","funk carioca"},
        "rap":{"rap","hip hop","trap"},
        "pop":{"pop","dance pop"},
        "jazz":{"jazz","swing","bebop"},
    }
    SEM_DIST_Q_CUTOFF = 90
    SEM_DIST_MIN_KEEP = 60

# Strictness & debug (podem vir do config.py; se não, pegue do env ou defaults)
SEM_STRICT_LEVEL = int(os.getenv("SEM_STRICT_LEVEL", "1"))  # 0..3
SEM_DEBUG_ENABLE = (os.getenv("SEM_DEBUG_ENABLE","false").lower()=="true")

from app_v5.database.db import carregar_matriz
from app_v5.audio.extrator_fft import extrair_features_completas, get_feature_blocks


# =========================
# METADATA (fluxo atual)
# =========================
# Tentamos usar o seu metadata.py. Ajuste o caminho se o seu for diferente.
get_query_metadata = None
enrich_meta = None
for mod in (
    "app_v5.metadata.metadata",  # pacote/arquivo app_v5/metadata/metadata.py
    "app_v5.metadata",           # app_v5/metadata.py
    "metadata",                  # metadata.py na raiz
):
    try:
        _m = __import__(mod, fromlist=["*"])
        get_query_metadata = getattr(_m, "get_query_metadata", get_query_metadata)
        enrich_meta = getattr(_m, "enrich_meta", enrich_meta)
    except Exception:
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
    """Peso por bloco com suporte a ajustes do config."""
    base = float(BLOCK_WEIGHTS.get(name, 1.0))
    if isinstance(BLOCK_WEIGHTS_TWEAKS, dict) and name in BLOCK_WEIGHTS_TWEAKS:
        try:
            tweak = float(BLOCK_WEIGHTS_TWEAKS[name])
            return tweak
        except Exception:
            return base
    return base


def _apply_block_scaler(X: np.ndarray, scaler: Dict[str, Dict[str, np.ndarray]]) -> np.ndarray:
    Xs = X.copy()
    blocks = get_feature_blocks()
    for name, sl in blocks.items():
        info = scaler.get(name)
        if not info:
            continue
        mu = info["mean"]; sd = info["std"]
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
    import numpy as np
    X = np.asarray(x_mat, dtype=float)
    q = np.asarray(q_vec, dtype=float).ravel()
    denom = (np.linalg.norm(X, axis=1) + 1e-12) * (np.linalg.norm(q) + 1e-12)
    return (X @ q) / denom

def _euclidean_dist_local(x_mat, q_vec) -> "np.ndarray":
    import numpy as np
    X = np.asarray(x_mat, dtype=float)
    q = np.asarray(q_vec, dtype=float).ravel()
    if X.ndim != 2:
        X = np.atleast_2d(X)
    n = min(X.shape[1], q.shape[0])
    X = X[:, :n]; q = q[:n]
    return np.linalg.norm(X - q, axis=1)


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
    s = re.sub(r"\s+", " ", s)
    return s

def _norm_genre(x: Any) -> Optional[str]:
    if x is None: return None
    if isinstance(x, (list, tuple)) and x:
        x = x[0]
    s = _norm_text(x)
    s = s.replace("rock and roll", "rock").replace("hard rock", "rock").replace("glam metal","rock")
    s = s.replace("pagode","samba")
    return s or None

def _parse_number(x: Any) -> Optional[float]:
    if x is None: return None
    if isinstance(x, (int,float)): return float(x)
    m = re.search(r"[-+]?\d+(\.\d+)?", str(x))
    return float(m.group()) if m else None

def _norm_mode(x: Any) -> Optional[str]:
    if x is None: return None
    s = _norm_text(x)
    if any(t in s for t in ["minor","menor","aeolian"]): return "minor"
    if any(t in s for t in ["major","maior","ionian"]):  return "major"
    return None

def _pick(d: Dict[str, Any], path: List[str]) -> Any:
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur: return None
        cur = cur[p]
    return cur

def _extract_candidate_semantics(meta: Dict[str,Any]) -> Dict[str,Any]:
    # gênero
    genre_raw = (
        _get_first(meta, ["gênero","genero","genre","estilo","style"]) or
        _pick(meta, ["enriched","genre"]) or
        _pick(meta, ["enriched","genres"]) or
        _pick(meta, ["spotify","genre"]) or
        _pick(meta, ["spotify","genres"])
    )
    # bpm
    bpm_raw = (
        _get_first(meta, ["bpm","tempo"]) or
        _pick(meta, ["enriched","audio_features","tempo"]) or
        _pick(meta, ["spotify","audio_features","tempo"])
    )
    # ano
    year_raw = (
        _get_first(meta, ["ano","year","release_year"]) or
        _pick(meta, ["enriched","release_year"]) or
        _pick(meta, ["spotify","album","release_year"])
    )
    # modo
    mode_raw = (
        _get_first(meta, ["mode","modo","scale","tom"]) or
        _pick(meta, ["enriched","audio_features","mode"]) or
        _pick(meta, ["spotify","audio_features","mode"])
    )

    return {
        "genre": _norm_genre(genre_raw),
        "bpm": _parse_number(bpm_raw),
        "year": int(_parse_number(year_raw)) if _parse_number(year_raw) is not None else None,
        "mode": _norm_mode(mode_raw),
    }

def _extract_query_semantics(query_meta: Optional[Dict[str,Any]]) -> Dict[str,Any]:
    if not query_meta:
        return {"genre":None,"bpm":None,"year":None,"mode":None}
    g = _get_first(query_meta, ["genero","gênero","genre","estilo","style"])
    b = _get_first(query_meta, ["bpm","tempo"])
    y = _get_first(query_meta, ["ano","year","release_year"])
    m = _get_first(query_meta, ["mode","modo","scale","tom"])
    return {
        "genre": _norm_genre(g),
        "bpm": _parse_number(b),
        "year": int(_parse_number(y)) if _parse_number(y) is not None else None,
        "mode": _norm_mode(m),
    }

def _try_query_semantics_from_metadata(path_audio: str) -> Dict[str,Any]:
    """Tenta usar o metadata.py do projeto para extrair metadados da QUERY."""
    if callable(get_query_metadata):
        try:
            raw = get_query_metadata(path_audio)  # esperado: dict com campos de meta
            if isinstance(raw, dict):
                return _extract_candidate_semantics(raw)
        except Exception:
            pass
    return {"genre":None,"bpm":None,"year":None,"mode":None}

def _bootstrap_query_semantics_from_candidates(order: np.ndarray,
                                               metas: List[Dict[str,Any]],
                                               topn: int = 100) -> Dict[str,Any]:
    """Se não houver meta do query, infere por maioria/mediana nos Top-N candidatos."""
    idxs = list(order[:min(len(order), topn)])
    genres, bpms, years, modes = [], [], [], []
    for i in idxs:
        csem = _extract_candidate_semantics(metas[i] or {})
        if csem.get("genre"): genres.append(csem["genre"])
        if csem.get("bpm") is not None: bpms.append(float(csem["bpm"]))
        if csem.get("year") is not None: years.append(int(csem["year"]))
        if csem.get("mode"): modes.append(csem["mode"])

    from collections import Counter
    genre = Counter(genres).most_common(1)[0][0] if genres else None
    bpm = float(np.median(bpms)) if bpms else None
    year = int(np.median(years)) if years else None
    mode = Counter(modes).most_common(1)[0][0] if modes else None
    return {"genre": genre, "bpm": bpm, "year": year, "mode": mode}


# =========================
# GENRES: WHITELIST / TRILHOS
# =========================
if not isinstance(GENRE_WHITELISTS, dict):
    GENRE_WHITELISTS = {}

def _genre_group(g: Optional[str]) -> Optional[str]:
    """Encontra o 'grupo' do gênero com base no GENRE_WHITELISTS (chave que contém o gênero)."""
    if not g:
        return None
    g = _norm_genre(g)
    for root, allowed in GENRE_WHITELISTS.items():
        if g == root or g in allowed:
            return root
    return g  # se não achar grupo, usa o próprio gênero

def _same_genre_lane(g_query: Optional[str], g_cand: Optional[str]) -> bool:
    """True se candidato pertence ao mesmo 'trilho' (whitelist) do gênero do query."""
    if not g_query or not g_cand:
        return False
    gq = _genre_group(g_query)
    gc = _genre_group(g_cand)
    if gq == gc:
        return True
    allow = GENRE_WHITELISTS.get(gq, set())
    return gc in allow or _norm_genre(g_cand) in allow


# =========================
# DEDUP (Spotify / YouTube / Título+Artista)
# =========================
_SPOT_RE = re.compile(r"(spotify:track:|open\.spotify\.com/track/)([A-Za-z0-9]+)")
_YT_RE_V = re.compile(r"[?&]v=([A-Za-z0-9_\-]{6,})")
_YT_RE_S = re.compile(r"youtu\.be/([A-Za-z0-9_\-]{6,})")

def _extract_spotify_id(url: Optional[str]) -> Optional[str]:
    if not url: return None
    m = _SPOT_RE.search(str(url))
    return m.group(2) if m else None

def _extract_youtube_id(url: Optional[str]) -> Optional[str]:
    if not url: return None
    s = str(url)
    m = _YT_RE_V.search(s) or _YT_RE_S.search(s)
    return m.group(1) if m else None

def _canonical_track_key(meta: Dict[str,Any], fallback_id: Optional[Any]=None) -> str:
    # prioriza IDs fortes
    sp = _get_first(meta, ["spotify","link_spotify"])
    yt = _get_first(meta, ["youtube","link_youtube"])
    sp_id = _extract_spotify_id(sp)
    yt_id = _extract_youtube_id(yt)
    if sp_id: return f"sp:{sp_id}"
    if yt_id: return f"yt:{yt_id}"
    # fallback em título+artista normalizados
    title = _norm_text(_get_first(meta, ["titulo","title","nome"]) or "")
    artist = _norm_text(_get_first(meta, ["artista","artist"]) or "")
    if title or artist:
        return f"ta:{title}|{artist}"
    # último recurso: id interno (garante chave)
    return f"id:{fallback_id}"

def _dedup_order_by_key(order: np.ndarray, metas: List[Dict[str,Any]], ids: List[int]) -> np.ndarray:
    seen: set[str] = set()
    out: List[int] = []
    for idx in order:
        i = int(idx)
        key = _canonical_track_key(metas[i] or {}, ids[i] if i < len(ids) else None)
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
    return np.asarray(out, dtype=int)


# =========================
# STRICTNESS: RESOLUÇÃO DE PARÂMETROS
# =========================
def _resolve_strict_params(level: int) -> Dict[str, Any]:
    """
    Constrói parâmetros efetivos conforme o 'nível de rigidez' (0..3).
    Aumentar nível => mais corte por distância, gênero mais rígido, penalidades maiores e tolerâncias menores.
    """
    lvl = max(0, min(int(level), 3))
    # bases vindas do config
    base = dict(
        genre_penalty=float(SEM_GENRE_PENALTY),
        bpm_tol=float(SEM_BPM_TOL),
        bpm_max_pen=float(SEM_BPM_MAX_PENALTY),
        year_tol=int(SEM_YEAR_TOL),
        year_penalty=float(SEM_YEAR_PENALTY),
        mode_penalty=float(SEM_MODE_PENALTY),
        dist_q=int(SEM_DIST_Q_CUTOFF),
        min_keep=int(SEM_DIST_MIN_KEEP),
        genre_strict=bool(SEM_GENRE_STRICT),
        min_cand=int(SEM_MIN_CANDIDATOS),
    )
    # multiplicadores/ajustes por nível
    if lvl == 0:
        return {**base,
                "dist_q": min(99, max(80, base["dist_q"] + 5)),
                "genre_strict": False,
                "bpm_tol": base["bpm_tol"] + 10,
                "year_tol": base["year_tol"] + 5,
                "genre_penalty": max(0.10, base["genre_penalty"] - 0.05),
                "mode_penalty": max(0.05, base["mode_penalty"] - 0.05)}
    if lvl == 1:
        return base
    if lvl == 2:
        return {**base,
                "dist_q": max(80, base["dist_q"] - 5),
                "genre_strict": True,
                "bpm_tol": max(20.0, base["bpm_tol"] - 10),
                "year_tol": max(10, base["year_tol"] - 3),
                "genre_penalty": min(0.35, base["genre_penalty"] + 0.10),
                "mode_penalty": min(0.15, base["mode_penalty"] + 0.03)}
    # lvl == 3
    return {**base,
            "dist_q": max(75, base["dist_q"] - 10),
            "genre_strict": True,
            "bpm_tol": max(15.0, base["bpm_tol"] - 15),
            "year_tol": max(8, base["year_tol"] - 5),
            "genre_penalty": min(0.45, base["genre_penalty"] + 0.20),
            "mode_penalty": min(0.20, base["mode_penalty"] + 0.05)}


# =========================
# DISTÂNCIA: CUTOFF POR QUANTIL
# =========================
def _apply_distance_cutoff(order: np.ndarray, dists: np.ndarray, dist_q: int, min_keep: int) -> np.ndarray:
    """Remove candidatos muito distantes (d > Qcut) mantendo no mínimo min_keep."""
    if len(order) == 0:
        return order
    try:
        dc = np.percentile(dists[order], int(dist_q))
    except Exception:
        return order
    kept = [i for i in order if dists[i] <= dc]
    if len(kept) >= int(min_keep):
        return np.asarray(kept, dtype=int)
    return order  # se cortar demais, mantém


# =========================
# FILTRO + RERANK (TRILHOS)
# =========================
def _apply_semantic_filter(order: np.ndarray, metas: List[Dict[str,Any]], qsem: Dict[str,Any],
                           genre_strict: bool, min_cand: int) -> np.ndarray:
    """Filtra por 'trilho' de gênero (whitelist). Se ficar muito curto, relaxa a menos que genre_strict=True."""
    if not SEM_FILTER_ENABLE or not qsem.get("genre"):
        return order
    kept = []
    for i in order:
        csem = _extract_candidate_semantics(metas[i] or {})
        if _same_genre_lane(qsem.get("genre"), csem.get("genre")):
            kept.append(i)
    if kept and (len(kept) >= min_cand or genre_strict):
        return np.asarray(kept, dtype=int)
    return order


def _apply_semantic_rerank(order: np.ndarray,
                           dists: np.ndarray,
                           metas: List[Dict[str,Any]],
                           qsem: Dict[str,Any],
                           genre_penalty: float,
                           bpm_tol: float,
                           bpm_max_pen: float,
                           year_tol: int,
                           year_penalty: float,
                           mode_penalty: float,
                           debug: bool = False) -> Tuple[np.ndarray, Optional[Dict[int, Dict[str,Any]]]]:
    """Rerank usando penalidades; retorna nova ordem e, se debug=True, um mapa de diagnósticos por índice."""
    if not SEM_RERANK_ENABLE:
        return order, None

    cand = order[:min(len(order), SEM_TOPN)]
    base_score = 1.0 / (1.0 + dists[cand])  # 0..1, maior=melhor

    penalties = np.zeros_like(base_score)
    diag: Dict[int, Dict[str,Any]] = {} if debug else None

    for idx, i in enumerate(cand):
        csem = _extract_candidate_semantics(metas[i] or {})
        p = 0.0
        reasons = []

        # gênero
        if qsem.get("genre") and csem.get("genre"):
            if not _same_genre_lane(qsem["genre"], csem["genre"]):
                p += genre_penalty
                reasons.append(f"genre_out(+{genre_penalty:.2f})")

        # bpm
        if qsem.get("bpm") is not None and csem.get("bpm") is not None:
            diff = abs(float(qsem["bpm"]) - float(csem["bpm"]))
            add = min(diff / max(1.0, bpm_tol), 1.0) * bpm_max_pen
            if add > 0:
                p += add
                reasons.append(f"bpm_diff={diff:.1f}(+{add:.2f})")

        # ano
        if qsem.get("year") is not None and csem.get("year") is not None:
            if abs(int(qsem["year"]) - int(csem["year"])) > year_tol:
                p += year_penalty
                reasons.append(f"year_out(+{year_penalty:.2f})")

        # modo
        if qsem.get("mode") and csem.get("mode") and qsem["mode"] != csem["mode"]:
            p += mode_penalty
            reasons.append(f"mode_out(+{mode_penalty:.2f})")

        penalties[idx] = p

        if debug:
            diag[i] = {
                "distance": float(dists[i]),
                "base_score": float(base_score[idx]),
                "penalty_total": float(p),
                "reasons": reasons,
                "cand_sem": csem,
            }

    final = base_score - penalties
    new_order = cand[np.argsort(final)[::-1]]
    tail = np.array([i for i in order if i not in set(new_order)], dtype=int)
    out_order = np.concatenate([new_order, tail])

    return out_order, diag


# =========================
# RECOMENDAÇÃO KNN
# =========================
def recomendar_por_audio(
    path_audio: str,
    k: int = 3,
    sr: int = 22050,
    excluir_nome: str | None = None,
    metric: str | None = None,
    query_meta: Optional[Dict[str,Any]] = None,   # meta da query (gênero/bpm/ano/mode), opcional
    strict_level: Optional[int] = None,           # override do nível de rigidez (0..3)
    debug: Optional[bool] = None,                 # força debug (True/False)
) -> List[Dict[str, Any]]:
    """
    Gera recomendações a partir de um arquivo de áudio local.
    - Métrica padrão: euclidiana (SIMILARITY_METRIC em config.py)
    - Trilhos: corte por distância + filtro (whitelist) + rerank por metadados (quando existir)
    - Dedup: remove duplicados por Spotify/YouTube/(título,artista)
    - Exibição: ranking-only se HIDE_NUMERIC_SIMILARITY=True
    - Ajuste gradual: SEM_STRICT_LEVEL (0..3) mais rígido => menos falsos positivos
    - Debug opcional: inclui motivos/penalidades no payload
    """
    import librosa

    # parâmetros efetivos (strictness & debug)
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
    dists = _euclidean_dist_local(Xs, q[0])       # menor = melhor
    sims  = _cosine_sim_local(Xs, q[0])           # maior = melhor (só p/ exibição/futuro)

    # ordem base
    if chosen == "euclidean":
        order = np.argsort(dists)
        sims_display = (1.0 / (1.0 + dists)) * 100.0  # se quiser mostrar %
    else:
        order = np.argsort(-sims)
        sims_display = np.clip(sims, 0.0, 1.0) * 100.0

    # === TRILHOS: metadados do fluxo atual ===
    # 1) meta passada pelo chamador
    qsem = _extract_query_semantics(query_meta)
    # 2) tentar metadata.py da query
    if not any(qsem.values()):
        qmd = _try_query_semantics_from_metadata(str(p))
        for k2, v2 in qmd.items():
            if qsem.get(k2) in (None, "") and v2 not in (None, ""):
                qsem[k2] = v2
    # 3) se ainda vazio, bootstrap pelos candidatos
    if not any(qsem.values()):
        qsem = _bootstrap_query_semantics_from_candidates(order, metas, topn=100)

    # === DISTANCE CUTOFF: remove outliers (por quantil) ===
    order = _apply_distance_cutoff(order, dists, dist_q=P["dist_q"], min_keep=P["min_keep"])

    # === Filtro por gênero (whitelist) ===
    if SEM_FILTER_ENABLE:
        order = _apply_semantic_filter(order, metas, qsem,
                                       genre_strict=P["genre_strict"], min_cand=P["min_cand"])

    # === Rerank por penalidades ===
    diag_map = None
    if SEM_RERANK_ENABLE:
        order, diag_map = _apply_semantic_rerank(
            order, dists, metas, qsem,
            genre_penalty=P["genre_penalty"],
            bpm_tol=P["bpm_tol"], bpm_max_pen=P["bpm_max_pen"],
            year_tol=P["year_tol"], year_penalty=P["year_penalty"],
            mode_penalty=P["mode_penalty"],
            debug=dbg
        )

    # === DEDUP por chave canônica (Spotify/YouTube/título+artista) ===
    order = _dedup_order_by_key(order, metas, ids)

    # monta top-k (ranking-only por padrão)
    recs: List[Dict[str, Any]] = []
    rank = 0
    for idx in order:
        i = int(idx)
        meta = metas[i] or {}
        if excluir_nome and meta.get("nome") == excluir_nome:
            continue

        rank += 1

        # controla exibição do número
        if HIDE_NUMERIC_SIMILARITY:
            similaridade_val = 0.0
            similaridade_oculta = True
        else:
            similaridade_val = float(sims_display[i])
            similaridade_oculta = False

        rec = {
            "id": ids[i],
            "titulo": meta.get("titulo") or meta.get("nome"),
            "artista": meta.get("artista"),
            "rank": rank,                         # ranking absoluto (🥇/🥈/🥉...)
            "similaridade": similaridade_val,     # mantido por compatibilidade
            "similaridade_oculta": similaridade_oculta,  # UI deve esconder se True
            "caminho": (meta.get("link_spotify") or meta.get("spotify") or meta.get("caminho")
                        or meta.get("link_youtube") or meta.get("youtube")),
            "spotify": (meta.get("spotify") or meta.get("link_spotify")),
            "youtube": (meta.get("youtube") or meta.get("link_youtube")),
        }

        if dbg:
            # Se não temos diag pré-calculado (porque item ficou fora do top rerank),
            # recalculamos penalidades só para exibir no debug:
            if not (diag_map and i in diag_map):
                csem = _extract_candidate_semantics(meta)
                p_total = 0.0
                reasons = []
                # gênero
                if qsem.get("genre") and csem.get("genre"):
                    if not _same_genre_lane(qsem["genre"], csem["genre"]):
                        p_total += P["genre_penalty"]; reasons.append(f"genre_out(+{P['genre_penalty']:.2f})")
                # bpm
                if qsem.get("bpm") is not None and csem.get("bpm") is not None:
                    diff = abs(float(qsem["bpm"]) - float(csem["bpm"]))
                    add = min(diff / max(1.0, P["bpm_tol"]), 1.0) * P["bpm_max_pen"]
                    if add > 0:
                        p_total += add; reasons.append(f"bpm_diff={diff:.1f}(+{add:.2f})")
                # ano
                if qsem.get("year") is not None and csem.get("year") is not None:
                    if abs(int(qsem["year"]) - int(csem["year"])) > P["year_tol"]:
                        p_total += P["year_penalty"]; reasons.append(f"year_out(+{P['year_penalty']:.2f})")
                # modo
                if qsem.get("mode") and csem.get("mode") and qsem["mode"] != csem["mode"]:
                    p_total += P["mode_penalty"]; reasons.append(f"mode_out(+{P['mode_penalty']:.2f})")
                base_score = float(1.0 / (1.0 + dists[i]))
                rec["debug"] = {
                    "strict_level": lvl,
                    "distance": float(dists[i]),
                    "base_score": base_score,
                    "penalty_total": float(p_total),
                    "final_like": base_score - float(p_total),
                    "reasons": reasons,
                    "query_sem": qsem,
                    "cand_sem": csem,
                }
            else:
                rec["debug"] = {
                    "strict_level": lvl,
                    "distance": float(dists[i]),
                    "base_score": float(diag_map[i]["base_score"]),
                    "penalty_total": float(diag_map[i]["penalty_total"]),
                    "final_like": float(diag_map[i]["base_score"] - diag_map[i]["penalty_total"]),
                    "reasons": diag_map[i]["reasons"],
                    "query_sem": qsem,
                    "cand_sem": diag_map[i]["cand_sem"],
                }

        recs.append(rec)
        if len(recs) >= k:
            break

    return recs
