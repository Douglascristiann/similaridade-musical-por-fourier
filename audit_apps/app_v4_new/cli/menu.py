# -*- coding: utf-8 -*-
import os, sys, json
from pathlib import Path
import logging
from typing import List

from app_v4_new.config import APP_NAME, APP_VERSION, DOWNLOADS_DIR
from app_v4_new.database.db import listar
from app_v4_new.services.ingest import (
    processar_audio_local, processar_link_youtube,
    processar_playlist_youtube, recalibrar_e_recomendar,
    contar_musicas
)

log = logging.getLogger("FourierMatch")
logging.basicConfig(level=logging.INFO, format="%(message)s")

BANNER = r"""
   ______                     _            __  ___      __      __     
  / ____/___  __  _______  __(_)___  ___  /  |/  /___ _/ /___ _/ /____ 
 / / __/ __ \/ / / / ___/ / / / __ \/ _ \/ /|_/ / __ `/ / __ `/ __/ _ \
/ /_/ / /_/ / /_/ (__  ) /_/ / / / /  __/ /  / / /_/ / / /_/ / /_/  __/
\____/\____/\__,_/____/\__, /_/ /_/\___/_/  /_/\__,_/_/\__,_/\__/\___/ 
                      /____/          Similaridade musical por Fourier
"""

UNIVERSIDADE = "🏫  Universidade Paulista — Curso de Sistemas de Informação: Paraíso (2025/2)"
CRIADORES    = "👨‍💻  Criadores: Douglas Cristian da Cunha & Fábio Silva Matos Filho"
TCC_TITULO   = "📚  Uma Abordagem Baseada em Análise Espectral para Recomendação Musical"

def print_header() -> None:
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
    print(f"⬇️  Downloads: {DOWNLOADS_DIR}\n")

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

def _discover_audio_paths(path: Path, recursive: bool):
    AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".aiff", ".aif"}
    if path.is_file():
        return [path] if path.suffix.lower() in AUDIO_EXTS else []
    pattern = "**/*" if recursive else "*"
    return [p for p in path.glob(pattern) if p.is_file() and p.suffix.lower() in AUDIO_EXTS]

def _menu() -> str:
    print("\n🎧  === Menu Principal ===")
    print("1) Processar áudio local")
    print("2) Processar link do YouTube")
    print("3) Upload em massa (pasta local)")
    print("4) Recalibrar & Recomendar")
    print("5) Playlist do YouTube (bulk)")
    print("6) Listar últimos itens do banco")
    print("0) Sair")
    return input("Opção: ").strip()

def loop_interativo() -> None:
    while True:
        opc = _menu()
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
            rows = listar(limit=n)
            if not rows:
                print("Banco vazio.")
            else:
                cols = [c for c in ("id","titulo","artista","caminho","created_at") if c in rows[0]]
                print(_format_table(rows, cols))

        elif opc == "0":
            print("👋 Até a próxima!")
            break
        else:
            print("❌ Opção inválida.")
