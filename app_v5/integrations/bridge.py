# -*- coding: utf-8 -*-
"""
app_v5.integrations.bridge
Camada de orquestração para o BOT: baixa/ingere áudio, extrai features e retorna recomendações
em um formato estável para o menu_bot.

- Não altera a estrutura de tb_musicas.
- Compatível com db.upsert_musica que NÃO recebe 'caminho' (outras variantes também).
- Mantém fallback com yt_dlp (aceita ytsearch1:...).
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging
import inspect  # <- para compat de assinatura

log = logging.getLogger(__name__)

# ---------------- Config ----------------
try:
    from app_v5.config import DOWNLOADS_DIR, EXPECTED_FEATURE_LENGTH, BLOCK_WEIGHTS
except Exception:
    DOWNLOADS_DIR = "./downloads"
    EXPECTED_FEATURE_LENGTH = 161
    BLOCK_WEIGHTS = {"spec": 1.0, "mfcc": 1.0, "chroma": 1.0, "tonnetz": 1.0}

# ---------------- Reconhecimento & DB ----------------
try:
    from app_v5.recognition.recognizer import recognize_with_cache  # cache leve p/ título/artista
except Exception:
    def recognize_with_cache(_path: Path):
        return None

try:
    # upsert_musica: assinatura pode variar entre projetos (alguns não aceitam 'caminho')
    from app_v5.database.db import upsert_musica, listar
except Exception as e:
    upsert_musica = None
    listar = None
    log.warning("DB API parcial: %s", e)

# ---------------- Recomendação ----------------
try:
    from app_v5.recom.knn_recommender import recomendar_por_audio, preparar_base_escalada
except Exception:
    recomendar_por_audio = None
    preparar_base_escalada = None

# ---------------- Download / Ingest ----------------
try:
    # baixar_audio_youtube retorna uma lista de itens com .path e .meta
    from app_v5.services.ingest import baixar_audio_youtube
except Exception:
    baixar_audio_youtube = None

# Extrator oficial (se disponível); caso contrário usamos Librosa puro
try:
    from app_v5.audio.extrator_fft import extrair_features_completas
except Exception:
    extrair_features_completas = None

# Librosa fallback (não obrigatório em runtime se extrator oficial existir)
try:
    import numpy as np
    import librosa
except Exception:
    librosa = None
    np = None

# ---------------- Util ----------------
def _pad_or_trim(vec, target_len: int):
    import numpy as _np  # sempre local para evitar shadow
    v = _np.asarray(vec, dtype="float32").ravel()
    if len(v) == target_len:
        return v
    if len(v) > target_len:
        return v[:target_len]
    out = _np.zeros((target_len,), dtype="float32")
    out[: len(v)] = v
    return out

def _extract_features(y, sr) -> "np.ndarray":
    """
    Extrai vetor único de features (compatível com EXPECTED_FEATURE_LENGTH).
    - Usa extrair_features_completas se disponível.
    - Caso contrário, extrai blocos básicos (stft/mfcc/chroma/tonnetz) e concatena média+desvio.
    """
    if extrair_features_completas is not None:
        vec = extrair_features_completas(y, sr)  # já retorna np.ndarray correto
        return vec

    if librosa is None or np is None:
        raise RuntimeError("Sem backend de features (librosa/np) e sem extrator oficial.")

    feats = []
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    feats.append(S.mean(axis=1)); feats.append(S.std(axis=1))
    mf = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
    feats.append(mf.mean(axis=1)); feats.append(mf.std(axis=1))
    ch = librosa.feature.chroma_stft(S=S, sr=sr)
    feats.append(ch.mean(axis=1)); feats.append(ch.std(axis=1))
    try:
        tn = librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr)
        feats.append(tn.mean(axis=1)); feats.append(tn.std(axis=1))
    except Exception:
        pass
    vec = np.concatenate(feats, axis=0).astype("float32")
    return _pad_or_trim(vec, int(EXPECTED_FEATURE_LENGTH or 0))

def _fmt_pct(sim: float) -> str:
    pct = max(0.0, float(sim)) * 100.0
    return f"{pct:.2f}%"

# ----------- Compat: upsert_musica com assinatura variável -----------
def _upsert_musica_compat(**kwargs) -> int:
    """
    Filtra kwargs para apenas aqueles suportados por app_v5.database.db.upsert_musica.
    Ex.: se o seu upsert_musica NÃO aceita 'caminho', o argumento é descartado.
    """
    if upsert_musica is None:
        raise RuntimeError("API de DB indisponível (upsert_musica).")
    sig = inspect.signature(upsert_musica)
    accepted = set(sig.parameters.keys())
    filtered = {k: v for k, v in kwargs.items() if k in accepted}
    # alguns projetos definem parâmetros posicionais obrigatórios; portanto passamos nomeados.
    return upsert_musica(**filtered)

# --------------- Core ingest ---------------
def _ingest_core(file_path: Path, origem_link: Optional[str], sr: int = 22050) -> Dict[str, Any]:
    """
    Extrai features do arquivo, resolve meta básica (título/artista via Shazam cache) e faz upsert em DB.
    Retorna um dict 'query' com id, titulo, artista e caminho local (para depuração).
    """
    if librosa is None:
        raise RuntimeError("librosa não instalado (necessário para carregar áudio).")
    y, _sr = librosa.load(str(file_path), sr=sr, mono=True)
    vec = _extract_features(y, _sr)

    titulo = file_path.stem
    artista = "desconhecido"
    try:
        rec = recognize_with_cache(file_path)
        if getattr(rec, "title", None):
            titulo = rec.title
        if getattr(rec, "artist", None):
            artista = rec.artist
    except Exception:
        pass

    # Chamada compatível com diversos schemas/assinaturas de DB
    rid = _upsert_musica_compat(
        nome=file_path.name,
        caracteristicas=vec,
        artista=artista,
        titulo=titulo,
        album=None, genero=None, capa_album=None,
        link_youtube=str(origem_link or ""),
        link_spotify=None,
        caminho=str(file_path)  # será ignorado se sua upsert_musica não aceitar
    )

    return {
        "id": rid,
        "titulo": titulo,
        "artista": artista,
        "caminho": str(file_path),  # apenas retorno informativo (não vai ao DB)
        "origem": origem_link or ""
    }

# ---------------- Public API ----------------
def recommend_from_audio_file(path: str | Path, k: int = 3, sr: int = 22050) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"status": "error", "message": f"Arquivo não encontrado: {p}"}
    if recomendar_por_audio is None:
        return {"status": "error", "message": "Módulo de recomendação indisponível (recomendar_por_audio)."}
    try:
        q = _ingest_core(p, origem_link=None, sr=sr)
        recs = recomendar_por_audio(p, k=k, sr=sr, excluir_nome=p.name) or []
        items = [{
            "id": int(r.get("id") or 0),
            "titulo": r.get("titulo") or r.get("nome") or "",
            "artista": r.get("artista") or "",
            "link": r.get("caminho") or r.get("link_youtube") or "",
            "similaridade": float(r.get("similaridade") or 0.0),
            "similaridade_fmt": _fmt_pct(float(r.get("similaridade") or 0.0)),
        } for r in recs]
        return {"status": "ok", "query": q, "items": items}
    except Exception as e:
        log.exception("Erro em recommend_from_audio_file")
        return {"status": "error", "message": str(e)}

def recommend_from_youtube(url: str, k: int = 3, sr: int = 22050) -> Dict[str, Any]:
    out_dir = Path(DOWNLOADS_DIR); out_dir.mkdir(parents=True, exist_ok=True)
    dl = []
    if baixar_audio_youtube is not None:
        try:
            dl = baixar_audio_youtube(url, out_dir, playlist=False)
        except TypeError:
            try:
                dl = baixar_audio_youtube(url, out_dir)
            except Exception as e:
                log.warning("baixar_audio_youtube falhou; tentando fallback: %s", e)
    if not dl:
        # fallback com yt_dlp
        try:
            from yt_dlp import YoutubeDL
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav", "preferredquality": "0"}],
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if "entries" in info and info["entries"]:
                    entry = info["entries"][0]
                    p = Path(ydl.prepare_filename(entry)).with_suffix(".wav")
                    dl = [{"path": p, "meta": entry}]
                else:
                    p = Path(ydl.prepare_filename(info)).with_suffix(".wav")
                    dl = [{"path": p, "meta": info}]
        except Exception as e:
            return {"status": "error", "message": f"Falha no fallback yt_dlp: {e}"}

    if not dl:
        return {"status": "error", "message": "Falha ao baixar áudio do YouTube (pipeline e fallback indisponíveis)."}

    it = dl[0]
    p = Path(it["path"])
    link = (it.get("meta") or {}).get("webpage_url") or url
    if recomendar_por_audio is None:
        return {"status": "error", "message": "Módulo de recomendação indisponível (recomendar_por_audio)."}

    try:
        q = _ingest_core(p, origem_link=link, sr=sr)
        recs = recomendar_por_audio(p, k=k, sr=sr, excluir_nome=p.name) or []
        out = [{
            "id": int(r.get("id") or 0),
            "titulo": r.get("titulo") or r.get("nome") or "",
            "artista": r.get("artista") or "",
            "link": r.get("caminho") or r.get("link_youtube") or "",
            "similaridade": float(r.get("similaridade") or 0.0),
            "similaridade_fmt": _fmt_pct(float(r.get("similaridade") or 0.0)),
        } for r in recs]
        return {"status": "ok", "query": q, "items": out}
    except Exception as e:
        log.exception("Erro em recommend_from_youtube")
        return {"status": "error", "message": str(e)}

def process_playlist_youtube(url: str, sr: int = 22050) -> Dict[str, Any]:
    """
    Baixa e processa playlist/álbum do YouTube (bulk). Retorna contagem básica.
    """
    if baixar_audio_youtube is None:
        return {"status": "error", "message": "Pipeline de download indisponível."}
    try:
        out_dir = Path(DOWNLOADS_DIR); out_dir.mkdir(parents=True, exist_ok=True)
        items = baixar_audio_youtube(url, out_dir, playlist=True) or []
        ok = 0
        for it in items:
            p = Path(it["path"])
            link = (it.get("meta") or {}).get("webpage_url") or url
            try:
                _ingest_core(p, origem_link=link, sr=sr)
                ok += 1
            except Exception:
                log.exception("Falha ao processar item da playlist")
        return {"status": "ok", "total": len(items), "processados": ok}
    except Exception as e:
        log.exception("Erro em process_playlist_youtube")
        return {"status": "error", "message": str(e)}

def recalibrate() -> Dict[str, Any]:
    """
    Recalibra scaler por bloco (preparar_base_escalada) e retorna dimensão resultante.
    """
    if preparar_base_escalada is None:
        return {"status": "error", "message": "Preparador indisponível (preparar_base_escalada)."}
    try:
        Xs, ids, metas, scaler = preparar_base_escalada()
        try:
            n_items = int(Xs.shape[0]); n_dims = int(Xs.shape[1])
        except Exception:
            n_items, n_dims = len(Xs), len(Xs[0]) if Xs and hasattr(Xs[0], '__len__') else 0
        return {"status": "ok", "itens": n_items, "dim": n_dims}
    except Exception as e:
        log.exception("Erro em recalibrate")
        return {"status": "error", "message": str(e)}

def list_db(limit: int = 20):
    if listar is None:
        return []
    try:
        return listar(limit=limit)
    except Exception as e:
        log.warning("listar() falhou: %s", e)
        return []
