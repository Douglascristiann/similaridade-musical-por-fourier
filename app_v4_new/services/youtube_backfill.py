# -*- coding: utf-8 -*-
from __future__ import annotations
import json, re, time, random, unicodedata
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional

from app_v4_new.config import YT_BACKFILL_LIMIT, YT_BACKFILL_RETRIES, YT_BACKFILL_THROTTLE_S

_CACHE_PATH = Path(__file__).resolve().parents[1] / "cache" / "yt_search_cache.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

_last_call_ts: float = 0.0

def _cache_load() -> dict:
    try: return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception: return {}

def _cache_save(d: dict) -> None:
    try: _CACHE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass

def _cache_key(artist: str|None, title: str|None, duration_sec: float|None) -> str:
    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", s)
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s
    d = int(round(duration_sec or 0))
    return f"{norm(artist or '')}|{norm(title or '')}|{d}"

def _throttle():
    global _last_call_ts
    now = time.time()
    wait = max(0.0, (_last_call_ts + float(YT_BACKFILL_THROTTLE_S)) - now)
    if wait > 0: time.sleep(wait)
    _last_call_ts = time.time()

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()

def _strip_brackets(s: str) -> str:
    return re.sub(r"[\(\[\{].*?[\)\]\}]", " ", s or "")

def _sanitize(s: str) -> str:
    s = _strip_brackets(s)
    s = re.sub(r"(?i)\b(remaster(ed)?|ao vivo|live|official|oficial|audio|áudio|video|vídeo|lyric|karaoke|remix|vers[aã]o|legendado|subtitle|hd|hq)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _duration_score_secs(cand_sec: float|None, hint_sec: float|None) -> float:
    if not cand_sec or not hint_sec or cand_sec <= 0 or hint_sec <= 0: return 0.0
    import math
    delta = abs(cand_sec - hint_sec)
    sigma = max(2.0, 0.06 * max(cand_sec, hint_sec))
    return math.exp(- (delta / sigma) ** 2)

def _clean_link(url: str) -> str:
    try:
        from urllib.parse import urlparse, parse_qs
        pu = urlparse(url)
        if "youtube.com" in pu.netloc and pu.path == "/watch":
            q = parse_qs(pu.query)
            v = q.get("v", [None])[0]
            if v:
                return f"https://www.youtube.com/watch?v={v}"
        return url
    except Exception:
        return url

def find_youtube_link(artist_hint: str|None, title_hint: str|None, album_hint: str|None,
                      duration_sec: float|None) -> Optional[str]:
    """
    Retorna link canônico do YouTube (https://www.youtube.com/watch?v=…)
    ou None se não encontrar com confiança. **Nunca** retorna caminho local.
    """
    if not (artist_hint or title_hint):
        return None

    cache = _cache_load()
    ckey  = _cache_key(artist_hint, title_hint, duration_sec)
    if ckey in cache:
        return cache.get(ckey) or None

    q_title  = _sanitize(title_hint or "")
    q_artist = _sanitize(artist_hint or "")
    q = f'{q_artist} {q_title} "audio"'.strip()

    base_opts = {
        "quiet": True,
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": "discard_in_playlist",
        "default_search": "ytsearch",
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    clients_seq = ["android", "web"]

    best, best_s = None, -1.0
    import yt_dlp  # type: ignore

    backoff = 1.5
    for attempt in range(int(YT_BACKFILL_RETRIES) + 1):
        _throttle()
        ydl_opts = dict(base_opts)
        ydl_opts["extractor_args"] = {"youtube": {"player_client": [clients_seq[min(attempt, 1)]}}}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{int(YT_BACKFILL_LIMIT)}:{q}", download=False)
                for e in (info or {}).get("entries", []) or []:
                    vid = e.get("id")
                    if not vid: continue
                    title_cand = e.get("title") or ""
                    uploader   = e.get("uploader") or e.get("channel") or ""
                    link       = e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
                    cand_dur   = float(e.get("duration")) if e.get("duration") else None

                    title_score  = max(_ratio(title_cand, q_title), _ratio(title_cand, title_hint or q_title))
                    artist_score = max(_ratio(uploader, q_artist),  _ratio(uploader, artist_hint or q_artist))
                    dur_score    = _duration_score_secs(cand_dur, duration_sec)

                    score = 0.55*title_score + 0.30*artist_score + 0.15*dur_score
                    if title_score >= 0.62 and (artist_score >= 0.55 or dur_score >= 0.40):
                        if score > best_s:
                            best_s, best = score, _clean_link(link)
                    if score >= 0.87:
                        best = _clean_link(link); break
        except Exception as e:
            s = str(e).lower()
            if "429" in s or "too many requests" in s:
                time.sleep(backoff); backoff *= 1.8; continue
            if "not available on this app" in s and attempt < int(YT_BACKFILL_RETRIES):
                continue
            best = None
        if best: break

    cache[ckey] = best or ""
    _cache_save(cache)
    return best
