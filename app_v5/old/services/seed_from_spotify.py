# app_v5/services/seed_from_spotify.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import time
import argparse
import logging
from typing import Iterable, Dict, Optional

import requests

from app_v5.services.youtube_backfill import buscar_youtube_link
from app_v5.services.ingest import processar_link_youtube

log = logging.getLogger("FourierMatch")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _get_token() -> str:
    cid = os.getenv("SPOTIFY_CLIENT_ID")
    cs = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not cid or not cs:
        raise RuntimeError("Defina SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET no ambiente/.env")
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(cid, cs),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _playlist_id(url_or_id: str) -> str:
    m = re.search(r"playlist/([A-Za-z0-9]+)", url_or_id)
    return m.group(1) if m else url_or_id


def _api_get(url: str, token: str, params: Optional[dict] = None, retries: int = 3) -> dict:
    """GET com tratamento básico de 429/404/401."""
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(max(1, retries)):
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "1"))
            time.sleep(wait + 1)
            continue
        if r.status_code in (401, 403):
            raise RuntimeError("Token Spotify expirado/ inválido ou sem permissão. Gere novamente.")
        if r.status_code == 404:
            r.raise_for_status()
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Falha ao fazer GET no Spotify API")


def iter_playlist_tracks(
    token: str, playlist: str, limit: Optional[int] = 50, market: Optional[str] = None
) -> Iterable[Dict[str, str]]:
    """Itera (title, artist) da playlist, com fallback quando /tracks retorna 404."""
    market = market or os.getenv("SPOTIFY_MARKET", "BR")
    pid = _playlist_id(playlist)

    # 1) Caminho oficial: /v1/playlists/{id}/tracks
    url = f"https://api.spotify.com/v1/playlists/{pid}/tracks"
    params = {"limit": 100, "market": market, "fields": "items(track(name,artists(name))),next"}
    got = 0
    try:
        while url and (limit is None or got < limit):
            data = _api_get(url, token, params=params)
            for it in data.get("items", []):
                t = it.get("track") or {}
                name = (t.get("name") or "").strip()
                arts = t.get("artists") or []
                if not name or not arts:
                    continue
                yield {"title": name, "artist": arts[0]["name"]}
                got += 1
                if limit is not None and got >= limit:
                    return
            url = data.get("next")
            params = None  # a URL "next" já contém a query
        return
    except requests.HTTPError as e:
        if not (e.response is not None and e.response.status_code == 404):
            # erro diferente de 404 → propaga
            raise

    # 2) Fallback: /v1/playlists/{id}?fields=tracks(...)
    log.info(f"   ↪️ fallback: GET /v1/playlists/{pid}?fields=tracks(...), possivelmente playlist regional")
    url = f"https://api.spotify.com/v1/playlists/{pid}"
    params = {"market": market, "fields": "tracks(items(track(name,artists(name))),next)"}
    data = _api_get(url, token, params=params)

    tracks = (data.get("tracks") or {}).get("items") or []
    next_url = (data.get("tracks") or {}).get("next")
    for it in tracks:
        t = it.get("track") or {}
        name = (t.get("name") or "").strip()
        arts = t.get("artists") or []
        if not name or not arts:
            continue
        yield {"title": name, "artist": arts[0]["name"]}
        got += 1
        if limit is not None and got >= limit:
            return

    # paginação do fallback
    url = next_url
    while url and (limit is None or got < limit):
        data = _api_get(url, token)  # 'next' já inclui market/limit
        for it in data.get("items", []):
            t = it.get("track") or {}
            name = (t.get("name") or "").strip()
            arts = t.get("artists") or []
            if not name or not arts:
                continue
            yield {"title": name, "artist": arts[0]["name"]}
            got += 1
            if limit is not None and got >= limit:
                return
        url = data.get("next")


def main():
    ap = argparse.ArgumentParser(description="Semear base a partir de playlists do Spotify")
    ap.add_argument("-p", "--playlist", action="append", default=[], help="URL ou ID de playlist do Spotify (pode repetir)")
    ap.add_argument("--limit-per", type=int, default=40, help="máximo de faixas por playlist")
    ap.add_argument("--sleep", type=float, default=0.6, help="intervalo entre buscas do YouTube (s)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.playlist:
        log.error("Informe ao menos uma --playlist (URL ou ID do Spotify).")
        return

    token = _get_token()
    market = os.getenv("SPOTIFY_MARKET", "BR")
    ok = fail = 0

    for p in args.playlist:
        log.info(f"🎧 Playlist Spotify: {p} (market={market})")
        try:
            for tr in iter_playlist_tracks(token, p, limit=args.limit_per, market=market):
                a, t = tr["artist"], tr["title"]
                yt = buscar_youtube_link(a, t)
                if not yt:
                    log.warning(f"[skip] {a} — {t} (YT não encontrado)")
                    fail += 1
                    continue
                if args.dry_run:
                    print(f"[dry] {a} — {t} -> {yt}")
                else:
                    try:
                        processar_link_youtube(yt, enriquecer=True, recomendar=False)
                        ok += 1
                    except Exception as e:
                        log.error(f"[erro] {a} — {t}: {e}")
                        fail += 1
                time.sleep(args.sleep)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            log.error(f"❌ Falha ao acessar playlist ({code}): {p}")
            fail += 1
            continue
        except Exception as e:
            log.error(f"❌ Erro inesperado na playlist {p}: {e}")
            fail += 1
            continue

    print(f"Feito. ok={ok} falhas={fail}")


if __name__ == "__main__":
    main()
