from __future__ import annotations
from typing import Protocol, Dict, Any, List, Tuple

class Penalty(Protocol):
    def compute(self, query_meta: Dict[str, Any], cand: Dict[str, Any], context: Dict[str, Any]) -> Tuple[float, List[str]]: ...

class PenaltyEngine:
    def __init__(self, penalties: List[Penalty], shadow_mode: bool = False) -> None:
        self.penalties = penalties
        self.shadow_mode = shadow_mode

    def total_penalty(self, query_meta: Dict[str, Any], cand: Dict[str, Any], context: Dict[str, Any]) -> Tuple[float, List[str], float]:
        total = 0.0
        reasons: List[str] = []
        for p in self.penalties:
            pen, why = p.compute(query_meta, cand, context)
            total += pen
            reasons.extend(why)
        # pen (aplicada), reasons, pen_raw (para logs/“shadow mode”)
        return (0.0 if self.shadow_mode else total), reasons, total
