
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import traceback
import time
import json

import numpy as np
import librosa

try:
    from dotenv import load_dotenv  # opcional
    load_dotenv()
except Exception:
    pass

from .config import APP_NAME, APP_VERSION
from .audio.extrator_fft import extrair_features_completas
from .storage.db_utils import (
    default_db_path, ensure_schema, insert_track, list_tracks, AUDIO_EXTS
)
from .recom.knn_recommender import (
    recomendar_por_id, recomendar_por_audio, preparar_base_escalada
)
from .recognition.recognizer import reconhecer_com_cache

BANNER = r"""
   ______                     _            __  ___      __      __     
  / ____/___  __  _______  __(_)___  ___  /  |/  /___ _/ /___ _/ /____ 
 / / __/ __ \/ / / / ___/ / / / __ \/ _ \/ /|_/ / __ `/ / __ `/ __/ _ \\ 
/ /_/ / /_/ / /_/ (__  ) /_/ / / / /  __/ /  / / /_/ / / /_/ / /_/  __/
\____/\____/\__,_/____/\__, /_/ /_/\___/_/  /_/\__,_/_/\__,_/\__/\___/ 
                      /____/          Similaridade musical por Fourier
"""

def _cabecalho():
    print(BANNER)
    print(f"{APP_NAME} v{APP_VERSION}")
    print("-" * 72)

def _tabela(rows: list[dict], columns: list[str]) -> str:
    larguras = [len(c) for c in columns]
    srows = []
    for r in rows:
        line = []
        for i, c in enumerate(columns):
            v = r.get(c, "")
            v = "" if v is None else str(v)
            larguras[i] = max(larguras[i], len(v))
            line.append(v)
        srows.append(line)
    sep = "+".join("-" * (w + 2) for w in larguras)
    out = []
    header = " | ".join(c.ljust(w) for c, w in zip(columns, larguras))
    out.append(header)
    out.append(sep)
    for line in srows:
        out.append(" | ".join(v.ljust(w) for v, w in zip(line, larguras)))
    return "\n".join(out)

def _coletar_arquivos(path: Path, recursivo: bool) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in AUDIO_EXTS else []
    padrao = "**/*" if recursivo else "*"
    return [p for p in path.glob(padrao) if p.is_file() and p.suffix.lower() in AUDIO_EXTS]

# --------------- Subcomandos ---------------

def cmd_indexar(args: argparse.Namespace) -> int:
    _cabecalho()
    db = Path(args.db) if args.db else default_db_path()
    ensure_schema(db)

    caminhos: list[Path] = []
    for p in args.path:
        P = Path(p)
        if not P.exists():
            print(f"⚠️  Ignorando: {p} (não encontrado)")
            continue
        caminhos.extend(_coletar_arquivos(P, args.recursivo))

    if not caminhos:
        print("Nenhum arquivo de áudio válido encontrado.")
        return 1

    print(f"Banco de dados: {db}")
    print(f"Arquivos a processar: {len(caminhos)}\n")

    ok, falha = 0, 0
    for i, ap in enumerate(caminhos, 1):
        t0 = time.time()
        try:
            y, sr = librosa.load(str(ap), sr=args.sr, mono=True)
            vec = extrair_features_completas(y, sr)

            # Reconhecimento (opcional)
            titulo = ap.stem
            artista = "desconhecido"
            if args.enriquecer:
                rec = reconhecer_com_cache(db, ap, use_cache=True)
                if rec.title:  titulo = rec.title
                if rec.artist: artista = rec.artist

            new_id = insert_track(db, titulo=titulo, artista=artista, caminho=str(ap.resolve()), vec=vec, upsert=True)
            dt = time.time() - t0
            print(f"[{i}/{len(caminhos)}] ✅ id={new_id} {ap.name} ({dt:.2f}s)  ->  {titulo} — {artista}")
            ok += 1
        except Exception as e:
            falha += 1
            print(f"[{i}/{len(caminhos)}] ❌ {ap.name} -> {e}")
            if args.verbose:
                traceback.print_exc()
    print(f"\nConcluído. Sucesso: {ok}  |  Falhas: {falha}")
    return 0 if ok > 0 and falha == 0 else (0 if ok > 0 else 1)

def cmd_recomendar_id(args: argparse.Namespace) -> int:
    _cabecalho()
    db = Path(args.db) if args.db else default_db_path()
    res = recomendar_por_id(db, song_id=args.id, k=args.k)
    if not res:
        print("Nenhuma recomendação encontrada.")
        return 0
    cols = ["id", "titulo", "artista", "caminho", "similaridade"]
    print(_tabela(res, [c for c in cols if c in res[0]]))
    if args.json:
        print("\nJSON:")
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0

def cmd_recomendar_arquivo(args: argparse.Namespace) -> int:
    _cabecalho()
    db = Path(args.db) if args.db else default_db_path()
    res = recomendar_por_audio(db, audio_path=args.arquivo, k=args.k, sr=args.sr)
    if not res:
        print("Nenhuma recomendação encontrada.")
        return 0
    cols = ["id", "titulo", "artista", "caminho", "similaridade"]
    print(_tabela(res, [c for c in cols if c in res[0]]))
    if args.json:
        print("\nJSON:")
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0

def cmd_reconhecer(args: argparse.Namespace) -> int:
    _cabecalho()
    db = Path(args.db) if args.db else default_db_path()
    P = Path(args.caminho)
    caminhos = []
    if P.is_dir():
        caminhos = _coletar_arquivos(P, recursivo=True)
    elif P.is_file():
        caminhos = [P]
    else:
        print(f"Caminho não encontrado: {P}")
        return 1

    if not caminhos:
        print("Nenhum áudio válido encontrado.")
        return 1

    saida = []
    for i, ap in enumerate(caminhos, 1):
        rec = reconhecer_com_cache(db, ap, use_cache=True)
        row = {"arquivo": str(ap), **rec.to_dict()}
        saida.append(row)
        print(f"[{i}/{len(caminhos)}] {ap.name} -> {row.get('title')} — {row.get('artist')} ({row.get('source') or '-'})")

    if args.json:
        print("\nJSON:")
        print(json.dumps(saida, ensure_ascii=False, indent=2))
    return 0

def cmd_reajustar_scaler(args: argparse.Namespace) -> int:
    _cabecalho()
    db = Path(args.db) if args.db else default_db_path()
    print(f"Reajustando scaler por bloco a partir do banco: {db}")
    from .recom.knn_recommender import preparar_base_escalada
    Xs, ids, metas, scaler = preparar_base_escalada(db)
    print(f"✅ Scaler treinado e salvo. Matriz escalada: {Xs.shape[0]} músicas x {Xs.shape[1]} dims.")
    return 0

def cmd_banco_listar(args: argparse.Namespace) -> int:
    _cabecalho()
    db = Path(args.db) if args.db else default_db_path()
    rows = list_tracks(db, limit=args.limite)
    if not rows:
        print("Banco vazio.")
        return 0
    cols = []
    for c in ("id", "titulo", "artista", "caminho", "created_at"):
        if c in rows[0]:
            cols.append(c)
    print(_tabela(rows, cols))
    return 0

def cmd_sobre(args: argparse.Namespace) -> int:
    _cabecalho()
    print(f"{APP_NAME} v{APP_VERSION}")
    print("Engine de similaridade musical + pipeline de reconhecimento:")
    print(" - Normalização de loudness (LUFS/RMS)")
    print(" - HPSS (harmônico x percussivo) + features sincronizadas ao pulso")
    print(" - MFCC(+Δ,+Δ²), Spectral Contrast, chroma alinhado + TIV-6, Tonnetz")
    print(" - Rítmicas/espectrais (ZCR, centroid, bandwidth, rolloff) + tempo/variância")
    print(" - Reconhecimento: Shazam (opcional), AudD, Discogs + cache em SQLite")
    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=APP_NAME, description=f"{APP_NAME} — Similaridade musical baseada em Fourier")
    sub = p.add_subparsers(dest="cmd")

    # indexar (alias: ingest)
    pi = sub.add_parser("indexar", help="Indexa arquivos de áudio no banco (extrai features).", aliases=["ingest"])
    pi.add_argument("path", nargs="+", help="Arquivo(s) ou pasta(s).")
    pi.add_argument("--recursivo", "-r", action="store_true", help="Buscar recursivamente em subpastas.")
    pi.add_argument("--enriquecer", action="store_true", help="Tentar reconhecer metadados (Shazam/AudD/Discogs).")
    pi.add_argument("--sr", type=int, default=22050, help="Sample rate para leitura (padrão: 22050).")
    pi.add_argument("--db", type=str, default=None, help="Caminho do banco SQLite (padrão: autodetect).")
    pi.add_argument("--verbose", "-v", action="store_true", help="Erros detalhados (stacktrace).")
    pi.set_defaults(func=cmd_indexar)

    # reconhecer (alias: recognize)
    prec = sub.add_parser("reconhecer", help="Reconhece metadados (com cache) para arquivo ou pasta.", aliases=["recognize"])
    prec.add_argument("caminho", help="Arquivo de áudio ou pasta.")
    prec.add_argument("--db", type=str, default=None, help="Caminho do banco SQLite.")
    prec.add_argument("--json", action="store_true", help="Imprimir JSON.")
    prec.set_defaults(func=cmd_reconhecer)

    # recomendar-id (alias: recommend-id)
    pr = sub.add_parser("recomendar-id", help="Recomenda similares pelo id no banco.", aliases=["recommend-id"])
    pr.add_argument("id", type=int, help="ID da música no banco.")
    pr.add_argument("--k", type=int, default=10, help="Número de vizinhos retornados.")
    pr.add_argument("--db", type=str, default=None, help="Caminho do banco SQLite.")
    pr.add_argument("--json", action="store_true", help="Imprimir JSON.")
    pr.set_defaults(func=cmd_recomendar_id)

    # recomendar-arquivo (alias: recommend-file)
    prf = sub.add_parser("recomendar-arquivo", help="Recomenda similares por um arquivo de áudio.", aliases=["recommend-file"])
    prf.add_argument("arquivo", type=str, help="Caminho do arquivo de áudio.")
    prf.add_argument("--k", type=int, default=10, help="Número de vizinhos retornados.")
    prf.add_argument("--sr", type=int, default=22050, help="Sample rate de leitura.")
    prf.add_argument("--db", type=str, default=None, help="Caminho do banco SQLite.")
    prf.add_argument("--json", action="store_true", help="Imprimir JSON.")
    prf.set_defaults(func=cmd_recomendar_arquivo)

    # normalizador (alias: scaler)
    ps = sub.add_parser("normalizador", help="Operações com o scaler por bloco.", aliases=["scaler"])
    ps_sub = ps.add_subparsers(dest="subcmd")
    psr = ps_sub.add_parser("reajustar", help="Refaz o ajuste do scaler a partir do banco atual.", aliases=["rebuild"])
    psr.add_argument("--db", type=str, default=None, help="Caminho do banco SQLite.")
    psr.set_defaults(func=cmd_reajustar_scaler)

    # banco (alias: db)
    pdb = sub.add_parser("banco", help="Operações de banco de dados.", aliases=["db"])
    pdb_sub = pdb.add_subparsers(dest="subcmd")
    pdbl = pdb_sub.add_parser("listar", help="Lista as últimas faixas inseridas.", aliases=["list"])
    pdbl.add_argument("--limite", type=int, default=20, help="Número de linhas (padrão: 20).")
    pdbl.add_argument("--db", type=str, default=None, help="Caminho do banco SQLite.")
    pdbl.set_defaults(func=cmd_banco_listar)

    # sobre (alias: about)
    pa = sub.add_parser("sobre", help="Sobre o produto.", aliases=["about"])
    pa.set_defaults(func=cmd_sobre)

    return p

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        _cabecalho()
        print("Use um dos comandos: indexar | reconhecer | recomendar-id | recomendar-arquivo | normalizador reajustar | banco listar | sobre")
        print(f"Ex.: python -m app_v4.main indexar ./minhas_musicas -r --enriquecer")
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
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
