# app_v4_new/integrations/spotify.py
from __future__ import annotations
import os, time, base64, math
from typing import Dict, Any, Optional, List, Tuple
import requests
import re, unicodedata
from difflib import SequenceMatcher

# ===== Autenticação (Client Credentials) =====
_SPOTIFY_TOKEN_CACHE: Dict[str, Any] = {}
_SPOTIFY_DEFAULT_MARKET = os.getenv("SPOTIFY_MARKET", "BR")

def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")

def _get_token() -> str:
    now = time.time()
    if _SPOTIFY_TOKEN_CACHE.get("token") and _SPOTIFY_TOKEN_CACHE.get("exp", 0) - now > 60:
        return _SPOTIFY_TOKEN_CACHE["token"]
    cid = os.getenv("SPOTIFY_CLIENT_ID")
    csec = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not cid or not csec:
        raise RuntimeError("Defina SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET nas variáveis de ambiente.")
    headers = {"Authorization": "Basic " + _b64(f"{cid}:{csec}")}
    r = requests.post("https://accounts.spotify.com/api/token",
                      data={"grant_type": "client_credentials"},
                      headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    _SPOTIFY_TOKEN_CACHE["token"] = data["access_token"]
    _SPOTIFY_TOKEN_CACHE["exp"] = now + int(data.get("expires_in", 3600))
    return _SPOTIFY_TOKEN_CACHE["token"]

# ===== Normalização / Fuzzy =====
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
    if not a or not b: return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _artist_tokens(s: str) -> List[str]:
    s = _norm(s)
    s = re.sub(r"(?i)\b(feat\.?|com)\b", ",", s)
    return [t.strip() for t in re.split(r"[,&/x+]+", s) if t.strip()]

def _artist_match_ok(cand_names: List[str], hint: Optional[str]) -> Tuple[bool, float]:
    if not cand_names: return (False, 0.0)
    if not hint:       return (True, 1.0)
    toks = _artist_tokens(hint)
    best = 0.0
    for c in cand_names:
        for t in toks or [hint]:
            best = max(best, _ratio(c, t))
    return (best >= 0.70 or (best >= 0.90 and bool(toks))), best

def _album_score(cand_album: str, album_hint: Optional[str]) -> float:
    if not album_hint or not cand_album: return 0.0
    return _ratio(cand_album, album_hint)

def _title_score(cand_title: str, title_hint: Optional[str]) -> float:
    if not title_hint or not cand_title: return 0.0
    return _ratio(cand_title, title_hint)

def _duration_score(cand_ms: int, duration_hint_sec: Optional[float]) -> float:
    if not duration_hint_sec or duration_hint_sec <= 0 or not cand_ms:
        return 0.0
    dh = duration_hint_sec * 1000.0
    delta = abs(cand_ms - dh)
    sigma = max(2000.0, 0.06 * max(dh, cand_ms))  # 2s ou 6%
    return math.exp(- (delta / sigma) ** 2)

def _largest_image(images: List[Dict[str, Any]]) -> Optional[str]:
    if not images: return None
    try:
        img = sorted(images, key=lambda d: (d.get("width", 0), d.get("height", 0)))[-1]
        return img.get("url")
    except Exception:
        return images[0].get("url")

# ===== Chamadas REST =====
def _search(q: str, token: str, market: str, limit: int = 5) -> List[Dict[str, Any]]:
    r = requests.get("https://api.spotify.com/v1/search",
                     params={"q": q, "type": "track", "limit": limit, "market": market},
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if r.status_code != 200:
        return []
    data = r.json() or {}
    return (data.get("tracks") or {}).get("items") or []

def _get_track_details(track_id: str, token: str) -> Dict[str, Any]:
    r = requests.get(f"https://api.spotify.com/v1/tracks/{track_id}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if r.status_code != 200:
        return {}
    return r.json() or {}

def _get_artist_genres(artist_id: Optional[str], token: str) -> Optional[List[str]]:
    if not artist_id: return None
    r = requests.get(f"https://api.spotify.com/v1/artists/{artist_id}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if r.status_code != 200:
        return None
    data = r.json() or {}
    return data.get("genres")

def _get_audio_features(track_id: str, token: str) -> Dict[str, Any]:
    # Pode retornar 403 em algumas contas; tratar como opcional
    r = requests.get(f"https://api.spotify.com/v1/audio-features/{track_id}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if r.status_code != 200:
        return {}
    return r.json() or {}

# ===== Função principal =====
def enrich_from_spotify(artist_hint: Optional[str],
                        title_hint: Optional[str],
                        album_hint: Optional[str],
                        duration_sec: Optional[float],
                        market: str = _SPOTIFY_DEFAULT_MARKET) -> Dict[str, Any]:
    """
    Retorna:
      {
        accepted, reason, title, artist, album, cover, genres,
        spotify_id, isrc, duration_ms, popularity_sp,
        tempo_sp, key_sp, mode_sp, time_sig_sp
      }
    accepted=True só quando os limiares passam (artista ok e título >= 0.65).
    """
    token = _get_token()
    queries = []
    if artist_hint and title_hint:
        queries.append(f'artist:"{artist_hint}" track:"{title_hint}"')
        if album_hint:
            queries.append(f'artist:"{artist_hint}" track:"{title_hint}" album:"{album_hint}"')
    if artist_hint and title_hint:
        queries.append(f"{artist_hint} {title_hint}")
    elif title_hint:
        queries.append(title_hint)

    seen = set()
    cands: List[Dict[str, Any]] = []
    for q in queries:
        for it in _search(q, token, market):
            if it.get("id") in seen: continue
            seen.add(it.get("id"))
            cands.append(it)

    if not cands:
        return {"accepted": False, "reason": "no_results"}

    best = None
    best_score = -1.0
    for t in cands:
        cand_artists = [a.get("name","") for a in t.get("artists") or []]
        ok_artist, art_score = _artist_match_ok(cand_artists, artist_hint)
        tit_score = _title_score(t.get("name",""), title_hint)
        alb_score = _album_score((t.get("album") or {}).get("name",""), album_hint)
        dur_score = _duration_score(int(t.get("duration_ms") or 0), duration_sec)

        score = 0.45*art_score + 0.35*tit_score + 0.10*alb_score + 0.10*dur_score
        if not ok_artist or tit_score < 0.65:
            continue
        if score > best_score:
            best, best_score = t, score

    if not best:
        return {"accepted": False, "reason": "low_scores"}

    # detalhes adicionais
    album = best.get("album") or {}
    artists = [a.get("name","") for a in best.get("artists") or []]
    cover = _largest_image(album.get("images") or [])
    det = _get_track_details(best.get("id"), token) if best.get("id") else {}
    isrc = ((det.get("external_ids") or {}).get("isrc")) if det else None

    out = {
        "title": best.get("name"),
        "artist": ", ".join(artists) if artists else None,
        "album": album.get("name"),
        "cover": cover,
        "genres": None,  # gênero vem do artista
        "spotify_id": best.get("id"),
        "isrc": isrc,
        "duration_ms": best.get("duration_ms"),
        "popularity_sp": best.get("popularity"),
        "tempo_sp": None, "key_sp": None, "mode_sp": None, "time_sig_sp": None,
        "accepted": True, "reason": "spotify_match"
    }

    # gêneros do primeiro artista
    try:
        aid = (best.get("artists") or [{}])[0].get("id")
        gens = _get_artist_genres(aid, token)
        if gens: out["genres"] = gens
    except Exception:
        pass

    # audio features (opcional)
    try:
        feats = _get_audio_features(best.get("id"), token)
        if feats:
            out["tempo_sp"] = feats.get("tempo")
            out["key_sp"] = feats.get("key")
            out["mode_sp"] = feats.get("mode")
            out["time_sig_sp"] = feats.get("time_signature")
    except Exception:
        pass

    return out
