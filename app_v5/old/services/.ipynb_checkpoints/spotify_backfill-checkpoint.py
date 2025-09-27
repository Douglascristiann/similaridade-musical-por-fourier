# -*- coding: utf-8 -*-
from __future__ import annotations
import time
import argparse
import mysql.connector
from typing import Dict, Any, List, Optional

from app_v5.config import DB_CONFIG, DB_TABLE_NAME
from app_v5.integrations.spotify import enrich_from_spotify

def _fetch_sem_spotify(limit: int) -> List[Dict[str, Any]]:
    with mysql.connector.connect(**DB_CONFIG) as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(f"""
                SELECT id, titulo, artista
                  FROM {DB_TABLE_NAME}
                 WHERE (link_spotify IS NULL OR link_spotify = '')
                   AND (titulo IS NOT NULL AND titulo <> '')
              ORDER BY id ASC
                 LIMIT %s
            """, (int(limit),))
            return cur.fetchall()

def _salvar_link_spotify(mid: int, link: Optional[str]) -> None:
    with mysql.connector.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {DB_TABLE_NAME} SET link_spotify=%s WHERE id=%s", (link, int(mid)))
            conn.commit()

def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill de link do Spotify na base.")
    ap.add_argument("--limit", type=int, default=500, help="Qtd máxima de registros para tentar.")
    ap.add_argument("--sleep", type=float, default=0.3, help="Pausa entre chamadas (s).")
    ap.add_argument("--dry-run", action="store_true", help="Não grava no banco (só simula).")
    args = ap.parse_args()

    rows = _fetch_sem_spotify(args.limit)
    if not rows:
        print("Nada a atualizar.")
        return

    ok = 0
    skip = 0
    for r in rows:
        title = r.get("titulo")
        artist = r.get("artista")
        if not title:
            continue

        try:
            res = enrich_from_spotify(artist, title, album_hint=None, duration_sec=None)
        except Exception as e:
            print(f"[ERRO] id={r['id']} ao consultar Spotify: {e}")
            continue

        link = (res or {}).get("link_spotify")
        if link:
            if args.dry_run:
                print(f"[DRY] id={r['id']}: {artist} — {title} -> {link}")
            else:
                _salvar_link_spotify(r["id"], link)
                print(f"[OK]  id={r['id']}: {artist} — {title} -> {link}")
                ok += 1
        else:
            print(f"[--]  id={r['id']}: {artist} — {title} -> sem link")
            skip += 1

        time.sleep(args.sleep)

    print(f"Feito. gravados={ok} sem_link={skip} total={len(rows)}")

if __name__ == "__main__":
    main()
