
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import traceback
import time
import json
import os

import numpy as np
import librosa

try:
    from dotenv import load_dotenv  # optional
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
from .recognition.recognizer import recognize_with_cache

BANNER = r"""
   ______                     _            __  ___      __      __     
  / ____/___  __  _______  __(_)___  ___  /  |/  /___ _/ /___ _/ /____ 
 / / __/ __ \/ / / / ___/ / / / __ \/ _ \/ /|_/ / __ `/ / __ `/ __/ _ \\ 
/ /_/ / /_/ / /_/ (__  ) /_/ / / / /  __/ /  / / /_/ / / /_/ / /_/  __/
\____/\____/\__,_/____/\__, /_/ /_/\___/_/  /_/\__,_/_/\__,_/\__/\___/ 
                      /____/          Similaridade musical por Fourier
"""

def _print_header():
    print(BANNER)
    print(f"{APP_NAME} v{APP_VERSION}")
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

def _discover_audio_paths(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in AUDIO_EXTS else []
    pattern = "**/*" if recursive else "*"
    return [p for p in path.glob(pattern) if p.is_file() and p.suffix.lower() in AUDIO_EXTS]

# --------------- Subcommands ---------------

def cmd_ingest(args: argparse.Namespace) -> int:
    _print_header()
    db = Path(args.db) if args.db else default_db_path()
    ensure_schema(db)

    paths: list[Path] = []
    for p in args.path:
        P = Path(p)
        if not P.exists():
            print(f"⚠️  Ignoring: {p} (not found)")
            continue
        paths.extend(_discover_audio_paths(P, args.recursive))

    if not paths:
        print("No valid audio files found.")
        return 1

    print(f"Database: {db}")
    print(f"Files to process: {len(paths)}\n")

    ok, fail = 0, 0
    for i, ap in enumerate(paths, 1):
        t0 = time.time()
        try:
            y, sr = librosa.load(str(ap), sr=args.sr, mono=True)
            vec = extrair_features_completas(y, sr)

            # Recognition (optional enrichment)
            titulo = ap.stem
            artista = "desconhecido"
            if args.enrich:
                rec = recognize_with_cache(db, ap, use_cache=True)
                if rec.title:  titulo = rec.title
                if rec.artist: artista = rec.artist

            new_id = insert_track(db, titulo=titulo, artista=artista, caminho=str(ap.resolve()), vec=vec, upsert=True)
            dt = time.time() - t0
            print(f"[{i}/{len(paths)}] ✅ id={new_id} {ap.name} ({dt:.2f}s)  ->  {titulo} — {artista}")
            ok += 1
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(paths)}] ❌ {ap.name} -> {e}")
            if args.verbose:
                traceback.print_exc()
    print(f"\nDone. Success: {ok}  |  Failures: {fail}")
    return 0 if ok > 0 and fail == 0 else (0 if ok > 0 else 1)

def cmd_recommend_id(args: argparse.Namespace) -> int:
    _print_header()
    db = Path(args.db) if args.db else default_db_path()
    res = recomendar_por_id(db, song_id=args.id, k=args.k)
    if not res:
        print("No recommendations found.")
        return 0
    cols = ["id", "titulo", "artista", "caminho", "similaridade"]
    print(_format_table(res, [c for c in cols if c in res[0]]))
    if args.json:
        print("\nJSON:")
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0

def cmd_recommend_file(args: argparse.Namespace) -> int:
    _print_header()
    db = Path(args.db) if args.db else default_db_path()
    res = recomendar_por_audio(db, audio_path=args.file, k=args.k, sr=args.sr)
    if not res:
        print("No recommendations found.")
        return 0
    cols = ["id", "titulo", "artista", "caminho", "similaridade"]
    print(_format_table(res, [c for c in cols if c in res[0]]))
    if args.json:
        print("\nJSON:")
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0

def cmd_recognize(args: argparse.Namespace) -> int:
    _print_header()
    db = Path(args.db) if args.db else default_db_path()
    P = Path(args.path)
    paths = []
    if P.is_dir():
        paths = _discover_audio_paths(P, recursive=True)
    elif P.is_file():
        paths = [P]
    else:
        print(f"Path not found: {P}")
        return 1

    if not paths:
        print("No valid audio found.")
        return 1

    out_rows = []
    for i, ap in enumerate(paths, 1):
        rec = recognize_with_cache(db, ap, use_cache=True)
        row = {"file": str(ap), **rec.to_dict()}
        out_rows.append(row)
        print(f"[{i}/{len(paths)}] {ap.name} -> {row.get('title')} — {row.get('artist')} ({row.get('source') or '-'})")

    if args.json:
        print("\nJSON:")
        print(json.dumps(out_rows, ensure_ascii=False, indent=2))
    return 0

def cmd_scaler_rebuild(args: argparse.Namespace) -> int:
    _print_header()
    db = Path(args.db) if args.db else default_db_path()
    print(f"Rebuilding per-block scaler from DB: {db}")
    from .recom.knn_recommender import preparar_base_escalada
    Xs, ids, metas, scaler = preparar_base_escalada(db)
    print(f"✅ Scaler trained and saved. Scaled matrix: {Xs.shape[0]} tracks x {Xs.shape[1]} dims.")
    return 0

def cmd_db_list(args: argparse.Namespace) -> int:
    _print_header()
    db = Path(args.db) if args.db else default_db_path()
    rows = list_tracks(db, limit=args.limit)
    if not rows:
        print("Empty DB.")
        return 0
    cols = []
    for c in ("id", "titulo", "artista", "caminho", "created_at"):
        if c in rows[0]:
            cols.append(c)
    print(_format_table(rows, cols))
    return 0

def cmd_about(args: argparse.Namespace) -> int:
    _print_header()
    print(f"{APP_NAME} v{APP_VERSION}")
    print("Fourier-friendly music similarity engine + recognition pipeline:")
    print(" - Loudness normalization (LUFS/RMS)")
    print(" - HPSS (harmonic vs percussive) + beat-synchronous features")
    print(" - MFCC(+Δ,+Δ²), Spectral Contrast, key-invariant chroma + TIV-6, Tonnetz")
    print(" - Rhythmic/spectral (ZCR, centroid, bandwidth, rolloff) + tempo/variance")
    print(" - Recognition: Shazam (optional), AudD, Discogs enrichment + SQLite cache")
    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=APP_NAME, description=f"{APP_NAME} — Fourier-based music similarity")
    sub = p.add_subparsers(dest="cmd")

    # ingest
    pi = sub.add_parser("ingest", help="Index audio files into the DB (extract features).")
    pi.add_argument("path", nargs="+", help="File(s) or folder(s).")
    pi.add_argument("--recursive", "-r", action="store_true", help="Search recursively.")
    pi.add_argument("--enrich", action="store_true", help="Try to recognize metadata (Shazam/AudD/Discogs).")
    pi.add_argument("--sr", type=int, default=22050, help="Sample rate for reading (default: 22050).")
    pi.add_argument("--db", type=str, default=None, help="SQLite DB path (default: autodetect).")
    pi.add_argument("--verbose", "-v", action="store_true", help="Verbose errors (stacktrace).")
    pi.set_defaults(func=cmd_ingest)

    # recognize
    prec = sub.add_parser("recognize", help="Recognize metadata for a file or folder (with cache).")
    prec.add_argument("path", help="Audio file or folder.")
    prec.add_argument("--db", type=str, default=None, help="SQLite DB path.")
    prec.add_argument("--json", action="store_true", help="Print JSON output.")
    prec.set_defaults(func=cmd_recognize)

    # recommend id
    pr = sub.add_parser("recommend-id", help="Recommend similar tracks by DB id.")
    pr.add_argument("id", type=int, help="Track id in DB.")
    pr.add_argument("--k", type=int, default=10, help="Number of neighbors returned.")
    pr.add_argument("--db", type=str, default=None, help="SQLite DB path.")
    pr.add_argument("--json", action="store_true", help="Print JSON.")
    pr.set_defaults(func=cmd_recommend_id)

    # recommend file
    prf = sub.add_parser("recommend-file", help="Recommend similar tracks by audio file.")
    prf.add_argument("file", type=str, help="Audio file path.")
    prf.add_argument("--k", type=int, default=10, help="Number of neighbors returned.")
    prf.add_argument("--sr", type=int, default=22050, help="Reading sample rate.")
    prf.add_argument("--db", type=str, default=None, help="SQLite DB path.")
    prf.add_argument("--json", action="store_true", help="Print JSON.")
    prf.set_defaults(func=cmd_recommend_file)

    # scaler
    ps = sub.add_parser("scaler", help="Per-block scaler ops.")
    ps_sub = ps.add_subparsers(dest="subcmd")
    psr = ps_sub.add_parser("rebuild", help="Refit scaler from current DB.")
    psr.add_argument("--db", type=str, default=None, help="SQLite DB path.")
    psr.set_defaults(func=cmd_scaler_rebuild)

    # db
    pdb = sub.add_parser("db", help="DB operations.")
    pdb_sub = pdb.add_subparsers(dest="subcmd")
    pdbl = pdb_sub.add_parser("list", help="List latest tracks.")
    pdbl.add_argument("--limit", type=int, default=20, help="Rows to show (default: 20).")
    pdbl.add_argument("--db", type=str, default=None, help="SQLite DB path.")
    pdbl.set_defaults(func=cmd_db_list)

    # about
    pa = sub.add_parser("about", help="About the product.")
    pa.set_defaults(func=cmd_about)

    return p

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        _print_header()
        print("Use one of: ingest | recognize | recommend-id | recommend-file | scaler rebuild | db list | about")
        print(f"Ex.: python -m app_v4.main ingest ./my_music -r --enrich")
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
