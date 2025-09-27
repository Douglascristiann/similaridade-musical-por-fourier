# -*- coding: utf-8 -*-
import os, sys, json
from pathlib import Path
import logging
from typing import List

from app_v5.config import APP_NAME, APP_VERSION, DOWNLOADS_DIR, MUSIC_DIR
from app_v5.database.db import listar
from app_v5.services.ingest import (
    processar_audio_local, processar_link_youtube,
    processar_playlist_youtube, recalibrar_e_recomendar,
    contar_musicas
)
from app_v5.recom.knn_recommender import KNNRecommender, build_penalty_engine
from app_v5.recom.db_lookup_adapter import DBLookup


def acao_recomendar(...):
    # 1) carregar matriz e ids (ou de um cache que você já tenha)
    X = np.load("/caminho/feature_matrix.npy")
    ids = np.load("/caminho/item_ids.npy")

    # 2) função que devolve vetor da query (a sua rotina real)
    def get_vec_for_query(q: dict):
        # TODO: implemente com o mesmo schema que gerou X
        return obter_vetor_da_query(q)

    # 3) adaptador DB + penalty engine
    db_lookup = DBLookup()
    engine = build_penalty_engine()  # usa as flags do próprio knn_recommender.py (ENV)

    # 4) instanciar KNN e recomendar
    knn = KNNRecommender(
        feature_matrix=X,
        item_ids=ids,
        get_vector_for_query=get_vec_for_query,
        db_lookup=db_lookup,
        penalty_engine=engine,
        n_neighbors=50,     # ajuste conforme seu padrão
        metric="euclidean", # ou "cosine", etc.
    )

    query = {"id_musica": id_escolhido}  # ou artist/title/path
    recs = knn.recommend(query, topn=10, debug=True)





log = logging.getLogger("FourierMatch")
logging.basicConfig(level=logging.INFO, format="%(message)s")

# === Banner UNICODE (╔═╗/║/╚═╝) com cor + emoji, alinhado ===
import shutil
import textwrap
import os
import sys
import re
import unicodedata

# --- cor ---
def _use_color() -> bool:
    try:
        return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    except Exception:
        return False

USE_COLOR = _use_color()
CYAN  = "\033[96m" if USE_COLOR else ""
BOLD  = "\033[1m"  if USE_COLOR else ""
RESET = "\033[0m"  if USE_COLOR else ""

# --- emoji on/off (FM_EMOJI=0 desliga) ---
USE_EMOJI = os.environ.get("FM_EMOJI", "1") != "0"
def em(emoji: str, fallback: str) -> str:
    return emoji if USE_EMOJI else fallback

# ---- largura visual (usa wcwidth se existir, senão fallback) ----
_ansi_re = re.compile(r"\x1b\[[0-9;]*m")
try:
    from wcwidth import wcswidth as _wcswidth
    def _vwidth(s: str) -> int:
        return max(0, _wcswidth(_ansi_re.sub("", s)))
except Exception:
    def _vwidth(s: str) -> int:
        s = _ansi_re.sub("", s)
        total = 0
        for ch in s:
            if unicodedata.category(ch) == "Mn":
                continue
            eaw = unicodedata.east_asian_width(ch)
            cp = ord(ch)
            if eaw in ("W", "F") or (0x1F000 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF):
                total += 2
            else:
                total += 1
        return total

def _unicode_box(lines, max_width=None) -> str:
    cols = shutil.get_terminal_size((100, 20)).columns
    w = min(max(68, cols - 4), 100)   # largura da caixa
    if max_width: w = min(w, max_width)
    inner = w - 2

    # wrap suave
    wrapped = []
    for ln in lines:
        if not ln:
            wrapped.append("")
            continue
        if _vwidth(ln) <= inner - 2:
            wrapped.append(ln)
        else:
            wrapped.extend(textwrap.wrap(ln, width=max(20, inner - 2),
                                         break_long_words=False, break_on_hyphens=False))

    top    = "╔" + ("═" * inner) + "╗"
    bottom = "╚" + ("═" * inner) + "╝"
    empty_content = " " * inner

    # imprime topo/bottom com a linha inteira colorida (não tem RESET no meio)
    cols_margin = " " * max(0, (cols - w) // 2)
    out = []
    out.append(cols_margin + (CYAN + top + RESET if USE_COLOR else top))

    # linha vazia
    out.append(cols_margin + (CYAN + "║" + RESET) + empty_content + (CYAN + "║" + RESET))

    # corpo
    for s in wrapped:
        s = s.strip()
        pad = max(0, inner - _vwidth(s))
        left = pad // 2
        right = pad - left
        content = (" " * left) + s + (" " * right)
        # pinta APENAS as bordas; conteúdo fica sem ANSI (evita “pipe” branco)
        out.append(cols_margin + (CYAN + "║" + RESET) + content + (CYAN + "║" + RESET))

    # linha vazia
    out.append(cols_margin + (CYAN + "║" + RESET) + empty_content + (CYAN + "║" + RESET))
    out.append(cols_margin + (CYAN + bottom + RESET if USE_COLOR else bottom))
    return "\n".join(out)

def print_header() -> None:
    from app_v5.config import APP_NAME, APP_VERSION
    from app_v5.services.ingest import contar_musicas

    try:
        n = contar_musicas()
    except Exception:
        n = None

    title = f"{BOLD}FOURIERMATCH{RESET}" if USE_COLOR else "FOURIERMATCH"
    lines = [
        title,
        "Similaridade musical por Fourier",
        em("🎵 ", "") + f"{APP_NAME} {APP_VERSION}",
        "",
        em("🏫 ", "") + "Universidade Paulista — Curso de Sistemas de Informação: Paraíso (2025/2)",
        em("💻 ", "") + "Criadores: Douglas Cristian da Cunha & Fábio Silva Matos Filho",  # trocado de 👨‍💻 -> 💻
        em("📚 ", "") + "Uma Abordagem Baseada em Análise Espectral para Recomendação Musical",
    ]
    if isinstance(n, int):
        lines += ["", em("📦 ", "") + f"Catálogo atual: {n} música(s) no banco"]

    panel = _unicode_box(lines)

    cols = shutil.get_terminal_size((100, 20)).columns
    sep = "─" * min(cols, 100)
    if USE_COLOR: sep = CYAN + sep + RESET

    print(panel)
    print(sep + "\n")


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
            nome = input("Arquivo de áudio: ").strip().strip('"').strip("'")
            c = (MUSIC_DIR / Path(nome).name).resolve()
            side = c.with_suffix(".info.json")
            meta = None
            try:
                if side.exists():
                    meta = json.loads(side.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
            processar_audio_local(c, recomendar=True, k=3, youtube_meta=meta)

        elif opc == "2":
            link = input("Link do YouTube (vídeo): ").strip()
            # ==============================================================================
            # === CORREÇÃO APLICADA AQUI ===
            # Removido o argumento 'enriquecer=True' que não é mais usado.
            # ==============================================================================
            processar_link_youtube(link, recomendar=True)

        elif opc == "3":
            pasta = Path(MUSIC_DIR)
            if not pasta.exists() or not pasta.is_dir():
                print(f"⚠️  Diretório inválido: {pasta}")
            else:
                arquivos = _discover_audio_paths(pasta, True)
                total = len(arquivos)
                print(f"📂 Pasta-alvo: {pasta}")
                if total == 0:
                    print("ℹ️  Nenhuma música encontrada.")
                else:
                    print(f"🎵  Detectadas {total} música(s) para processar.")
                    resp = input("Pressione Enter para continuar ou digite 0 para voltar ao menu: ").strip()
                    if resp != "0":
                        ok, falhas = 0, 0
                        for i, ap in enumerate(arquivos, 1):
                            try:
                                log.info(f"[{i}/{total}] {ap.name}")
                                side = ap.with_suffix(".info.json")
                                meta = json.loads(side.read_text(encoding="utf-8", errors="ignore")) if side.exists() else None
                                processar_audio_local(ap, recomendar=False, youtube_meta=meta)
                                ok += 1
                            except Exception as e:
                                falhas += 1
                                log.error(f"Falha em {ap}: {e}")
                        print(f"✅ Concluído. Sucesso: {ok} | Falhas: {falhas}")

        elif opc == "4":
            recalibrar_e_recomendar(k=3)

        elif opc == "5":
            link = input("Link da playlist/álbum (YouTube): ").strip()
            processar_playlist_youtube(link)

        elif opc == "6":
            try:
                n = int(input("Quantos itens listar? [20]: ") or "20")
            except Exception:
                n = 20
            rows = listar(limit=n)
            if not rows:
                print("Banco vazio.")
            else:
                cols = [c for c in ("id", "titulo", "artista", "caminho", "created_at") if c in rows[0]]
                print(_format_table(rows, cols))

        elif opc == "0":
            print("👋 Até a próxima!")
            break

        else:
            print("❌ Opção inválida.")