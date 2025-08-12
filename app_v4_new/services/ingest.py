# -*- coding: utf-8 -*-
"""
Serviços de ingestão e recomendação (compatível com o menu):
- processar_audio_local(caminho, sr=22050, k_recs=3, recomendar=True)
- processar_link_youtube(link, enriquecer=True, recomendar=True, k_recs=3, sr=22050)
- upload_em_massa(pasta, sr=22050, k_recs=3)
- processar_playlist_youtube(link, sr=22050, k_recs=3)  # alias
- playlist_bulk(link, sr=22050, k_recs=3)
- listar_ultimos_itens(limite=10)
- recalibrar_e_recomendar(k=3, sr=22050)
- contar_musicas() -> int

Robustez YouTube:
- fallback de player_client: ios -> android -> web
- backoff com jitter p/ HTTP 429
- uso opcional de cookiefile (se existir)
- playlist: youtubetab:skip=authcheck
"""

from __future__ import annotations

import os
import time
import random
import logging
from importlib import import_module
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from yt_dlp import YoutubeDL
# topo de app_v4_new/services/ingest.py
from pathlib import Path
from app_v4_new.config_app import DOWNLOADS_DIR, COOKIEFILE_PATH
from app_v4_new.downloader.youtube_dl import (
    baixar_audio_youtube,
    baixar_playlist_youtube,
    buscar_youtube_por_meta,
)


# === Config / DB / Audio / Recom ===
try:
    from app_v4_new.config import DOWNLOADS_DIR as _DL_DIR
except Exception:
    _DL_DIR = Path(__file__).resolve().parents[1] / "downloads"

DOWNLOADS_DIR = Path(_DL_DIR)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Apagar o áudio após extrair (boa prática)
try:
    from app_v4_new.config import DELETE_AUDIO_AFTER_INGEST
except Exception:
    DELETE_AUDIO_AFTER_INGEST = True

# Comprimento do vetor e nome da tabela (se expostos)
try:
    from app_v4_new.config import EXPECTED_FEATURE_LENGTH, DB_TABLE_NAME  # noqa
except Exception:
    EXPECTED_FEATURE_LENGTH = None
    DB_TABLE_NAME = "tb_musicas"

# Cookiefile/clients para yt-dlp (opcionais)
try:
    from app_v4_new.config import COOKIEFILE_PATH  # noqa
except Exception:
    COOKIEFILE_PATH = None  # defina no config se quiser usar cookies

try:
    from app_v4_new.config import YTDLP_CLIENT_SEQUENCE  # noqa
except Exception:
    YTDLP_CLIENT_SEQUENCE = ["ios", "android", "web"]

# DB (compatível com suas versões antigas e novas)
_SALVAR_FUN = None
try:
    from app_v4_new.database.db import upsert_musica as _SALVAR_FUN  # type: ignore
except Exception:
    try:
        from app_v4_new.database.db import inserir_musica as _SALVAR_FUN  # type: ignore
    except Exception:
        _SALVAR_FUN = None

# Contagem direta (se existir no seu DB)
_DB_CONTAR = None
try:
    from app_v4_new.database.db import contar as _DB_CONTAR  # type: ignore
except Exception:
    _DB_CONTAR = None

# Conexão bruta (para contagem SQL fallback)
_DB_CONNECT = None
try:
    from app_v4_new.database.db import conectar as _DB_CONNECT  # type: ignore
except Exception:
    _DB_CONNECT = None

# Listagem / Matriz para KNN
try:
    from app_v4_new.database.db import listar as _DB_LISTAR  # type: ignore
except Exception:
    _DB_LISTAR = None

try:
    from app_v4_new.database.db import carregar_matriz  # type: ignore
except Exception:
    def carregar_matriz():
        import numpy as np
        return np.zeros((0, 0)), [], []

# Extrator de features
from app_v4_new.audio.extrator_fft import extrair_caracteristicas  # type: ignore

# Recomendador (percentis + guard-rails)
from app_v4_new.recom.knn_recommender import (
    preparar_base_escalada,
    recomendar_por_audio,
    recomendar_por_id,
)

log = logging.getLogger("FourierMatch")


# =====================================================================
# Utilitários
# =====================================================================

def _parse_hints_from_filename(fname: str) -> Tuple[Optional[str], Optional[str]]:
    """Extrai (artista, título) do padrão 'Artista - Título' se possível."""
    base = Path(fname).stem

    lixo = ["(ao vivo)", "(live)", "(oficial)", "[oficial]", "(official)", "[official]",
            "(audio)", "(áudio)", "(clipe)", "(clip)", "(video)", "(vídeo)"]
    tmp = base.lower()
    for t in lixo:
        tmp = tmp.replace(t, "")
    base = " ".join(tmp.split()).strip()

    if " - " in base:
        artista, titulo = base.split(" - ", 1)
        artista = artista.strip().title()
        titulo = titulo.strip().title()
        if artista and titulo:
            return artista, titulo
    return None, None


def _buscar_youtube_link_simples(artista: str, titulo: str) -> str:
    """Busca 1 link do YouTube para ('artista titulo') sem cookies."""
    if not artista or not titulo:
        return "Não Encontrado"

    query = f"{artista} {titulo}"
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "default_search": "ytsearch",
        "noplaylist": True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if result and "entries" in result and result["entries"]:
                vid = result["entries"][0].get("id")
                if vid:
                    return f"https://www.youtube.com/watch?v={vid}"
    except Exception as e:
        print("❌ Erro yt_dlp (busca simples):", e)
    return "Não Encontrado"


def _call_integration(module_name: str, func_name: str, *args, **kwargs) -> Optional[Dict[str, Any]]:
    """Chama uma função em app_v4_new.integrations.*, se existir; senão retorna None."""
    try:
        mod = import_module(module_name)
        fn = getattr(mod, func_name, None)
        if not callable(fn):
            return None
        return fn(*args, **kwargs)
    except Exception:
        return None


def _obter_metadados(path: Path,
                     hint_artista: Optional[str],
                     hint_titulo: Optional[str]) -> Dict[str, Any]:
    """
    Orquestra metadados (preenche faltantes com 'Desconhecido' / 'Não Encontrado'):
      Spotify → Discogs → Deezer → Shazam (se necessário)
      + busca YouTube para arquivos locais
    """
    meta: Dict[str, Any] = {
        "titulo": hint_titulo or None,
        "artista": hint_artista or None,
        "album": None,
        "genero": None,
        "capa_album": None,
        "link_youtube": None,
    }

    # Spotify
    if hint_artista or hint_titulo:
        query = f"{hint_artista or ''} {hint_titulo or ''}".strip()
        sp = _call_integration("app_v4_new.integrations.spotify", "search_best_track", query)
        if not sp:
            sp = _call_integration("app_v4_new.integrations.spotify", "search_track", query)
        if isinstance(sp, dict):
            meta["titulo"] = meta["titulo"] or sp.get("title")
            meta["artista"] = meta["artista"] or sp.get("artist")
            meta["album"] = sp.get("album") or meta.get("album")
            meta["genero"] = sp.get("genre") or meta.get("genero")
            meta["capa_album"] = sp.get("cover") or meta.get("capa_album")

    # Discogs
    qd = f"{meta.get('artista') or ''} {meta.get('titulo') or ''}".strip()
    if qd:
        dgs = _call_integration("app_v4_new.integrations.discogs_api", "search_discogs", qd)
        if isinstance(dgs, dict):
            meta["genero"] = meta.get("genero") or dgs.get("genre")
            meta["album"] = meta.get("album") or dgs.get("album")
            meta["capa_album"] = meta.get("capa_album") or dgs.get("cover")

    # Deezer
    qz = f"{meta.get('artista') or ''} {meta.get('titulo') or ''}".strip()
    if qz:
        dz = _call_integration("app_v4_new.integrations.deezer_api", "search_deezer", qz)
        if isinstance(dz, dict):
            meta["album"] = meta.get("album") or dz.get("album")
            meta["capa_album"] = meta.get("capa_album") or dz.get("cover")
            if not meta.get("link_youtube") and dz.get("youtube"):
                meta["link_youtube"] = dz.get("youtube")

    # Shazam (se faltar básico)
    if not meta.get("titulo") or not meta.get("artista"):
        shz = _call_integration("app_v4_new.integrations.shazam_api", "recognize_file", str(path))
        if isinstance(shz, dict):
            meta["titulo"] = meta.get("titulo") or shz.get("title")
            meta["artista"] = meta.get("artista") or shz.get("artist")
            meta["album"] = meta.get("album") or shz.get("album")
            meta["capa_album"] = meta.get("capa_album") or shz.get("cover")

    # Fallbacks
    for k in ("titulo", "artista", "album", "genero"):
        if not meta.get(k):
            meta[k] = "Desconhecido"
    if not meta.get("capa_album"):
        meta["capa_album"] = "Não Encontrado"

    # Link YouTube p/ arquivo local
    if not meta.get("link_youtube") and meta.get("artista") != "Desconhecido" and meta.get("titulo") != "Desconhecido":
        meta["link_youtube"] = _buscar_youtube_link_simples(meta["artista"], meta["titulo"])

    return meta


def _salvar_no_db(nome: str, vetor: List[float], meta: Dict[str, Any]) -> Optional[int]:
    """Salva no DB usando upsert_musica/inserir_musica (conforme disponível)."""
    if _SALVAR_FUN is None:
        print("❌ Nenhuma função de persistência encontrada em app_v4_new.database.db")
        return None

    try:
        rid = _SALVAR_FUN(
            nome,
            vetor,
            meta.get("artista"),
            meta.get("titulo"),
            meta.get("album"),
            meta.get("genero"),
            meta.get("capa_album"),
            meta.get("link_youtube"),
        )
        return rid
    except TypeError:
        _SALVAR_FUN(
            nome,
            vetor,
            meta.get("artista"),
            meta.get("titulo"),
            meta.get("album"),
            meta.get("genero"),
            meta.get("capa_album"),
            meta.get("link_youtube"),
        )
        return None


def _print_topk_pretty(recs: List[Dict[str, Any]]) -> None:
    if not recs:
        print("ℹ️  Sem recomendações.")
        return
    print("\n✨ Top 3 Recomendações Musicais ✨\n")
    medalhas = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(recs[:3]):
        barra_len = int(round((r.get("similaridade", 0.0) / 100.0) * 23))
        barra = "█" * max(0, min(23, barra_len))
        titulo = (r.get("titulo") or "—")[:58]
        artista = (r.get("artista") or "—")[:57]
        link = (r.get("caminho") or "—")[:60]
        print("┌─{} Top {} ────────────────────────────────────────────────────────────┐".format(medalhas[i], i+1))
        print("│ 🎵 Título: {:<58}│".format(titulo))
        print("│ 🎤 Artista: {:<57}│".format(artista))
        print("│ 📊 Similaridade: {:>6.2f}% [{:<23}] │".format(float(r.get("similaridade", 0.0)), barra))
        print("│ 🔗 Link: {:<60}│".format(link))
        print("└───────────────────────────────────────────────────────────────────────┘\n")


# =====================================================================
# yt-dlp resiliente (evita 429 e "not available on this app")
# =====================================================================

def _make_ydl_opts_base() -> Dict[str, Any]:
    return {
        "format": "bestaudio/best",
        "quiet": True,
        "noplaylist": True,
        "outtmpl": str(DOWNLOADS_DIR / "%(title)s-%(id)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
        ],
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 1,
        "throttledratelimit": 1024 * 1024,  # 1MB/s para evitar estrangular
        "nocheckcertificate": True,
        "geo_bypass": True,
        "noprogress": True,
    }


def _make_ydl_opts_for_client(client: str, cookiefile: Optional[str] = None, is_playlist: bool = False) -> Dict[str, Any]:
    opts = _make_ydl_opts_base()
    exargs: Dict[str, Any] = {"youtube": {"player_client": [client]}}
    if is_playlist:
        exargs["youtubetab"] = {"skip": ["authcheck"]}
        opts["yesplaylist"] = True
        opts["noplaylist"] = False
    opts["extractor_args"] = exargs

    if cookiefile and Path(cookiefile).expanduser().exists():
        opts["cookiefile"] = str(Path(cookiefile).expanduser())

    # cabeçalhos ajudam em alguns cenários
    opts["http_headers"] = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    return opts


def _download_single_video(link: str, clients: List[str], cookiefile: Optional[str] = None) -> Optional[Path]:
    """Tenta baixar um único vídeo usando varios player_client e backoff em 429."""
    max_attempts = len(clients) * 2  # 2 voltas na lista
    attempt = 0
    last_exc: Optional[Exception] = None

    while attempt < max_attempts:
        client = clients[attempt % len(clients)]
        ydl_opts = _make_ydl_opts_for_client(client, cookiefile=cookiefile, is_playlist=False)
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(link, download=True)
                if not info:
                    raise RuntimeError("Sem info retornada.")
                fn = Path(ydl.prepare_filename(info))
                cand = fn.with_suffix(".mp3")
                if cand.exists():
                    return cand
                # fallback para m4a se o pós-processador falhar
                m4a = fn.with_suffix(".m4a")
                if m4a.exists():
                    return m4a
                # último recurso: o nome que o yt-dlp retornou
                if fn.exists():
                    return fn
                raise RuntimeError("Arquivo final não encontrado após download.")
        except Exception as e:
            last_exc = e
            msg = str(e)
            # 429 → aguarda e tenta com próximo client
            if "429" in msg or "Too Many Requests" in msg:
                wait = 1.5 + random.random() * 2.0
                print(f"⏳ 429 recebido (client={client}). Aguardando {wait:.1f}s e tentando outro client…")
                time.sleep(wait)
                attempt += 1
                continue
            # "not available on this app" → muda client imediatamente
            if "not available on this app" in msg.lower():
                print(f"🔁 Conteúdo indisponível no client '{client}'. Trocando de client…")
                attempt += 1
                continue
            # outros erros → tenta próximo client rapidamente
            print(f"⚠️  Falha com client '{client}': {msg}")
            attempt += 1
            time.sleep(0.5)

    print(f"❌ Erro ao baixar (último erro): {last_exc}")
    return None


def _download_playlist(link: str, clients: List[str], cookiefile: Optional[str] = None) -> List[Path]:
    """Baixa playlist tentando múltiplos clients e skip=authcheck. Retorna lista de arquivos baixados."""
    baixados: List[Path] = []
    last_exc: Optional[Exception] = None

    for client in clients:
        ydl_opts = _make_ydl_opts_for_client(client, cookiefile=cookiefile, is_playlist=True)
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(link, download=True)
                entries = info.get("entries") if isinstance(info, dict) else None
                if not entries:
                    raise RuntimeError("Nenhuma entrada na playlist (pode precisar de auth).")
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    fn = Path(ydl.prepare_filename(e))
                    cand = fn.with_suffix(".mp3")
                    if cand.exists():
                        baixados.append(cand)
                    elif fn.exists():
                        baixados.append(fn)
                if baixados:
                    return baixados
        except Exception as e:
            last_exc = e
            msg = str(e)
            if "429" in msg or "Too Many Requests" in msg:
                wait = 1.5 + random.random() * 2.0
                print(f"⏳ 429 na playlist (client={client}). Aguardando {wait:.1f}s e tentando outro client…")
                time.sleep(wait)
                continue
            print(f"⚠️  Falha na playlist com client '{client}': {msg}")
            continue

    if not baixados and last_exc:
        print(f"❌ Erro ao baixar playlist (último erro): {last_exc}")
    return baixados


# =====================================================================
# Funções expostas ao menu
# =====================================================================

def processar_audio_local(caminho: str, sr: int = 22050, k_recs: int = 3, recomendar: bool = True) -> None:
    """
    Processa UM arquivo local:
    - Extrai features
    - Enriquece metadados (Spotify/Discogs/Deezer/Shazam) + busca YouTube
    - Salva no DB
    - (opcional) apaga o arquivo após ingestão
    - Mostra top-3 recomendações (se recomendar=True)
    """
    p = Path(caminho).expanduser().resolve()
    if not p.exists() or not p.is_file():
        print(f"❌ Arquivo inválido: {p}")
        return

    print("🔧 Extraindo features…")
    vetor = extrair_caracteristicas(str(p), sr=sr)
    if vetor is None:
        print("❌ Falha ao extrair características.")
        return
    if EXPECTED_FEATURE_LENGTH and len(vetor) != int(EXPECTED_FEATURE_LENGTH):
        print(f"❌ Vetor com tamanho inesperado ({len(vetor)} != {EXPECTED_FEATURE_LENGTH}).")
        return

    artista_hint, titulo_hint = _parse_hints_from_filename(p.name)

    print("🟢 Buscando metadados (Spotify → Discogs → Deezer → Shazam)…")
    meta = _obter_metadados(p, artista_hint, titulo_hint)

    if meta.get("link_youtube") in (None, "", str(p)):
        meta["link_youtube"] = _buscar_youtube_link_simples(meta.get("artista", ""), meta.get("titulo", ""))

    print("💾 Gravando no MySQL (tabela)…")
    rid = _salvar_no_db(p.name, list(map(float, vetor)), meta)

    rot_t = meta.get("titulo") or "?"
    rot_a = meta.get("artista") or "?"
    rid_txt = f"id={rid}" if rid is not None else "id=?"
    print(f"✅ Indexado {rid_txt}  {p.name}  →  {rot_t} — {rot_a}")

    if recomendar:
        try:
            print("🤝 Gerando recomendações…")
            recs = recomendar_por_audio(p, k=k_recs, sr=sr, excluir_nome=p.name)
            _print_topk_pretty(recs[:k_recs])
        except Exception as e:
            print(f"⚠️  Não foi possível gerar recomendações agora: {e}")

    if DELETE_AUDIO_AFTER_INGEST:
        try:
            os.remove(str(p))
        except Exception:
            pass


def processar_link_youtube(link: str,
                           enriquecer: bool = True,
                           recomendar: bool = True,
                           k_recs: int = 3,
                           sr: int = 22050) -> None:
    """
    Baixa UM link do YouTube com fallback de clients/cookies e processa como local.
    Parâmetros 'enriquecer' e 'recomendar' mantidos por compatibilidade com o menu.
    """
    print("⬇️ Baixando do YouTube…")
    cookiefile = COOKIEFILE_PATH
    destino = _download_single_video(link, clients=YTDLP_CLIENT_SEQUENCE, cookiefile=cookiefile)

    if not destino or not destino.exists():
        print("❌ Erro ao baixar: não foi possível obter o áudio.")
        return

    # Processa o arquivo baixado
    processar_audio_local(str(destino), sr=sr, k_recs=k_recs, recomendar=recomendar)


def upload_em_massa(pasta: str, sr: int = 22050, k_recs: int = 3) -> None:
    """Processa TODOS os áudios da pasta (sem recursão)."""
    root = Path(pasta).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"❌ Pasta inválida: {root}")
        return

    arquivos = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in (".mp3", ".wav", ".m4a")]
    if not arquivos:
        print("ℹ️  Nenhum arquivo de áudio encontrado.")
        return

    total = len(arquivos)
    for i, p in enumerate(sorted(arquivos), 1):
        print(f"[{i}/{total}] {p.name}")
        # em massa: recomendações deixam lento; setar recomendar=False
        processar_audio_local(str(p), sr=sr, k_recs=k_recs, recomendar=False)


def playlist_bulk(link_playlist: str, sr: int = 22050, k_recs: int = 3) -> None:
    """
    Baixa uma playlist do YouTube e ingere faixa a faixa.
    Usa extractor_args para evitar o erro de authcheck e fallback de clients.
    """
    print("⬇️ Baixando playlist (pode demorar)…")
    cookiefile = COOKIEFILE_PATH
    baixados = _download_playlist(link_playlist, clients=YTDLP_CLIENT_SEQUENCE, cookiefile=cookiefile)

    if not baixados:
        print("Nenhum item baixado da playlist.")
        return

    print(f"▶️ Playlist: {len(baixados)} itens baixados.")
    for idx, p in enumerate(baixados, 1):
        print(f"[{idx}/{len(baixados)}] {p.name}")
        processar_audio_local(str(p), sr=sr, k_recs=k_recs, recomendar=False)


# === Alias para compatibilidade com o menu ===
def processar_playlist_youtube(link: str, sr: int = 22050, k_recs: int = 3) -> None:
    """Compat: alguns menus importam esse nome; delega para playlist_bulk()."""
    return playlist_bulk(link, sr=sr, k_recs=k_recs)


def listar_ultimos_itens(limite: int = 10) -> None:
    """Lista os últimos itens do banco usando listar() do seu módulo DB, se existir."""
    if _DB_LISTAR is None:
        print("⚠️  Função 'listar' não está disponível no seu app_v4_new.database.db.")
        return
    try:
        rows = _DB_LISTAR(limite=limite)
    except TypeError:
        rows = _DB_LISTAR(limite)
    if not rows:
        print("ℹ️  Nenhum registro encontrado.")
        return

    print("\nid | titulo                 | artista                | caminho/yt")
    print("----+------------------------+------------------------+----------------------------")
    for r in rows:
        rid = r.get("id", "?") if isinstance(r, dict) else (r[0] if len(r) > 0 else "?")
        t = r.get("titulo", "") if isinstance(r, dict) else (r[1] if len(r) > 1 else "")
        a = r.get("artista", "") if isinstance(r, dict) else (r[2] if len(r) > 2 else "")
        lnk = r.get("link_youtube", "") if isinstance(r, dict) else (r[3] if len(r) > 3 else "")
        print(f"{rid:<3} | {t[:22]:<22} | {a[:22]:<22} | {lnk[:26]}")


def recalibrar_e_recomendar(k: int = 3, sr: int = 22050) -> None:
    """
    Recalibra (reajusta o scaler por bloco) e, se o usuário quiser, recomenda por um arquivo local.
    """
    print("🛠️  Reajustando padronizador por bloco (scaler)…")
    Xs, ids, metas, scaler = preparar_base_escalada()
    if Xs.shape[0] >= 1:
        print(f"✅ Scalado {Xs.shape[0]} faixas x {Xs.shape[1]} dims.")
    else:
        print("⚠️  Catálogo insuficiente para calibrar. Ingerir mais faixas e tentar novamente.")
        return

    path_str = input("\nArquivo de áudio para recomendar (ou Enter para pular): ").strip()

    if not path_str:
        print("➡️  Pulando recomendação por áudio. Você pode usar as opções 1/2/3 a qualquer momento.")
        return

    p = Path(path_str)
    if not p.exists():
        print(f"⚠️  Caminho não existe: '{p}'. Informe um arquivo .mp3/.wav válido.")
        return
    if not p.is_file():
        print(f"⚠️  '{p}' é uma pasta. Informe um arquivo .mp3/.wav válido.")
        return

    try:
        recs = recomendar_por_audio(p, k=k, sr=sr, excluir_nome=p.name)
    except Exception as e:
        print(f"❌ Erro ao recomendar por áudio: {e}")
        return

    if not recs:
        print("ℹ️  Não foi possível calcular recomendações para este arquivo.")
        return

    _print_topk_pretty(recs[:k])


def contar_musicas() -> int:
    """
    Conta quantas músicas existem no catálogo.
    Preferência:
      1) usa 'contar()' do seu módulo DB, se existir;
      2) usa 'conectar()' e SELECT COUNT(*);
      3) fallback: len(ids) de carregar_matriz().
    """
    if callable(_DB_CONTAR):
        try:
            n = int(_DB_CONTAR())
            return n
        except Exception:
            pass

    if callable(_DB_CONNECT):
        try:
            with _DB_CONNECT() as conn:
                with conn.cursor() as cur:
                    if EXPECTED_FEATURE_LENGTH:
                        cur.execute(
                            f"""
                            SELECT COUNT(*) FROM {DB_TABLE_NAME}
                            WHERE (LENGTH(caracteristicas) - LENGTH(REPLACE(caracteristicas, ',', ''))) + 1 = %s
                            """,
                            (int(EXPECTED_FEATURE_LENGTH),),
                        )
                    else:
                        cur.execute(f"SELECT COUNT(*) FROM {DB_TABLE_NAME}")
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        return int(row[0])
        except Exception:
            pass

    try:
        X, ids, metas = carregar_matriz()
        return int(len(ids)) if ids is not None else 0
    except Exception:
        return 0
