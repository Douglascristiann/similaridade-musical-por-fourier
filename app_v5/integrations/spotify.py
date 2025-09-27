# -*- coding: utf-8 -*-
from __future__ import annotations
import base64
import time
import os
import re
from typing import Optional, Dict, Any, List
import requests
from dotenv import load_dotenv

load_dotenv()

# --- Configuração ---
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_MARKET = os.getenv("SPOTIFY_MARKET", "BR")
# CORREÇÃO: URLs oficiais da API
SPOTIFY_API_BASE_URL = "https://api.spotify.com"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    raise RuntimeError("As credenciais SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET não foram configuradas.")

_TOKEN_VAL: dict = {"access_token": None, "exp": 0.0}

# --- Funções de API ---
def _get_token() -> Optional[str]:
    global _TOKEN_VAL
    now = time.time()
    if _TOKEN_VAL.get("access_token") and _TOKEN_VAL.get("exp", 0) > now + 60:
        return _TOKEN_VAL["access_token"]
    
    auth_str = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    auth_bytes = base64.b64encode(auth_str.encode())
    
    try:
        r = requests.post(
           SPOTIFY_TOKEN_URL,
           data={"grant_type": "client_credentials"},
           headers={"Authorization": f"Basic {auth_bytes.decode()}"},
           timeout=15
        )
        r.raise_for_status()
        data = r.json()
        _TOKEN_VAL["access_token"] = data.get("access_token")
        _TOKEN_VAL["exp"] = time.time() + float(data.get("expires_in", 3600))
        return _TOKEN_VAL["access_token"]
    except requests.RequestException:
        return None

def _api_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    token = _get_token()
    if not token: return None
    try:
        r = requests.get(
            f"{SPOTIFY_API_BASE_URL}{endpoint}",
            params=params, headers={"Authorization": f"Bearer {token}"}, timeout=20
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None

def _ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()

def enrich_from_spotify(artist_hint: str | None, title_hint: str | None, album_hint: str | None, duration_sec: float | None) -> Dict[str, Any]:
    query = f"{artist_hint or ''} {title_hint or ''}".strip()
    if not query:
        return {"accepted": False, "reason": "no_query"}

    search_result = _api_get("/v1/search", {"q": query, "type": "track", "limit": 5, "market": SPOTIFY_MARKET})
    items = (search_result or {}).get("tracks", {}).get("items", [])
    if not items:
        return {"accepted": False, "reason": "no_results"}

    best_match, best_score = None, -1.0
    for item in items:
        score = _ratio(item.get("name"), title_hint)
        if duration_sec:
            delta = abs(item.get("duration_ms", 0) / 1000.0 - duration_sec)
            if delta > 7.0: continue
        if score > best_score:
            best_match, best_score = item, score

    if not best_match or best_score < 0.6:
        return {"accepted": False, "reason": "no_match"}

    track_id = best_match.get("id")
    artist_id = (best_match.get("artists", [{}])[0]).get("id")

    features_data = _api_get(f"/v1/audio-features/{track_id}") if track_id else None
    artist_data = _api_get(f"/v1/artists/{artist_id}") if artist_id else None
    
    album_data = best_match.get("album", {})
    release_date = album_data.get("release_date", "")
    year = int(release_date.split('-')[0]) if release_date and release_date[0].isdigit() else None
    
    mode_val = (features_data or {}).get("mode")
    mode = "major" if mode_val == 1 else "minor" if mode_val == 0 else None

    return {
        "accepted": True,
        "title": best_match.get("name"),
        "artist": ", ".join(a.get("name", "") for a in best_match.get("artists", [])),
        "album": album_data.get("name"),
        "cover": (album_data.get("images", [{}])[0]).get("url") if album_data.get("images") else None,
        "genres": (artist_data or {}).get("genres", []),
        "link_spotify": best_match.get("external_urls", {}).get("spotify"),
        "bpm": (features_data or {}).get("tempo"),
        "year": year,
        "mode": mode,
    }