# -*- coding: utf-8 -*-
"""
app_v5.integrations.bridge (fluxo da CLI + fallback suave)
- Usa exatamente o pipeline de metadados da CLI:
  * services.ingest.baixar_audio_youtube
  * services.metadata.enrich_metadata / _parse_title_tokens
  * services.youtube_backfill.buscar_youtube_link
- Grava via database.db.upsert_musica (assinatura do projeto, com link_spotify).
- Se enrich_metadata não "aceitar" (accepted=False), NÃO aborta: preenche com heurísticas e segue.
- Se quiser abortar como antes, defina BOT_STRICT_METADATA=1 no ambiente.
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import logging
import os

log = logging.getLogger(__name__)

# -------- Flags de execução --------
BOT_STRICT_METADATA = (os.getenv("BOT_STRICT_METADATA", "0").strip().lower() in {"1","true","yes","on"})

# -------- Config --------
try:
    from app_v5.config import DOWNLOADS_DIR, EXPECTED_FEATURE_LENGTH
except Exception:
    DOWNLOADS_DIR = "./downloads"
    EXPECTED_FEATURE_LENGTH = 161

# -------- Integração (mesmo fluxo da CLI) --------
from app_v5.services.ingest import baixar_audio_youtube
from app_v5.services.metadata import enrich_metadata, _parse_title_tokens
from app_v5.services.youtube_backfill import buscar_youtube_link

# -------- DB / Recomendador --------
from app_v5.database.db import upsert_musica, listar  # upsert_musica inclui link_spotify na assinatura  # :contentReference[oaicite:1]{index=1}
from app_v5.recom.knn_recommender import recomendar_por_audio, preparar_base_escalada

# -------- Features --------
try:
    from app_v5.audio.extrator_fft import extrair_features_completas
except Exception:
    extrair_features_completas = None

import numpy as np
import librosa


# ===================== helpers =====================
def _pad_or_trim(vec, target_len: int):
    v = np.asarray(vec, dtype="float32").ravel()
    if len(v) == target_len:
        return v
    if len(v) > target_len:
        return v[:target_len]
    out = np.zeros((target_len,), dtype="float32")
    out[: len(v)] = v
    return out

def _extract_features(y, sr) -> np.ndarray:
    if extrair_features_completas is not None:
        return extrair_features_completas(y, sr)
    # fallback leve (coerente com CLI se extrator não estiver disponível)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    feats = [S.mean(axis=1), S.std(axis=1)]
    mf = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
    feats += [mf.mean(axis=1), mf.std(axis=1)]
    vec = np.concatenate(feats, axis=0).astype("float32")
    return _pad_or_trim(vec, int(EXPECTED_FEATURE_LENGTH or 0))

def _fmt_pct(sim: float) -> str:
    return f"{max(0.0, float(sim))*100.0:.2f}%"


# ===================== ingest core (CLI-like) =====================
def _ingest_with_cli_metadata(arquivo: Path, *, youtube_meta: Dict[str, Any] | None, sr: int) -> Dict[str, Any]:
    """
    Replica o fluxo da CLI:
      1) extrai features
      2) monta hints (YouTube -> _parse_title_tokens)
      3) resolve metadados via enrich_metadata
      4) decide link_youtube
      5) grava via upsert_musica
    Se 'accepted' vier False, aplica fallback suave (não aborta, a menos que BOT_STRICT_METADATA=1).
    """
    if not arquivo.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {arquivo}")

    # 1) features
    y, _sr = librosa.load(str(arquivo), sr=sr, mono=True)
    vec = _extract_features(y, _sr)
    duration_sec = float(librosa.get_duration(y=y, sr=_sr))

    # 2) hints
    yt_title = yt_uploader = yt_thumb = yt_url = None
    artist_hint = track_hint = album_hint = None

    if youtube_meta:
        yt_title = (youtube_meta.get("title") or "").strip() or None
        yt_uploader = (youtube_meta.get("uploader") or youtube_meta.get("channel") or "").strip() or None
        yt_url = (youtube_meta.get("webpage_url") or "").strip() or None

        thumbs = youtube_meta.get("thumbnails") or []
        if youtube_meta.get("thumbnail"):
            yt_thumb = youtube_meta["thumbnail"]
        elif thumbs and isinstance(thumbs, list):
            try:
                yt_thumb = sorted(thumbs, key=lambda t: t.get("preference", 0))[-1].get("url")
            except Exception:
                yt_thumb = thumbs[-1].get("url")

        a, t, alb = _parse_title_tokens(yt_title or "")
        artist_hint = a or yt_uploader
        track_hint  = t
        album_hint  = alb
        if not artist_hint:
            artist_hint = yt_uploader
    else:
        a, t, alb = _parse_title_tokens(arquivo.stem)
        artist_hint, track_hint, album_hint = a, t, alb

    meta_hints = {"artist": artist_hint, "title": track_hint, "album": album_hint, "thumb": yt_thumb}

    # 3) resolve metadados
    md = {}
    try:
        md = enrich_metadata(arquivo, duration_sec, meta_hints) or {}
    except Exception as e:
        log.warning("enrich_metadata falhou (%s). Seguindo com fallback suave.", e)
        md = {}

    accepted = bool(md.get("accepted"))

    # 4) decisão de preenchimento (estrito x suave)
    if accepted:
        titulo  = md.get("title")
        artista = md.get("artist")
        album   = md.get("album")
        genero  = md.get("genres")
        capa    = md.get("cover")
        link_sp = md.get("link_spotify")
    else:
        if BOT_STRICT_METADATA:
            # Comportamento antigo (abortava o fluxo)
            raise RuntimeError("Metadados não confiáveis para este áudio (STRICT_METADATA ativo).")
        # Fallback SUAVE: usa o que tiver de md; completa com hints do YouTube/filename
        titulo  = md.get("title")  or track_hint  or yt_title or arquivo.stem
        artista = md.get("artist") or artist_hint or yt_uploader or "desconhecido"
        album   = md.get("album")  or album_hint
        genero  = md.get("genres")
        capa    = md.get("cover")  or yt_thumb
        link_sp = md.get("link_spotify")

    # 5) decide link a salvar
    link_final = yt_url or buscar_youtube_link(artista, titulo)

    # 6) grava no catálogo (ASSINATURA do seu db.py)
    rid = upsert_musica(
        nome=arquivo.name,
        caracteristicas=vec,
        artista=artista,
        titulo=titulo,
        album=album,
        genero=genero,
        capa_album=capa,
        link_youtube=link_final,
        link_spotify=link_sp,
    )  # upsert_musica espera link_spotify também.  # :contentReference[oaicite:2]{index=2}

    return {
        "id": rid,
        "titulo": titulo,
        "artista": artista,
        "album": album,
        "genero": genero,
        "capa_album": capa,
        "link": link_final or "",
        "caminho": str(arquivo),
        "accepted": accepted
    }


# ===================== API usada pelo bot =====================
def recommend_from_audio_file(path: str | Path, k: int = 3, sr: int = 22050) -> Dict[str, Any]:
    p = Path(path)
    try:
        q = _ingest_with_cli_metadata(p, youtube_meta=None, sr=sr)
    except Exception as e:
        log.exception("Erro em recommend_from_audio_file")
        return {"status": "error", "message": str(e)}

    try:
        recs = recomendar_por_audio(p, k=k, sr=sr, excluir_nome=p.name) or []
        items = [{
            "id": int(r.get("id") or 0),
            "titulo": r.get("titulo") or r.get("nome") or "",
            "artista": r.get("artista") or "",
            "link": r.get("caminho") or r.get("link_spotify") or r.get("link_youtube") or "",
            "similaridade": float(r.get("similaridade") or 0.0),
            "similaridade_fmt": _fmt_pct(float(r.get("similaridade") or 0.0)),
        } for r in recs]
    except Exception as e:
        return {"status": "error", "message": f"Recomendador indisponível: {e}"}

    return {"status": "ok", "query": q, "items": items}


def recommend_from_youtube(url: str, k: int = 3, sr: int = 22050) -> Dict[str, Any]:
    """
    Exige **link do YouTube** (mesmo fluxo da CLI). Baixa, enriquece metadados e recomenda.
    """
    try:
        items = baixar_audio_youtube(url, Path(DOWNLOADS_DIR), playlist=False) or []
        if not items:
            return {"status": "error", "message": "Nenhum arquivo baixado do YouTube."}
        it = items[0]
        p = Path(it["path"])
        q = _ingest_with_cli_metadata(p, youtube_meta=(it.get("meta") or {}), sr=sr)
    except Exception as e:
        log.exception("Erro em recommend_from_youtube")
        return {"status": "error", "message": str(e)}

    try:
        recs = recomendar_por_audio(p, k=k, sr=sr, excluir_nome=p.name) or []
        items_out = [{
            "id": int(r.get("id") or 0),
            "titulo": r.get("titulo") or r.get("nome") or "",
            "artista": r.get("artista") or "",
            "link": r.get("caminho") or r.get("link_spotify") or r.get("link_youtube") or "",
            "similaridade": float(r.get("similaridade") or 0.0),
            "similaridade_fmt": _fmt_pct(float(r.get("similaridade") or 0.0)),
        } for r in recs]
    except Exception as e:
        return {"status": "error", "message": f"Recomendador indisponível: {e}"}

    return {"status": "ok", "query": q, "items": items_out}


def process_playlist_youtube(url: str, sr: int = 22050) -> Dict[str, Any]:
    """
    Baixa e processa playlist/álbum do YouTube (bulk) usando o mesmo fluxo.
    """
    try:
        out_dir = Path(DOWNLOADS_DIR); out_dir.mkdir(parents=True, exist_ok=True)
        items = baixar_audio_youtube(url, out_dir, playlist=True) or []
        ok = 0
        for it in items:
            p = Path(it["path"])
            try:
                _ingest_with_cli_metadata(p, youtube_meta=(it.get("meta") or {}), sr=sr)
                ok += 1
            except Exception as e:
                log.warning("Falha ao processar item da playlist: %s", e)
        return {"status": "ok", "total": len(items), "processados": ok}
    except Exception as e:
        log.exception("Erro em process_playlist_youtube")
        return {"status": "error", "message": str(e)}


def recalibrate() -> Dict[str, Any]:
    try:
        Xs, ids, metas, scaler = preparar_base_escalada()
        n_items = int(Xs.shape[0]) if hasattr(Xs, "shape") else len(Xs)
        n_dims = int(Xs.shape[1]) if hasattr(Xs, "shape") and len(Xs.shape) > 1 else (len(Xs[0]) if Xs and hasattr(Xs[0], '__len__') else 0)
        return {"status": "ok", "itens": n_items, "dim": n_dims}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_db(limit: int = 20) -> List[Dict[str, Any]]:
    try:
        return listar(limit=limit) or []
    except Exception:
        return []
