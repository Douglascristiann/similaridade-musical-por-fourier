# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any, List
import json, logging, traceback
import numpy as np
import librosa

from app_v4_new.config import DOWNLOADS_DIR, COOKIEFILE_PATH, AUTO_DELETE_DOWNLOADED
from app_v4_new.audio.extrator_fft import extrair_features_completas
from app_v4_new.database.db import upsert_musica
from app_v4_new.recom.knn_recommender import recomendar_por_audio, preparar_base_escalada
from app_v4_new.services.metadata import enrich_metadata, _parse_title_tokens
from app_v4_new.services.youtube_backfill import find_youtube_link

log = logging.getLogger("FourierMatch")

def _bar_from_pct(pct: float, width: int = 20) -> str:
    pct = max(0.0, min(100.0, pct))
    fill = int(round(pct * width / 100.0))
    return "[" + ("█" * fill) + ("─" * (width - fill)) + "]"

def _clean_link(url: str) -> str:
    try:
        from urllib.parse import urlparse, parse_qs
        if not url: return url
        pu = urlparse(url)
        if "youtube.com" in pu.netloc and pu.path == "/watch":
            q = parse_qs(pu.query); v = q.get("v", [None])[0]
            if v: return f"https://www.youtube.com/watch?v={v}"
        return url
    except Exception:
        return url

def _is_url(s: str|None) -> bool:
    return isinstance(s, str) and s.startswith(("http://","https://"))

def _print_recs_pretty(recs: List[dict]) -> None:
    print("\n✨ Top 3 Recomendações Musicais ✨\n")
    medals = ["🥇","🥈","🥉"]; box_w = 69
    for i, r in enumerate(recs[:3], start=1):
        medal = medals[i-1] if i <= 3 else f"#{i}"
        titulo  = r.get("titulo") or "—"
        artista = r.get("artista") or "—"
        link    = _clean_link(r.get("caminho") or "")
        sim_f   = float(r.get("similaridade", 0.0))
        pct     = (sim_f * 100.0) if sim_f <= 1.0 else sim_f
        bar     = _bar_from_pct(pct, width=20)
        head = f"┌─{medal} Top {i} " + "─" * (box_w - len(f"{medal} Top {i} ") - 1) + "┐"
        tail = "└" + "─" * (box_w + 2) + "┘"
        print(head)
        print("│ " + (f"🎵 Título: {titulo}" ).ljust(box_w) + " │")
        print("│ " + (f"🎤 Artista: {artista}").ljust(box_w) + " │")
        print("│ " + (f"📊 Similaridade: {pct:.2f}% {bar}").ljust(box_w) + " │")
        print("│ " + (f"🔗 Link: {link}"     ).ljust(box_w) + " │")
        print(tail + "\n")

def contar_musicas() -> Optional[int]:
    try:
        import mysql.connector
        from app_v4_new.config import DB_CONFIG, DB_TABLE_NAME
        with mysql.connector.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {DB_TABLE_NAME}")
                r = cur.fetchone()
                return int(r[0]) if r else 0
    except Exception:
        return None

def _extract_entries_with_paths(ydl, info_obj) -> List[Dict[str, Any]]:
    def resolve_one(item):
        base = Path(ydl.prepare_filename(item))
        mp3  = base.with_suffix(".mp3") if base.suffix.lower() != ".mp3" else base
        meta = {
            "id": item.get("id"),
            "title": item.get("title"),
            "uploader": item.get("uploader"),
            "channel": item.get("channel"),
            "artist": item.get("artist"),
            "track": item.get("track"),
            "webpage_url": item.get("webpage_url"),
            "thumbnail": item.get("thumbnail"),
            "thumbnails": item.get("thumbnails"),
            "playlist_title": item.get("playlist_title"),
        }
        try:
            mp3.with_suffix(".info.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        except Exception:
            pass
        return {"path": mp3, "meta": meta}
    out = []
    if "entries" in info_obj and isinstance(info_obj["entries"], list):
        for it in info_obj["entries"]:
            if it: out.append(resolve_one(it))
    else:
        out.append(resolve_one(info_obj))
    return out

def baixar_audio_youtube(url: str, pasta_destino: Path, playlist: bool = False) -> List[Dict[str, Any]]:
    try:
        import yt_dlp
    except Exception:
        log.error("❌ yt-dlp não está instalado. Instale com:  pip install yt-dlp")
        return []
    pasta_destino.mkdir(parents=True, exist_ok=True)
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(pasta_destino / "%(title)s-%(id)s.%(ext)s"),
        "noplaylist": not playlist,
        "quiet": True,
        "no_warnings": True,
        "prefer_ffmpeg": True,
        "cookiefile": str(COOKIEFILE_PATH),
        "postprocessors": [{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}],
        "extract_flat": False,
        "skip_download": False,
    }
    if not COOKIEFILE_PATH.exists():
        ydl_opts.pop("cookiefile", None)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return _extract_entries_with_paths(ydl, info)
    except Exception as e:
        log.error(f"❌ Erro ao baixar: {e}")
        return []

def processar_audio_local(
    arquivo: Path,
    origem_link: str | None = None,
    enriquecer: bool = True,
    recomendar: bool = True,
    k: int = 3,
    sr: int = 22050,
    youtube_meta: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        if not arquivo.exists():
            log.error(f"❌ Arquivo não encontrado: {arquivo}")
            return

        log.info("🔧 Extraindo features…")
        y, _sr = librosa.load(str(arquivo), sr=sr, mono=True)
        vec = extrair_features_completas(y, _sr)
        duration_sec = float(librosa.get_duration(y=y, sr=_sr))

        # Extrai “hints” de metadado do sidecar .info.json (se existir) ou do nome
        artist_hint = track_hint = album_hint = yt_thumb = None
        if youtube_meta is None:
            side = arquivo.with_suffix(".info.json")
            if side.exists():
                try: youtube_meta = json.loads(side.read_text())
                except Exception: youtube_meta = None
        if youtube_meta:
            artist_hint = youtube_meta.get("artist") or youtube_meta.get("uploader") or youtube_meta.get("channel")
            track_hint  = youtube_meta.get("track")
            album_hint  = youtube_meta.get("playlist_title")
            thumbs = youtube_meta.get("thumbnails") or []
            if isinstance(thumbs, list) and thumbs:
                try:
                    thumbs_sorted = sorted(thumbs, key=lambda d: (d.get("height",0), d.get("width",0)))
                    yt_thumb = thumbs_sorted[-1].get("url")
                except Exception:
                    pass
            if not track_hint:
                t = youtube_meta.get("title") or arquivo.stem
                a2, tr2, alb2 = _parse_title_tokens(t)
                track_hint = tr2 or track_hint
                if not artist_hint: artist_hint = a2
                if not album_hint:  album_hint  = alb2
        else:
            a3, tr3, alb3 = _parse_title_tokens(arquivo.stem)
            artist_hint, track_hint, album_hint = a3, tr3, alb3

        meta_hints = {"artist": artist_hint, "title": track_hint, "album": album_hint, "thumb": yt_thumb}
        md = enrich_metadata(arquivo, duration_sec, meta_hints)
        if not md["accepted"]:
            log.warning(f"🔒 Sem metadados confiáveis para '{arquivo.name}'. Enfileirado em pendentes.csv.")
            try:
                pend = Path(__file__).resolve().parents[1] / "pendentes.csv"
                with pend.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"arquivo":str(arquivo), "hints":meta_hints}, ensure_ascii=False) + "\n")
            except Exception:
                pass
            return

        titulo  = md["title"]; artista = md["artist"]
        album   = md["album"]; genero  = md["genres"]; capa = md["cover"]

        # Decide link a salvar:
        # - Se veio do YouTube (origem_link/webpage_url), mantém
        # - Se é arquivo local, tenta backfill SEM cookies
        link_final = (youtube_meta or {}).get("webpage_url") or origem_link
        if link_final and _is_url(link_final):
            link_final = _clean_link(link_final)
        else:
            yt_link = find_youtube_link(
                artista if artista and artista != "desconhecido" else artist_hint,
                titulo  if titulo  and titulo  != arquivo.stem else track_hint,
                album or album_hint,
                duration_sec
            )
            # **Nunca** grava caminho local: se não achou, None
            link_final = yt_link or None

        log.info("💾 Gravando no MySQL (tabela)…")
        rid = upsert_musica(
            nome=arquivo.name,
            caracteristicas=vec,
            artista=artista,
            titulo=titulo,
            album=album,
            genero=genero,
            capa_album=capa,
            link_youtube=link_final,
        )
        log.info(f"✅ Indexado id={rid}  {arquivo.name}  →  {titulo} — {artista}")

        if recomendar:
            log.info("🤝 Gerando recomendações…")
            recs = recomendar_por_audio(arquivo, k=k, sr=sr, excluir_nome=arquivo.name)
            if not recs:
                print("\nℹ️  Sem vizinhos suficientes ainda. Ingerir mais faixas ajuda.")
            else:
                _print_recs_pretty(recs)

    except Exception as e:
        log.error(f"❌ Falha ao processar '{arquivo}': {e}")
        log.debug(traceback.format_exc())
    finally:
        try:
            if AUTO_DELETE_DOWNLOADED:
                try:
                    is_download = Path(arquivo).resolve().is_relative_to(Path(DOWNLOADS_DIR).resolve())
                except Exception:
                    a_res = str(Path(arquivo).resolve()); d_res = str(Path(DOWNLOADS_DIR).resolve())
                    is_download = a_res.startswith(d_res)
                if is_download:
                    side = Path(arquivo).with_suffix(".info.json")
                    if side.exists(): side.unlink()
                    if Path(arquivo).exists(): Path(arquivo).unlink()
        except Exception:
            pass

def processar_link_youtube(url: str, enriquecer: bool = True, recomendar: bool = True, sr: int = 22050) -> None:
    items = baixar_audio_youtube(url, DOWNLOADS_DIR, playlist=False)
    if not items:
        log.warning("Nenhum arquivo baixado.")
        return
    for it in items:
        link_individual = (it.get("meta") or {}).get("webpage_url") or url
        processar_audio_local(it["path"], origem_link=link_individual, enriquecer=enriquecer, recomendar=recomendar, sr=sr, youtube_meta=it.get("meta"))

def processar_playlist_youtube(url: str, enriquecer: bool = True, sr: int = 22050) -> None:
    items = baixar_audio_youtube(url, DOWNLOADS_DIR, playlist=True)
    if not items:
        log.warning("Nenhum item baixado da playlist.")
        return
    log.info(f"▶️ Playlist: {len(items)} itens baixados.")
    for i, it in enumerate(items, 1):
        log.info(f"[{i}/{len(items)}] {it['path'].name}")
        link_individual = (it.get("meta") or {}).get("webpage_url") or url
        processar_audio_local(it["path"], origem_link=link_individual, enriquecer=enriquecer, recomendar=False, sr=sr, youtube_meta=it.get("meta"))
    log.info("✅ Playlist processada.")

def recalibrar_e_recomendar(k: int = 3, sr: int = 22050) -> None:
    log.info("🛠️  Reajustando padronizador por bloco (scaler)…")
    Xs, ids, metas, scaler = preparar_base_escalada()
    log.info(f"✅ Scalado {Xs.shape[0]} faixas x {Xs.shape[1]} dims.\n")
    f = Path(input("Arquivo de áudio para recomendar (ou Enter para pular): ").strip() or "")
    if f.exists():
        recs = recomendar_por_audio(f, k=k, sr=sr, excluir_nome=f.name)
        if recs: _print_recs_pretty(recs)
        else: print("Nenhuma recomendação encontrada.")
