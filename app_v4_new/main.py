# === main.py (app_v4_new) — pronto para rodar com: python3 main.py ===
import os
import sys
import argparse
from pathlib import Path
import traceback
import logging
import re
import json
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, Tuple, List

import librosa

# --- Ajuste de caminho para importar como script ou pacote ---
PKG_DIR = os.path.dirname(os.path.abspath(__file__))          # …/app_v4_new
ROOT_DIR = os.path.dirname(PKG_DIR)                           # …/
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if PKG_DIR not in sys.path:
    sys.path.insert(0, PKG_DIR)

# --- Imports da app ---
from app_v4_new.config import (
    APP_NAME, APP_VERSION, DOWNLOADS_DIR, COOKIEFILE_PATH, DISCOGS_TOKEN
)
try:
    from app_v4_new.config import AUTO_DELETE_DOWNLOADED
except Exception:
    AUTO_DELETE_DOWNLOADED = True

try:
    from app_v4_new.config import STRICT_METADATA, INSERT_ON_LOW_CONFIDENCE
except Exception:
    STRICT_METADATA = True
    INSERT_ON_LOW_CONFIDENCE = False

from app_v4_new.audio.extrator_fft import extrair_features_completas
from app_v4_new.database.db import criar_tabela, upsert_musica, listar
from app_v4_new.recom.knn_recommender import (
    recomendar_por_audio, preparar_base_escalada
)
from app_v4_new.recognition.recognizer import recognize_with_cache

# Spotify (opcional, mas recomendável)
try:
    from app_v4_new.integrations.spotify import enrich_from_spotify
    _HAS_SPOTIFY = True
except Exception:
    _HAS_SPOTIFY = False

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("FourierMatch")

BANNER = r"""
   ______                     _            __  ___      __      __     
  / ____/___  __  _______  __(_)___  ___  /  |/  /___ _/ /___ _/ /____ 
 / / __/ __ \/ / / / ___/ / / / __ \/ _ \/ /|_/ / __ `/ / __ `/ __/ _ \
/ /_/ / /_/ / /_/ (__  ) /_/ / / / /  __/ /  / / /_/ / / /_/ / /_/  __/
\____/\____/\__,_/____/\__, /_/ /_/\___/_/  /_/\__,_/_/\__,_/\__/\___/ 
                      /____/          Similaridade musical por Fourier
"""

UNIVERSIDADE = "🏫  Universidade Paulista — Curso de Sistemas de Informação"
CRIADORES    = "👨‍💻  Criadores: Douglas Cristian da Cunha & Fábio Silva Matos Filho"
TCC_TITULO   = "📚  Uma Abordagem Baseada em Análise Espectral para Recomendação Musical"

# -------------------- Contagem de músicas no DB --------------------
def contar_musicas() -> Optional[int]:
    """Conta quantas músicas existem na tabela configurada."""
    try:
        import mysql.connector  # depende de mysql-connector-python
        from app_v4_new.config import DB_CONFIG, DB_TABLE_NAME
        with mysql.connector.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {DB_TABLE_NAME}")
                row = cur.fetchone()
                if not row:
                    return 0
                return int(row[0])
    except Exception as e:
        log.debug(f"[DB] Falha ao contar músicas: {e}")
        return None

# -------------------- Util: formatação / impressão --------------------
def _fmt_pct(sim: float) -> str:
    pct = max(0.0, float(sim)) * 100.0
    return f"{pct:.2f}%"

def _print_header() -> None:
    os.system("")
    print(BANNER)
    print(f"🎵  {APP_NAME} v{APP_VERSION}")
    print(UNIVERSIDADE)
    print(CRIADORES)
    print(TCC_TITULO)
    n = contar_musicas()
    if n is not None:
        print(f"📦  Catálogo atual: {n} música(s) no banco")
    print("-" * 72)

def _format_table(rows, columns) -> str:
    if not rows:
        return ""
    widths = [len(c) for c in columns]
    srows = []
    for r in rows:
        line = []
        for i, c in enumerate(columns):
            v = r.get(c, "")
            v = "" if v is None else str(v)
            widths[i] = max(widths[i], len(v))
            line.append(v)
        srows.append(line)
    sep = "+".join("-" * (w + 2) for w in widths)
    out = []
    header = " | ".join(c.ljust(w) for c, w in zip(columns, widths))
    out.append(header)
    out.append(sep)
    for line in srows:
        out.append(" | ".join(v.ljust(w) for v, w in zip(line, widths)))
    return "\n".join(out)

# ===== Novo: impressão bonita do Top 3 =====
def _truncate(s: str, maxlen: int) -> str:
    return s if len(s) <= maxlen else s[:maxlen - 1] + "…"

def _bar_from_pct(pct: float, width: int = 20) -> str:
    """Gera barra de 0–100% em largura fixa."""
    pct = max(0.0, min(100.0, pct))
    fill = int(round(pct * width / 100.0))
    return "[" + ("█" * fill) + ("─" * (width - fill)) + "]"

def _clean_link(url: str) -> str:
    """Remove parâmetros de playlist e deixa link canônico do vídeo."""
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

def _print_recs_pretty(recs: List[dict]) -> None:
    print("\n✨ Top 3 Recomendações Musicais ✨\n")
    medals = ["🥇", "🥈", "🥉"]
    box_w = 69  # largura do conteúdo dentro da moldura

    for i, r in enumerate(recs[:3], start=1):
        medal = medals[i - 1] if i <= 3 else f"#{i}"
        titulo  = r.get("titulo") or "—"
        artista = r.get("artista") or "—"
        link    = _clean_link(r.get("caminho") or "")
        sim_f   = float(r.get("similaridade", 0.0))
        pct     = (sim_f * 100.0) if sim_f <= 1.0 else sim_f
        bar     = _bar_from_pct(pct, width=20)

        head = f"┌─{medal} Top {i} " + "─" * (box_w - len(f"{medal} Top {i} ") - 1) + "┐"
        tail = "└" + "─" * (box_w + 2) + "┘"
        print(head)
        print("│ " + _truncate(f"🎵 Título: {titulo}",  box_w).ljust(box_w) + " │")
        print("│ " + _truncate(f"🎤 Artista: {artista}", box_w).ljust(box_w) + " │")
        print("│ " + _truncate(f"📊 Similaridade: {pct:.2f}% {bar}", box_w).ljust(box_w) + " │")
        print("│ " + _truncate(f"🔗 Link: {link}",      box_w).ljust(box_w) + " │")
        print(tail)
        print()

# -------------------- Fuzzy/normalização para validar artista/álbum --------------------
def _norm(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", s)
    s = re.sub(r"(?i)\b(ao vivo|live|oficial|audio|áudio|clipe|karaok[eê]|cover|lyric|vídeo|video|remix|vers[aã]o)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _ratio(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _artist_tokens(s: str) -> List[str]:
    s = _norm(s)
    s = re.sub(r"(?i)\b(feat\.?|com)\b", ",", s)
    return [t.strip() for t in re.split(r"[,&/x+]+", s) if t.strip()]

def _artist_match_ok(cand: str, hint: Optional[str]) -> bool:
    if not cand:
        return False
    if not hint:
        return True
    if _ratio(cand, hint) >= 0.65:
        return True
    cand_t = _artist_tokens(cand)
    hint_t = _artist_tokens(hint or "")
    for a in cand_t:
        for b in hint_t:
            if _ratio(a, b) >= 0.90:
                return True
    return False

# -------------------- Hints do YouTube/arquivo --------------------
def _parse_title_tokens(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not text:
        return None, None, None
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    parts = [p.strip() for p in t.split(" - ") if p.strip()]
    if len(parts) >= 3:
        artist = parts[0]
        album = parts[-1]
        track = " - ".join(parts[1:-1])
        return artist, track, album
    if len(parts) == 2:
        return parts[0], parts[1], None
    return None, parts[0] if parts else None, None

def _hints_from_ytdlp(meta: Dict[str, Any], filename_stem: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    artist_hint = meta.get("artist") or meta.get("uploader") or meta.get("channel")
    track_hint  = meta.get("track")
    album_hint  = meta.get("playlist_title")
    thumb = None
    thumbs = meta.get("thumbnails") or []
    if isinstance(thumbs, list) and thumbs:
        try:
            thumbs_sorted = sorted(thumbs, key=lambda d: (d.get("height", 0), d.get("width", 0)))
            thumb = thumbs_sorted[-1].get("url")
        except Exception:
            pass
    if not thumb and isinstance(meta.get("thumbnail"), str):
        thumb = meta["thumbnail"]
    if not track_hint:
        t = meta.get("title") or filename_stem
        a2, tr2, alb2 = _parse_title_tokens(t)
        track_hint = tr2 or track_hint
        if not artist_hint: artist_hint = a2
        if not album_hint:  album_hint  = alb2
    if not (artist_hint and track_hint):
        a3, tr3, alb3 = _parse_title_tokens(filename_stem)
        artist_hint = artist_hint or a3
        track_hint  = track_hint  or tr3
        album_hint  = album_hint  or alb3
    artist_hint = artist_hint.strip() if isinstance(artist_hint, str) else None
    track_hint  = track_hint.strip()  if isinstance(track_hint, str)  else None
    album_hint  = album_hint.strip()  if isinstance(album_hint, str)  else None
    return artist_hint, track_hint, album_hint, thumb

# -------------------- Discogs → Deezer (fallback) --------------------
def _discogs_search(artist: Optional[str], track: Optional[str], album: Optional[str], q_fallback: str) -> Optional[Dict[str, Any]]:
    if not DISCOGS_TOKEN:
        return None
    try:
        import requests  # type: ignore
        params = {"token": DISCOGS_TOKEN, "per_page": 5}
        if artist: params["artist"] = artist
        if track:  params["track"] = track
        if album:  params["release_title"] = album
        if not artist and not track and not album:
            params["q"] = q_fallback
        r = requests.get("https://api.discogs.com/database/search", params=params, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json() or {}
        results = data.get("results") or []
        if not results:
            return None
        best = results[0]
        title_full = best.get("title") or ""
        if " - " in title_full:
            a, t = title_full.split(" - ", 1)
            artist_out, title_out = a.strip(), t.strip()
        else:
            artist_out, title_out = (artist or ""), (track or title_full.strip())
        genres = []
        g = best.get("genre") or []; s = best.get("style") or []
        if isinstance(g, list): genres.extend(g)
        if isinstance(s, list): genres.extend(s)
        return {
            "title": title_out or None,
            "artist": artist_out or None,
            "album": best.get("title") or (album or None),
            "cover": best.get("cover_image") or None,
            "genres": list(dict.fromkeys(genres)) or None,
            "source": "discogs",
        }
    except Exception:
        return None

def _deezer_search(artist: Optional[str], track: Optional[str], album: Optional[str], q_fallback: str) -> Optional[Dict[str, Any]]:
    try:
        import requests  # type: ignore
        if artist and track and album:
            q = f'artist:"{artist}" track:"{track}" album:"{album}"'
        elif artist and track:
            q = f'artist:"{artist}" track:"{track}"'
        elif track:
            q = f'track:"{track}"'
        else:
            q = q_fallback
        r = requests.get("https://api.deezer.com/search", params={"q": q}, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json() or {}
        items = data.get("data") or []
        if not items:
            return None
        d = items[0]
        art = (d.get("artist") or {}).get("name")
        tit = d.get("title")
        alb = (d.get("album") or {}).get("title")
        alb_obj = d.get("album") or {}
        cover = alb_obj.get("cover_xl") or alb_obj.get("cover_big") or alb_obj.get("cover_medium") or alb_obj.get("cover")
        link = d.get("link")
        return {
            "title": tit or None,
            "artist": art or None,
            "album": alb or album or None,
            "cover": cover or None,
            "genres": None,
            "deezer_link": link or None,
            "source": "deezer",
        }
    except Exception:
        return None

# -------------------- YouTube download (retorna metadados ricos) --------------------
def _extract_entries_with_paths(ydl, info_obj) -> List[Dict[str, Any]]:
    def resolve_one(item):
        base = Path(ydl.prepare_filename(item))
        mp3 = base.with_suffix(".mp3") if base.suffix.lower() != ".mp3" else base
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
            if it:
                out.append(resolve_one(it))
    else:
        out.append(resolve_one(info_obj))
    return out

def baixar_audio_youtube(url: str, pasta_destino: Path, playlist: bool = False) -> List[Dict[str, Any]]:
    try:
        import yt_dlp  # type: ignore
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
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
        "extract_flat": False,
        "skip_download": False,
    }
    if not COOKIEFILE_PATH.exists():
        log.warning(f"⚠️  cookies.txt não encontrado em {COOKIEFILE_PATH}; continuando sem cookies.")
        ydl_opts.pop("cookiefile", None)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return _extract_entries_with_paths(ydl, info)
    except Exception as e:
        log.error(f"❌ Erro ao baixar: {e}")
        return []

# -------------------- Ações --------------------
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

        # Hints do YouTube / arquivo
        artist_hint = track_hint = album_hint = yt_thumb = None
        if youtube_meta is None:
            # tenta sidecar .info.json se existir
            side = arquivo.with_suffix(".info.json")
            if side.exists():
                try:
                    youtube_meta = json.loads(side.read_text())
                except Exception:
                    youtube_meta = None
        if youtube_meta:
            artist_hint, track_hint, album_hint, yt_thumb = _hints_from_ytdlp(youtube_meta, arquivo.stem)
        else:
            a3, tr3, alb3 = _parse_title_tokens(arquivo.stem)
            artist_hint, track_hint, album_hint = a3, tr3, alb3

        titulo = arquivo.stem
        artista = "desconhecido"
        album = genero = capa = None

        if enriquecer:
            # ===== Spotify primeiro (alta confiabilidade) =====
            used_spotify = False
            if _HAS_SPOTIFY and (artist_hint or track_hint):
                try:
                    log.info("🟢 Buscando no Spotify (metadados confiáveis)…")
                    sp = enrich_from_spotify(artist_hint, track_hint, album_hint, duration_sec)
                    if sp.get("accepted"):
                        titulo  = sp.get("title")  or titulo
                        artista = sp.get("artist") or artista
                        album   = sp.get("album")  or album
                        capa    = sp.get("cover")  or yt_thumb or capa
                        g_list  = sp.get("genres")
                        if g_list: genero = ", ".join(g_list)
                        used_spotify = True
                    else:
                        log.info(f"Spotify não confirmou ({sp.get('reason')}). Indo para Discogs/Deezer…")
                except Exception as e:
                    log.info(f"Spotify indisponível: {e}. Partindo para Discogs/Deezer…")

            # ===== Discogs → Deezer (com validação contra hints) =====
            if not used_spotify:
                log.info("🔎 Buscando metadados (Discogs → Deezer)…")
                q_fb = " ".join([p for p in [artist_hint, track_hint, album_hint] if p]) or arquivo.stem
                md = _discogs_search(artist_hint, track_hint, album_hint, q_fb)
                if md and (_artist_match_ok(md.get("artist",""), artist_hint)) and (_ratio(md.get("title",""), track_hint or "") >= 0.60):
                    titulo = md.get("title") or titulo
                    artista = md.get("artist") or artista
                    album = md.get("album") or album_hint or album
                    capa = md.get("cover") or yt_thumb or capa
                    if md.get("genres"):
                        genero = ", ".join(md["genres"]) if isinstance(md["genres"], list) else str(md["genres"])
                else:
                    md2 = _deezer_search(artist_hint, track_hint, album_hint, q_fb)
                    if md2 and (_artist_match_ok(md2.get("artist",""), artist_hint)) and (_ratio(md2.get("title",""), track_hint or "") >= 0.60):
                        titulo = md2.get("title") or titulo
                        artista = md2.get("artist") or artista
                        album = md2.get("album") or album_hint or album
                        capa = md2.get("cover") or yt_thumb or capa
                        if md2.get("genres"):
                            genero = ", ".join(md2["genres"]) if isinstance(md2["genres"], list) else str(md2["genres"])
                    else:
                        # ===== Shazam (confirma artista+título pelo áudio) =====
                        log.info("🎧 Tentando reconhecer pelo Shazam…")
                        try:
                            rec = recognize_with_cache(arquivo, prefer_shazam_first=True)
                        except TypeError:
                            rec = recognize_with_cache(arquivo)
                        if rec and (rec.title or rec.artist):
                            if rec.title:  titulo = rec.title
                            if rec.artist: artista = rec.artist
                            # tentar completar álbum/capa no Discogs com o que Shazam trouxe
                            if DISCOGS_TOKEN and rec.title and rec.artist:
                                try:
                                    md3 = _discogs_search(rec.artist, rec.title, None, f"{rec.artist} {rec.title}") or {}
                                    if md3.get("album"): album = md3["album"]
                                    if md3.get("cover"): capa = md3["cover"]
                                    if md3.get("genres"):
                                        genero = ", ".join(md3["genres"]) if isinstance(md3["genres"], list) else str(md3["genres"])
                                except Exception:
                                    pass

            # ===== Modo estrito: só grava se houver metadado confiável =====
            if STRICT_METADATA:
                a_ok = artista and artista != "desconhecido"
                t_ok = titulo and (titulo != arquivo.stem)
                if not (a_ok and t_ok):
                    msg = f"🔒 Sem metadados confiáveis para '{arquivo.name}'."
                    if not INSERT_ON_LOW_CONFIDENCE:
                        # enfileira em pendentes e não insere
                        try:
                            pend = Path(__file__).resolve().parent / "pendentes.csv"
                            with pend.open("a", encoding="utf-8") as f:
                                f.write(json.dumps({
                                    "arquivo": str(arquivo),
                                    "hints": {"artist": artist_hint, "title": track_hint, "album": album_hint, "thumb": yt_thumb}
                                }, ensure_ascii=False) + "\n")
                            log.warning(msg + f" Enfileirado em {pend}.")
                        except Exception:
                            log.warning(msg + " Enfileirado em pendentes.csv (falha ao gravar).")
                        return
                    else:
                        log.warning(msg + " Gravando com hints (INSERT_ON_LOW_CONFIDENCE=True).")
                        artista = artist_hint or artista
                        titulo  = track_hint  or titulo
                        album   = album_hint  or album
                        capa    = yt_thumb    or capa

        # ===== Persistência =====
        nome = arquivo.name
        link_final = (youtube_meta or {}).get("webpage_url") or origem_link or str(arquivo.resolve())
        log.info("💾 Gravando no MySQL (tabela)…")
        rid = upsert_musica(
            nome=nome,
            caracteristicas=vec,
            artista=artista,
            titulo=titulo,
            album=album,
            genero=genero,
            capa_album=capa,
            link_youtube=link_final,
        )
        log.info(f"✅ Indexado id={rid}  {arquivo.name}  →  {titulo} — {artista}")

        # ===== Recomendações =====
        if recomendar:
            log.info("🤝 Gerando recomendações…")
            recs = recomendar_por_audio(arquivo, k=k, sr=sr, excluir_nome=nome)
            if not recs:
                print("\nℹ️  Sem vizinhos suficientes ainda. Ingerir mais faixas ajuda.")
            else:
                # impressão bonita
                _print_recs_pretty(recs)

    except Exception as e:
        log.error(f"❌ Falha ao processar '{arquivo}': {e}")
        log.debug(traceback.format_exc())
    finally:
        # --- LIMPEZA: apaga downloads após extrair features ---
        try:
            if AUTO_DELETE_DOWNLOADED:
                is_download = False
                try:
                    is_download = Path(arquivo).resolve().is_relative_to(Path(DOWNLOADS_DIR).resolve())
                except Exception:
                    a_res = str(Path(arquivo).resolve())
                    d_res = str(Path(DOWNLOADS_DIR).resolve())
                    is_download = a_res.startswith(d_res)
                if is_download:
                    side = Path(arquivo).with_suffix(".info.json")
                    if side.exists():
                        side.unlink()
                    if Path(arquivo).exists():
                        Path(arquivo).unlink()
                    log.info(f"🧹 Arquivos removidos da pasta de downloads: {Path(arquivo).name}")
        except Exception:
            pass

def processar_link_youtube(url: str, enriquecer: bool = True, recomendar: bool = True, sr: int = 22050) -> None:
    items = baixar_audio_youtube(url, DOWNLOADS_DIR, playlist=False)
    if not items:
        log.warning("Nenhum arquivo baixado.")
        return
    for it in items:
        link_individual = (it.get("meta") or {}).get("webpage_url") or url
        processar_audio_local(
            it["path"], origem_link=link_individual, enriquecer=enriquecer, recomendar=recomendar, sr=sr, youtube_meta=it.get("meta")
        )

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
        if recs:
            _print_recs_pretty(recs)
        else:
            print("Nenhuma recomendação encontrada.")

def listar_banco(limite: int = 20) -> None:
    rows = listar(limit=limite)
    if not rows:
        print("Banco vazio.")
        return
    cols = [c for c in ("id", "titulo", "artista", "caminho", "created_at") if c in rows[0]]
    print(_format_table(rows, cols))

# -------------------- MENU --------------------
def menu() -> str:
    print("\n🎧  === Menu Principal ===")
    print("1) Processar áudio local")
    print("2) Processar link do YouTube")
    print("3) Upload em massa (pasta local)")
    print("4) Recalibrar & Recomendar")
    print("5) Playlist do YouTube (bulk)")
    print("6) Listar últimos itens do banco")
    print("0) Sair")
    return input("Opção: ").strip()

def _discover_audio_paths(path: Path, recursive: bool):
    AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".aiff", ".aif"}
    if path.is_file():
        return [path] if path.suffix.lower() in AUDIO_EXTS else []
    pattern = "**/*" if recursive else "*"
    return [p for p in path.glob(pattern) if p.is_file() and p.suffix.lower() in AUDIO_EXTS]

def loop_interativo() -> None:
    _print_header()
    criar_tabela()
    print(f"⬇️  Downloads: {DOWNLOADS_DIR}\n")
    while True:
        opc = menu()
        if opc == "1":
            c = Path(input("Arquivo de áudio: ").strip())
            side = c.with_suffix(".info.json")
            meta = None
            try:
                if side.exists():
                    meta = json.loads(side.read_text())
            except Exception:
                pass
            processar_audio_local(c, enriquecer=True, recomendar=True, k=3, youtube_meta=meta)
        elif opc == "2":
            link = input("Link do YouTube (vídeo): ").strip()
            processar_link_youtube(link, enriquecer=True, recomendar=True)
        elif opc == "3":
            pasta = Path(input("Pasta local: ").strip())
            arquivos = _discover_audio_paths(pasta, True)
            if not arquivos:
                print("Nenhum áudio encontrado.")
            else:
                for i, ap in enumerate(arquivos, 1):
                    log.info(f"[{i}/{len(arquivos)}] {ap.name}")
                    side = ap.with_suffix(".info.json")
                    meta = None
                    try:
                        if side.exists():
                            meta = json.loads(side.read_text())
                    except Exception:
                        pass
                    processar_audio_local(ap, enriquecer=True, recomendar=False, youtube_meta=meta)
                print("✅ Concluído.")
        elif opc == "4":
            recalibrar_e_recomendar(k=3)
        elif opc == "5":
            link = input("Link da playlist/álbum (YouTube): ").strip()
            processar_playlist_youtube(link, enriquecer=True)
        elif opc == "6":
            try:
                n = int(input("Quantos itens listar? [20]: ") or "20")
            except Exception:
                n = 20
            listar_banco(limite=n)
        elif opc == "0":
            print("👋 Até a próxima!")
            break
        else:
            print("❌ Opção inválida.")

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        loop_interativo()
        return 0
    parser = argparse.ArgumentParser(prog=APP_NAME, description=f"{APP_NAME} — Menu interativo")
    parser.add_argument("--menu", action="store_true", help="Abrir menu (default).")
    _ = parser.parse_args(argv)
    loop_interativo()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
