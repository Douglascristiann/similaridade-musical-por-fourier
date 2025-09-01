# -*- coding: utf-8 -*-
"""
app_v5.integrations.bridge (versão simples)
-------------------------------------------
Fluxo idêntico ao da CLI para metadados:
- usa app_v5.services.ingest.baixar_audio_youtube para baixar
- usa app_v5.services.metadata.enrich_metadata para preencher título/artist/álbum/gênero/capa
- usa app_v5.services.youtube_backfill.buscar_youtube_link como fallback de link quando for áudio local
- grava via app_v5.database.db.upsert_musica (mesma assinatura do projeto)
Sem descoberta dinâmica, sem aceitar ID puro: **exige link do YouTube** para a opção 2.
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import logging

log = logging.getLogger(__name__)

# ---------------- Config ----------------
try:
    from app_v5.config import DOWNLOADS_DIR, EXPECTED_FEATURE_LENGTH
except Exception:
    DOWNLOADS_DIR = "./downloads"
    EXPECTED_FEATURE_LENGTH = 161

# ---------------- Integração (mesmo fluxo da CLI) ----------------
from app_v5.services.ingest import baixar_audio_youtube
from app_v5.services.metadata import enrich_metadata, _parse_title_tokens
from app_v5.services.youtube_backfill import buscar_youtube_link

# ---------------- DB/Recomendador ----------------
from app_v5.database.db import upsert_musica, listar
from app_v5.recom.knn_recommender import recomendar_por_audio, preparar_base_escalada

# ---------------- Features ----------------
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
    Reproduz o fluxo do services/ingest.processar_audio_local, mas retornando um dict adequado ao bot.
    - Extrai features
    - Monta hints de metadados a partir do YouTube (se houver) ou do nome do arquivo
    - Resolve metadados via services.metadata.enrich_metadata
    - Decide link_youtube final (origem ou backfill simples)
    - Grava no catálogo via upsert_musica
    """
    if not arquivo.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {arquivo}")

    # 1) features
    y, _sr = librosa.load(str(arquivo), sr=sr, mono=True)
    vec = _extract_features(y, _sr)
    duration_sec = float(librosa.get_duration(y=y, sr=_sr))

    # 2) hints (iguais ao CLI)
    yt_title = yt_uploader = yt_thumb = None
    artist_hint = track_hint = album_hint = None

    if youtube_meta:
        yt_title = (youtube_meta.get("title") or "").strip() or None
        yt_uploader = (youtube_meta.get("uploader") or youtube_meta.get("channel") or "").strip() or None
        # thumbnails → pega a última (geralmente maior)
        yt_thumb = (youtube_meta.get("thumbnail") or None)
        if not yt_thumb:
            thumbs = youtube_meta.get("thumbnails") or []
            if thumbs and isinstance(thumbs, list):
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

    # 3) resolve metadados oficiais (Spotify → Discogs → Deezer → Shazam)
    md = enrich_metadata(arquivo, duration_sec, meta_hints)
    if not md.get("accepted", False):
        raise RuntimeError("Metadados não confiáveis para este áudio (STRICT_METADATA ativo).")

    titulo  = md.get("title")
    artista = md.get("artist")
    album   = md.get("album")
    genero  = md.get("genres")
    capa    = md.get("cover")

    # 4) decide link a salvar (como na CLI)
    link_final = (youtube_meta or {}).get("webpage_url") if youtube_meta else None
    if not link_final:
        # backfill simples (yt_dlp/ytsearch1)
        title_q  = titulo if (titulo and titulo != arquivo.stem) else track_hint
        artist_q = artista if (artista and artista.lower() != "desconhecido") else artist_hint
        link_final = buscar_youtube_link(artist_q, title_q)

    # 5) grava no catálogo (mesma assinatura do projeto)
    rid = upsert_musica(
        nome=arquivo.name,
        caracteristicas=vec,
        artista=artista,
        titulo=titulo,
        album=album,
        genero=genero,
        capa_album=capa,
        link_youtube=link_final,
        link_spotify=md.get("link_spotify"),
    )  # assinatura com link_spotify está no seu db.py.  # :contentReference[oaicite:1]{index=1}

    return {
        "id": rid,
        "titulo": titulo,
        "artista": artista,
        "album": album,
        "genero": genero,
        "capa_album": capa,
        "link": link_final or "",
        "caminho": str(arquivo),
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
