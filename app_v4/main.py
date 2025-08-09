
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import traceback
import time
import json
import os
import logging

import numpy as np
import librosa

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# IMPORTS ROBUSTOS
try:
    from .config_app import APP_NAME, APP_VERSION, ORG_TITLE, CREATORS, TCC_TITLE, BLOCK_SCALER_PATH, BLOCK_WEIGHTS, DOWNLOADS_DIR, COOKIEFILE_PATH
    from .audio.extrator_fft import extrair_features_completas
    from .storage.mysql_db import (
        ensure_schema, insert_track, list_tracks, AUDIO_EXTS
    )
    from .recom.knn_recommender import (
        recomendar_por_audio, preparar_base_escalada, formatar_percentual
    )
    from .recognition.recognizer import recognize_with_cache
except Exception:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app_v5.config_app import APP_NAME, APP_VERSION, ORG_TITLE, CREATORS, TCC_TITLE, BLOCK_SCALER_PATH, BLOCK_WEIGHTS, DOWNLOADS_DIR, COOKIEFILE_PATH
    from app_v5.audio.extrator_fft import extrair_features_completas
    from app_v5.storage.mysql_db import (
        ensure_schema, insert_track, list_tracks, AUDIO_EXTS
    )
    from app_v5.recom.knn_recommender import (
        recomendar_por_audio, preparar_base_escalada, formatar_percentual
    )
    from app_v5.recognition.recognizer import recognize_with_cache

# Logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("FourierMatch")

BANNER = r"""
   ______                     _            __  ___      __      __     
  / ____/___  __  _______  __(_)___  ___  /  |/  /___ _/ /___ _/ /____ 
 / / __/ __ \/ / / / ___/ / / / __ \/ _ \/ /|_/ / __ `/ / __ `/ __/ _ \\ 
/ /_/ / /_/ / /_/ (__  ) /_/ / / / /  __/ /  / / /_/ / / /_/ / /_/  __/
\____/\____/\__,_/____/\__, /_/ /_/\___/_/  /_/\__,_/_/\__,_/\__/\___/ 
                      /____/          Similaridade musical por Fourier
"""

# -------------------- Helpers UI --------------------
def _print_header():
    os.system("")
    print(BANNER)
    print(f"🎵  {APP_NAME} v{APP_VERSION}")
    print(f"🏫  {ORG_TITLE}")
    print(f"👨‍💻  Criadores: {', '.join(CREATORS)}")
    print(f"📚  {TCC_TITLE}")
    print("-" * 72)

def _format_table(rows: list[dict], columns: list[str]) -> str:
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

def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""

def _discover_audio_paths(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in AUDIO_EXTS else []
    pattern = "**/*" if recursive else "*"
    return [p for p in path.glob(pattern) if p.is_file() and p.suffix.lower() in AUDIO_EXTS]

# -------------------- YouTube download --------------------
def baixar_audio_youtube(url: str, pasta_destino: Path, playlist: bool = False) -> list[Path]:
    """
    Baixa áudio do YouTube (depende de yt-dlp + ffmpeg).
    Usa cookies em COOKIEFILE_PATH se existir.
    Retorna a lista de caminhos dos arquivos de áudio extraídos (mp3).
    """
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
    }
    if not COOKIEFILE_PATH.exists():
        log.warning(f"⚠️  cookies.txt não encontrado em {COOKIEFILE_PATH}; continuando sem cookies.")
        ydl_opts.pop("cookiefile", None)

    results: list[Path] = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            def _resolve_final(p_info) -> Path | None:
                try:
                    base = Path(ydl.prepare_filename(p_info))
                    cand = base.with_suffix(".mp3")
                    if cand.exists():
                        return cand
                    return base if base.exists() else None
                except Exception:
                    return None

            if "entries" in info and isinstance(info["entries"], list):
                for it in info["entries"]:
                    if not it:
                        continue
                    p = _resolve_final(it)
                    if p:
                        results.append(p)
            else:
                p = _resolve_final(info)
                if p:
                    results.append(p)
    except Exception as e:
        log.error(f"❌ Erro ao baixar: {e}")
        return []

    return results

# -------------------- Pipelines --------------------
def processar_audio_local(arquivo: Path, origem_link: str | None = None, enriquecer: bool = True, recomendar: bool = True, k: int = 3, sr: int = 22050) -> None:
    if not arquivo.exists():
        log.error(f"❌ Arquivo não encontrado: {arquivo}")
        return
    try:
        log.info("🔧 Extraindo features…")
        y, _sr = librosa.load(str(arquivo), sr=sr, mono=True)
        vec = extrair_features_completas(y, _sr)

        titulo = arquivo.stem
        artista = "desconhecido"
        album = genero = capa = None
        if enriquecer:
            log.info("🔎 Reconhecendo metadados (Shazam/AudD)…")
            rec = recognize_with_cache(arquivo)
            if rec.title:  titulo = rec.title
            if rec.artist: artista = rec.artist

        nome = arquivo.name
        log.info("💾 Gravando no MySQL…")
        rid = insert_track(
            nome=nome, vec=vec, artista=artista, titulo=titulo,
            album=album, genero=genero, capa_album=capa,
            link_youtube=origem_link or str(arquivo.resolve()), upsert=True
        )
        log.info(f"✅ Indexado id={rid}  {arquivo.name}  →  {titulo} — {artista}")

        if recomendar:
            log.info("🤝 Gerando recomendações…")
            recs = recomendar_por_audio(arquivo, k=k, sr=sr, excluir_caminho=nome)
            if not recs:
                print("\nℹ️  Sem vizinhos suficientes ainda. Ingerir mais faixas ajuda.")
            else:
                # formata %
                for r in recs:
                    r["similaridade"] = formatar_percentual(float(r["similaridade"]))
                cols = ["id", "titulo", "artista", "caminho", "similaridade"]
                print("\n🎯 Recomendações (top 3):")
                print(_format_table(recs, [c for c in cols if c in recs[0]]))
    except Exception as e:
        log.error(f"❌ Falha ao processar '{arquivo}': {e}")
        log.debug(traceback.format_exc())

def processar_link_youtube(url: str, enriquecer: bool = True, recomendar: bool = True, sr: int = 22050):
    baixados = baixar_audio_youtube(url, DOWNLOADS_DIR, playlist=False)
    if not baixados:
        log.warning("Nenhum arquivo baixado.")
        return
    for p in baixados:
        processar_audio_local(p, origem_link=url, enriquecer=enriquecer, recomendar=recomendar, sr=sr)

def processar_playlist_youtube(url: str, enriquecer: bool = True, sr: int = 22050):
    baixados = baixar_audio_youtube(url, DOWNLOADS_DIR, playlist=True)
    if not baixados:
        log.warning("Nenhum item baixado da playlist.")
        return
    log.info(f"▶️ Playlist: {len(baixados)} itens baixados.")
    for i, p in enumerate(baixados, 1):
        log.info(f"[{i}/{len(baixados)}] {p.name}")
        processar_audio_local(p, origem_link=url, enriquecer=enriquecer, recomendar=False, sr=sr)
    log.info("✅ Playlist processada.")

def recalibrar_e_recomendar(k: int = 3, sr: int = 22050):
    log.info("🛠️  Reajustando padronizador por bloco (scaler)…")
    Xs, ids, metas, scaler = preparar_base_escalada()
    log.info(f"✅ Scalado {Xs.shape[0]} faixas x {Xs.shape[1]} dims.\n")
    f = Path(input("Arquivo de áudio para recomendar (ou Enter para pular): ").strip() or "")
    if f.exists():
        recs = recomendar_por_audio(f, k=k, sr=sr, excluir_caminho=f.name)
        if recs:
            for r in recs:
                r["similaridade"] = formatar_percentual(float(r["similaridade"]))
            cols = ["id", "titulo", "artista", "caminho", "similaridade"]
            print("\n🎯 Recomendações (top 3):")
            print(_format_table(recs, [c for c in cols if c in recs[0]]))
        else:
            print("Nenhuma recomendação encontrada.")

def listar_banco(limite: int = 20):
    rows = list_tracks(limit=limite)
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

def loop_interativo():
    _print_header()
    ensure_schema()
    print(f"⬇️  Downloads: {DOWNLOADS_DIR}\n")
    while True:
        opc = menu()
        if opc == "1":
            c = Path(input("Arquivo de áudio: ").strip())
            processar_audio_local(c, enriquecer=True, recomendar=True, k=3)
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
                    processar_audio_local(ap, enriquecer=True, recomendar=False)
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

# -------------------- CLI opcional --------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=APP_NAME, description=f"{APP_NAME} — Similaridade musical por Fourier")
    sub = p.add_subparsers(dest="cmd")
    pa = sub.add_parser("menu", help="Abre o menu interativo.")
    pa.set_defaults(func=lambda args: loop_interativo())
    return p

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        loop_interativo()
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
        return 130
    except Exception as e:
        print(f"❌ Erro: {e}")
        if "--verbose" in argv or "-v" in argv:
            traceback.print_exc()
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
