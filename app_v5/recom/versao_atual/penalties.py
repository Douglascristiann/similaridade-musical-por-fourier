# app_v5/recom/penalties.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, Iterable, List, Tuple, Set, Optional
import unicodedata, re

def _norm_token(s: str) -> str:
    if s is None: return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

_SPLIT_RE = re.compile(r"\s*[,/&;|]\s*")

# ===== CORREÇÃO APLICADA AQUI: MAIS ESPECIFICIDADE DE GÊNEROS =====
# O dicionário _CANON foi expandido para tratar subgêneros latinos e outros
# como categorias únicas, em vez de agrupá-los genericamente.
_CANON = {
    # Funk
    "funk carioca": "funk brasileiro",
    "baile funk": "funk brasileiro",
    
    # Sertanejo
    "sertanejo universitário": "sertanejo",
    "arrocha": "sertanejo",
    
    # Rock (agrupado)
    "hard rock": "rock",
    "classic rock": "rock",
    "pop rock": "rock",
    "prog rock": "rock",
    "alternative rock": "rock",
    "indie rock": "rock",
    "soft rock": "rock",
    
    # Metal (separado de Rock)
    "heavy metal": "metal",
    "thrash metal": "metal",
    "death metal": "metal",

    # Pop (agrupado)
    "dance pop": "pop",
    "electropop": "pop",
    
    # --- GÊNEROS LATINOS ESPECÍFICOS ---
    # Agora, cada subgênero será tratado como uma categoria distinta.
    #"latin pop": "latin pop",
    "reggaeton": "reggaeton",
    "salsa": "salsa",
    "bachata": "bachata",
    "cumbia": "cumbia",
    "merengue": "merengue",
    "tango": "tango",
    "ranchera": "ranchera",
    "mariachi": "mariachi",

    # --- GÊNEROS BRASILEIROS ESPECÍFICOS ---
    "bossa nova": "bossa nova",
    "mpb": "mpb",
    "pagode": "pagode",
    "samba": "samba",
    "forro": "forro",
    "axe": "axe",
    "piseiro": "piseiro",
    "brazilian pop": "pop nacional",
}
# =================================================================

def _canon(s: str) -> str:
    """Aplica a canonização para agrupar subgêneros."""
    return _CANON.get(s, s)

def _to_genre_set(value: Any) -> Set[str]:
    """
    Converte uma string ou lista de gêneros em um conjunto de tokens de gênero
    normalizados e canonizados.
    """
    if value is None:
        return set()
    
    toks: List[str] = []
    if isinstance(value, (list, tuple, set)):
        for v in value:
            if v is None: continue
            toks.extend(_SPLIT_RE.split(str(v)))
    else:
        # Tenta decodificar JSON se for uma string, útil para dados do banco
        try:
            import json
            parsed_value = json.loads(str(value))
            if isinstance(parsed_value, list):
                 for v in parsed_value:
                    toks.extend(_SPLIT_RE.split(str(v)))
            else:
                toks.extend(_SPLIT_RE.split(str(value)))
        except (json.JSONDecodeError, TypeError):
             toks.extend(_SPLIT_RE.split(str(value)))

    out = set()
    for t in toks:
        tt = _norm_token(t)
        if not tt or tt in {"desconhecido", "nao encontrado", "não encontrado", "other"}:
            continue
        out.add(_canon(tt))
    return out

def _get_genres_from_meta(meta: Dict[str, Any]) -> Set[str]:
    for k in ("genre", "genres", "genero"):
        if k in meta and meta[k] is not None:
            return _to_genre_set(meta[k])
    return set()

class BasePenalty:
    name: str = "base"
    def score(self, query_meta: Dict[str, Any], cand_meta: Dict[str, Any]) -> Tuple[float, Optional[str]]:
        return 0.0, None

class PenaltyEngine:
    def __init__(self, penalties: List[BasePenalty], shadow_mode: bool = False):
        self.penalties = penalties or []
        self.shadow_mode = shadow_mode

    def apply(self, query_meta: Dict[str, Any], cand_meta: Dict[str, Any]) -> Tuple[float, List[str]]:
        total = 0.0
        reasons: List[str] = []
        for p in self.penalties:
            pen, why = p.score(query_meta, cand_meta)
            if not self.shadow_mode:
                total += max(0.0, float(pen or 0.0))
            if why:
                reasons.append(why)
        return total, reasons

class GenrePenalty(BasePenalty):
    name = "genre"
    def __init__(self, strict_level: int = 2, weight: float = 1.0):
        self.strict_level = int(strict_level)
        self.weight = float(weight)

    def score(self, query_meta: Dict[str, Any], cand_meta: Dict[str, Any]) -> Tuple[float, Optional[str]]:
        if self.strict_level <= 0:
            return 0.0, None

        q_set = _get_genres_from_meta(query_meta)
        c_set = _get_genres_from_meta(cand_meta)

        if not q_set or not c_set:
            return 0.0, None

        inter = q_set & c_set
        
        if self.strict_level >= 3 and not inter:
            return 1e9, f"sem interseção de gênero (q={sorted(q_set)}; c={sorted(c_set)})"

        if self.strict_level == 1 and not inter:
            return self.weight, f"sem interseção de gênero (q={sorted(q_set)}; c={sorted(c_set)})"

        if self.strict_level >= 2:
            union = q_set | c_set
            jaccard = (len(inter) / len(union)) if union else 0.0
            dist = 1.0 - jaccard
            pen = dist * self.weight
            
            # Formata a razão da penalidade para ser mais legível no debug
            reason = None
            if dist > 0.01: # Apenas mostra a razão se a penalidade for significativa
                q_str = ', '.join(sorted(q_set))
                c_str = ', '.join(sorted(c_set))
                reason = f"distância Jaccard gênero={dist:.3f} (q=[{q_str}]; c=[{c_str}])"

            return pen, reason

        return 0.0, None