from __future__ import annotations
from typing import Dict, Any, Tuple, List, Optional, Set
import re, unicodedata

_CANON = {
    "pop": {"pop", "pop internacional"},
    "rock": {"rock", "hard rock", "classic rock", "indie rock", "alternativo"},
    "eletronica": {"eletrônica", "eletronica", "edm", "dance", "house", "deep house", "electro", "techno", "trance", "drum and bass", "dnb", "dubstep"},
    "hiphop": {"hip hop", "hip-hop", "rap", "trap"},
    "rnb": {"r&b", "rnb", "soul"},
    "sertanejo": {"sertanejo", "universitario", "modao"},
    "pagode": {"pagode", "samba"},
    "forro": {"forró", "forro", "piseiro"},
    "funkbr": {"funk", "funk carioca", "funk br", "funk brasileiro"},
    "mpb": {"mpb", "bossa nova"},
    "reggaeton": {"reggaeton", "latin urban"},
    "kpop": {"k-pop", "kpop"},
    "metal": {"metal", "heavy metal", "death metal", "power metal"},
    "jazz": {"jazz", "smooth jazz", "bebop"},
    "classica": {"clássica", "classica", "orquestral", "barroca"},
}
_ALIASES = {"eletrônica":"eletronica","clássica":"classica","r&b":"rnb","hip-hop":"hip hop","funk carioca":"funkbr","funk br":"funkbr","funk brasileiro":"funkbr"}

def _n(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()

def _split(raw: Optional[str]) -> List[str]:
    if not raw: return []
    return [p.strip() for p in re.split(r"[,/;|]", raw) if p.strip()]

def _is_unknown(raw: Optional[str]) -> bool:
    s = _n(raw or "")
    return s in {"", "desconhecido", "nao encontrado", "não encontrado"}

def _canon_set(raw: Optional[str]) -> Optional[Set[str]]:
    if _is_unknown(raw): return None
    out: Set[str] = set()
    for token in _split(raw):
        t = _ALIASES.get(_n(token), _n(token))
        matched = False
        for c, bucket in _CANON.items():
            if t in bucket or t == c:
                out.add(c); matched = True; break
        if not matched and t:
            out.add(t)
    return out or None

def _overlap(a: Set[str], b: Set[str]) -> float:
    inter, uni = a & b, a | b
    return len(inter) / max(1, len(uni))

_WEIGHTS = {
    0: {"mismatch": 0.10, "unk_c": 0.00, "unk_q": 0.00},
    1: {"mismatch": 0.15, "unk_c": 0.05, "unk_q": 0.00},
    2: {"mismatch": 0.22, "unk_c": 0.10, "unk_q": 0.06},
    3: {"mismatch": 0.30, "unk_c": 0.15, "unk_q": 0.10},
}

class GenrePenalty:
    def __init__(self, strict_level: int = 1) -> None:
        self.W = _WEIGHTS.get(int(strict_level), _WEIGHTS[1])

    def compute(self, query_meta: Dict[str, Any], cand: Dict[str, Any], context: Dict[str, Any]) -> Tuple[float, List[str]]:
        reasons: List[str] = []
        gq, gc = _canon_set(query_meta.get("genres")), _canon_set(cand.get("genres"))
        if not gq and not gc:
            pen = (self.W["unk_c"] + self.W["unk_q"]) * 0.5
            if pen > 0: reasons.append("Query e candidato sem gênero")
            return pen, reasons
        if gq and not gc:
            reasons.append("Candidato sem gênero")
            return self.W["unk_c"], reasons
        if not gq and gc:
            reasons.append("Query sem gênero")
            return self.W["unk_q"], reasons
        ov = _overlap(gq, gc)
        if ov <= 0.0:
            reasons.append("Gêneros incompatíveis")
            return self.W["mismatch"], reasons
        if ov < 1.0:
            reasons.append(f"Overlap parcial de gênero ({ov:.2f})")
            return self.W["mismatch"] * (1.0 - ov), reasons
        reasons.append("Gênero compatível")
        return 0.0, reasons
