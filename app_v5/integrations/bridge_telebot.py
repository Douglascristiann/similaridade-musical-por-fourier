from __future__ import annotations
import logging, sys
from pathlib import Path
from typing import Optional, Dict, Any, List

import librosa

# ajustar path para rodar como módulo ou script
ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app_v5"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# config (v5 mantém config dentro do pacote)
try:
    from app_v5.config import DOWNLOADS_DIR
except Exception:
    from config import DOWNLOADS_DIR  # fallback raro

from app_v5.services.ingest import baixar_audio_youtube              # v5 expõe esta função
from app_v5.audio.extrator_fft import extrair_features_completas
from app_v5.recognition.recognizer import recognize_with_cache
from app_v5.database.db import upsert_musica, listar
from app_v5.recom.knn_recommender import recomendar_por_audio

log = logging.getLogger(__name__)

def _fmt_pct(sim: float) -> str:
    sim = float(sim)
    pct = max(0.0, sim) * 100.0
    return f"{pct:.2f}%"

def _ingest_core(file_path: Path, origem_link: Optional[str], sr: int = 22050) -> Dict[str, Any]:
    y, _sr = librosa.load(str(file_path), sr=sr, mono=True)
    vec = extrair_features_completas(y, _sr)

    titulo = file_path.stem
    artista = "desconhecido"
    try:
        rec = recognize_with_cache(file_path)
        if getattr(rec, "title", None):  titulo  = rec.title
        if getattr(rec, "artist", None): artista = rec.artist
    except Exception:
        pass

    rid = upsert_musica(
        nome=file_path.name,
        caracteristicas=vec,
        artista=artista,
        titulo=titulo,
        album=None, genero=None, capa_album=None,
        link_youtube=origem_link or str(file_path.resolve()),
    )
    return {"id": rid, "arquivo": str(file_path), "titulo": titulo, "artista": artista, "link": origem_link or ""}

def recommend_from_audio_file(path: str | Path, k: int = 3, sr: int = 22050) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"status": "error", "message": f"Arquivo não encontrado: {p}"}
    q = _ingest_core(p, origem_link=None, sr=sr)
    recs = (recomendar_por_audio(p, k=k, sr=sr, excluir_nome=p.name) or [])
    items = [{
        "id": int(r.get("id") or 0),
        "titulo": r.get("titulo") or r.get("nome") or "",
        "artista": r.get("artista") or "",
        "link": r.get("caminho") or r.get("link_youtube") or "",
        "similaridade": float(r.get("similaridade") or 0.0),
        "similaridade_fmt": _fmt_pct(float(r.get("similaridade") or 0.0)),
    } for r in recs]
    return {"status": "ok", "query": q, "items": items}

def recommend_from_youtube(url: str, k: int = 3, sr: int = 22050) -> Dict[str, Any]:
    Path(DOWNLOADS_DIR).mkdir(parents=True, exist_ok=True)
    items = baixar_audio_youtube(url, Path(DOWNLOADS_DIR), playlist=False)
    if not items:
        return {"status": "error", "message": "Falha ao baixar áudio do YouTube."}
    it = items[0]
    p = Path(it["path"])
    link = (it.get("meta") or {}).get("webpage_url") or url
    q = _ingest_core(p, origem_link=link, sr=sr)
    recs = (recomendar_por_audio(p, k=k, sr=sr, excluir_nome=p.name) or [])
    out = [{
        "id": int(r.get("id") or 0),
        "titulo": r.get("titulo") or r.get("nome") or "",
        "artista": r.get("artista") or "",
        "link": r.get("caminho") or r.get("link_youtube") or "",
        "similaridade": float(r.get("similaridade") or 0.0),
        "similaridade_fmt": _fmt_pct(float(r.get("similaridade") or 0.0)),
    } for r in recs]
    return {"status": "ok", "query": q, "items": out}

def list_db(limit: int = 20):
    return listar(limit=limit)
