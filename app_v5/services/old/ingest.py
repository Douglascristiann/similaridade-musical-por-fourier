# app_v5/services/ingest.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any, List
import json, logging, traceback
import librosa

from app_v5.config import DOWNLOADS_DIR, COOKIEFILE_PATH, AUTO_DELETE_DOWNLOADED
from app_v5.audio.extrator_fft import extrair_features_completas
from app_v5.database.db import upsert_musica
from app_v5.recom.knn_recommender import recomendar_por_audio, preparar_base_escalada
# =======================================================================
# CORREÇÃO: Importa o nome público da função, sem o underscore
# =======================================================================
from app_v5.services.metadata import enrich_metadata, parse_title_tokens
from app_v5.services.youtube_backfill import buscar_youtube_link

log = logging.getLogger("FourierMatch")

def _formatar_links(meta: Dict[str, Any]) -> str:
    sp = (meta.get("spotify") or meta.get("link_spotify") or "").strip()
    yt = (meta.get("youtube") or meta.get("link_youtube") or "").strip()
    cam = (meta.get("caminho") or "").strip()

    def _is_spotify(u: str) -> bool:
        return u.startswith("spotify:track:") or "open.spotify.com" in u

    def _is_youtube(u: str) -> bool:
        return ("youtube.com" in u) or ("youtu.be" in u)

    if cam:
        if not sp and _is_spotify(cam):
            sp = "https://open.spotify.com/track/" + cam.split(":")[-1] if cam.startswith("spotify:track:") else cam
        if not yt and _is_youtube(cam):
            yt = _clean_link(cam)

    linhas = []
    if sp:
        linhas.append(f"🎧 Spotify: {sp}")
    else:
        linhas.append("🎧 Spotify: Não foi possível encontrar essa música no Spotify")
    if yt:
        linhas.append(f"▶️ YouTube: {yt}")

    return "\n".join(linhas)

def _bar_from_pct(pct: float, width: int = 20) -> str:
    pct = max(0.0, min(100.0, pct))
    fill = int(round(pct * width / 100.0))
    return "[" + ("█" * fill) + ("─" * (width - fill)) + "]"

def _clean_link(url: str) -> str:
    try:
        from urllib.parse import urlparse, parse_qs
        if not url:
            return url
        pu = urlparse(url)
        if "youtube.com" in pu.netloc and pu.path == "/watch":
            q = parse_qs(pu.query)
            v = q.get("v", [None])[0]
            if v:
                return f"https://www.youtube.com/watch?v={v}"
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
        for ln in _formatar_links(r).splitlines():
            print("│ " + ln.ljust(box_w) + " │")
        print(tail + "\n")

def contar_musicas() -> Optional[int]:
    try:
        import mysql.connector
        from app_v5.config import DB_CONFIG, DB_TABLE_NAME
        with mysql.connector.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM tb_musicas") #{DB_TABLE_NAME}
                r = cur.fetchone()
                return int(r[0]) if r else 0
    except Exception:
        return None

def _extract_entries_with_paths(ydl, info_obj) -> List[Dict[str, Any]]:
    def resolve_one(item):
        base = Path(ydl.prepare_filename(item))
        mp3  = base.with_suffix(".mp3") if base.suffix.lower() != ".mp3" else base
        meta = {
            "id": item.get("id"), "title": item.get("title"),
            "uploader": item.get("uploader"), "channel": item.get("channel"),
            "artist": item.get("artist"), "track": item.get("track"),
            "webpage_url": item.get("webpage_url"), "thumbnail": item.get("thumbnail"),
            "thumbnails": item.get("thumbnails"), "playlist_title": item.get("playlist_title"),
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
        log.error("❌ yt-dlp não está instalado. Instale com: pip install yt-dlp")
        return []
        
    pasta_destino.mkdir(parents=True, exist_ok=True)
    
    ydl_opts = {
        "outtmpl": str(pasta_destino / "%(title)s-%(id)s.%(ext)s"),
        "noplaylist": not playlist, "quiet": True, "no_warnings": True,
        "prefer_ffmpeg": True, "cookiefile": str(COOKIEFILE_PATH),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        "extract_flat": False, "skip_download": False, "default_search": "ytsearch",
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

        artist_hint = track_hint = album_hint = yt_thumb = None
        if youtube_meta is None:
            side = arquivo.with_suffix(".info.json")
            if side.exists():
                try:
                    youtube_meta = json.loads(side.read_text())
                except Exception:
                    youtube_meta = None
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
                # ==========================================================
                # CORREÇÃO: Chama a função com o novo nome público
                # ==========================================================
                a2, tr2, alb2 = parse_title_tokens(t)
                track_hint = tr2 or track_hint
                if not artist_hint: artist_hint = a2
                if not album_hint:  album_hint  = alb2
        else:
            # ==========================================================
            # CORREÇÃO: Chama a função com o novo nome público
            # ==========================================================
            a3, tr3, alb3 = parse_title_tokens(arquivo.stem)
            artist_hint, track_hint, album_hint = a3, tr3, alb3

        meta_hints = {"artist": artist_hint, "title": track_hint, "album": album_hint, "thumb": yt_thumb}
        log.info("🟢 Buscando metadados (Spotify → Discogs → Deezer → Shazam)…")
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

        titulo, artista, album, genero, capa = md["title"], md["artist"], md["album"], md["genres"], md["cover"]

        link_final = (youtube_meta or {}).get("webpage_url") or origem_link
        if link_final and _is_url(link_final):
            link_final = _clean_link(link_final)
            log.info(f"🔗 Link (origem YouTube): {link_final}")
        else:
            title_q  = titulo if (titulo and titulo != arquivo.stem) else track_hint
            artist_q = artista if (artista and artista.lower() != "desconhecido") else artist_hint
            log.info("🔎 Backfill YouTube (simples yt_dlp/ytsearch1) …")
            link = buscar_youtube_link(artist_q, title_q)
            if link:
                link_final = link
                log.info(f"✅ Backfill YouTube: {link_final}")
            else:
                link_final = None
                log.info("⚠️ Backfill YouTube: nenhum link encontrado.")

        log.info("💾 Gravando no MySQL (tabela)…")
        rid = upsert_musica(
            nome=arquivo.name, caracteristicas=vec, artista=artista, titulo=titulo, album=album,
            genero=genero, capa_album=capa, link_youtube=link_final, link_spotify=md.get("link_spotify"),
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
                    a_res, d_res = str(Path(arquivo).resolve()), str(Path(DOWNLOADS_DIR).resolve())
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
    print("🛠️  Reajustando padronizador por bloco (scaler)…")
    Xs, ids, metas, scaler = preparar_base_escalada()
    if Xs.shape[0] >= 1:
        try:
            print(f"✅ Scalado {Xs.shape[0]} faixas x {Xs.shape[1]} dims.")
        except Exception:
            print(f"✅ Scalado {len(Xs)} faixas.")
    else:
        print("⚠️  Catálogo insuficiente para calibrar. Ingerir mais faixas e tentar novamente.")
        return

    try:
        path_str = input("\nArquivo de áudio para recomendar (ou Enter para pular): ").strip()
    except EOFError:
        path_str = ""

    if not path_str:
        print("➡️  Pulando recomendação por áudio. Você pode usar as opções 1/2/3 a qualquer momento.")
        return

    p = Path(path_str).expanduser()
    if str(p) in (".", "./") or p.is_dir() or (not p.exists()):
        print("⚠️  Caminho inválido (ou é uma pasta). Pulando recomendação por áudio.")
        return

    try:
        recs = recomendar_por_audio(p, k=k, sr=sr, excluir_nome=p.name)
    except Exception as e:
        print(f"❌ Erro ao recomendar por áudio: {e}")
        return

    if not recs:
        print("ℹ️  Não foi possível calcular recomendações para este arquivo.")
        return

    _print_recs_pretty(recs[:k])