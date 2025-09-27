# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple, Callable
import logging
import numpy as np

try:
    # sklearn é comum aqui; se você usa FAISS/annoy, adapte o bloco NearestNeighbors
    from sklearn.neighbors import NearestNeighbors
except Exception:  # pragma: no cover
    NearestNeighbors = None  # deixa explícito para ambientes sem sklearn

from app_v5.recom.penalty_engine import PenaltyEngine
from app_v5.recom.penalty_genre import GenrePenalty
from app_v5.recom.query_provider import QueryMetadataProvider

log = logging.getLogger("FourierMatch")


# ----------------------------
# Tipos/adaptadores de banco
# ----------------------------
class DBLookup:
    """
    Adaptador fino sobre seu database. Implemente as três funções usando seu db.py atual.
    Pode ser um wrapper por cima de funções existentes.
    """
    def by_id(self, id_musica: int) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def by_artist_title(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def by_path(self, path: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

def _as_bool(s: str, default: bool=False) -> bool:
    if s is None: return default
    return s.strip().lower() in {"1","true","yes","y","on"}

_GENRE_PENALTY_ENABLED      = _as_bool(os.getenv("GENRE_PENALTY_ENABLED"), True)
_GENRE_PENALTY_STRICT_LEVEL = int(os.getenv("GENRE_PENALTY_STRICT_LEVEL", "1"))
_PENALTY_SHADOW_MODE        = _as_bool(os.getenv("PENALTY_SHADOW_MODE"), True)

def build_penalty_engine() -> PenaltyEngine:
    penalties = []
    if _GENRE_PENALTY_ENABLED:
        penalties.append(GenrePenalty(strict_level=_GENRE_PENALTY_STRICT_LEVEL))
    return PenaltyEngine(penalties, shadow_mode=_PENALTY_SHADOW_MODE)


# ----------------------------
# Engine de penalidades (factory)
# ----------------------------
def build_penalty_engine() -> PenaltyEngine:
    penalties = []
    if GENRE_PENALTY_ENABLED:
        penalties.append(GenrePenalty(strict_level=GENRE_PENALTY_STRICT_LEVEL))
    return PenaltyEngine(penalties, shadow_mode=PENALTY_SHADOW_MODE)


# ----------------------------
# Recomendador via KNN
# ----------------------------
class KNNRecommender:
    """
    Recomendador KNN com pipeline de score base + penalidades.
    - Desacoplado do banco: injete DBLookup e QueryMetadataProvider.
    - Desacoplado das penalidades: injete o PenaltyEngine.
    - Não assume fórmula de 'base': coloque a sua exata em _base_score().
    """

    def __init__(
        self,
        feature_matrix: np.ndarray,
        item_ids: np.ndarray,
        get_vector_for_query: Callable[[Dict[str, Any]], np.ndarray],
        db_lookup: DBLookup,
        penalty_engine: PenaltyEngine | None = None,
        n_neighbors: int = 50,
        metric: str = "euclidean",  # ajuste se usa "cosine" etc.
        algorithm: str = "auto",
    ) -> None:
        """
        feature_matrix: matriz [N, D] de vetores das músicas.
        item_ids: vetor [N] com IDs das músicas (chave que o DB conhece).
        get_vector_for_query: função que converte a query (dict) → vetor [1, D].
        db_lookup: adaptador de banco (by_id / by_artist_title / by_path).
        penalty_engine: agregador de penalidades (GenrePenalty, etc.).
        """
        assert feature_matrix.shape[0] == item_ids.shape[0], "X e ids devem ter mesmo N"
        self.X = feature_matrix
        self.ids = item_ids
        self.get_vec = get_vector_for_query
        self.db = db_lookup
        self.engine = penalty_engine or build_penalty_engine()
        self.n_neighbors = int(n_neighbors)

        if NearestNeighbors is None:
            raise RuntimeError("scikit-learn não disponível; instale para usar KNN padrão.")

        self.nn = NearestNeighbors(
            n_neighbors=self.n_neighbors,
            metric=metric,
            algorithm=algorithm,
        ).fit(self.X)

        self.qmeta_provider = QueryMetadataProvider(self.db)

    # --------- pontos de extensão (mantenha sua base) ---------
    @staticmethod
    def _base_score(dist_value: float) -> float:
        """
        Transformação padrão de distância → score base.
        Se você já tem uma fórmula de produção, substitua só esta linha.
        """
        # Exemplo ilustrativo (substitua pela sua): base = 1/(1+dist)
        return 1.0 / (1.0 + float(dist_value))

    def _fetch_metadata(self, id_musica: int) -> Dict[str, Any]:
        """
        Busca metadados essenciais do candidato (artist, title, genres...).
        Suporta retorno dict ou objeto com atributos.
        """
        row = self.db.by_id(int(id_musica))
        if not row:
            return {"id_musica": int(id_musica)}
        if isinstance(row, dict):
            row.setdefault("id_musica", int(id_musica))
            return row
        # objeto (ex.: ORM): extrai atributos usados
        return {
            "id_musica": int(id_musica),
            "artist": getattr(row, "artist", None),
            "title": getattr(row, "title", None),
            "genres": getattr(row, "genres", None),
            "album": getattr(row, "album", None),
            "cover": getattr(row, "cover", None),
        }

    # ----------------------------------------------------------
    # API principal
    # ----------------------------------------------------------
    def recommend(
        self,
        query: Dict[str, Any],
        topn: int = 10,
        strict_level: Optional[int] = None,
        debug: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        query: dict com pelo menos uma das chaves para o provider (id_musica/artist+title/path)
        topn: número de itens finais
        strict_level: se quiser sobrepor o nível do config só para esta consulta
        """
        qvec = self.get_vec(query).reshape(1, -1)
        dists, idxs = self.nn.kneighbors(qvec, n_neighbors=self.n_neighbors, return_distance=True)

        # prepara metadados da query (elimina WARNING de função ausente)
        qmeta = self.qmeta_provider.get(query)

        # se quiser sobrepor 'strict_level' só agora, reconstroi o engine no contexto
        engine = self.engine
        if strict_level is not None:
            engine = PenaltyEngine([GenrePenalty(strict_level=int(strict_level))], shadow_mode=PENALTY_SHADOW_MODE)

        results: List[Dict[str, Any]] = []
        for rank, (dist_value, idx) in enumerate(zip(dists[0], idxs[0]), start=1):
            song_id = int(self.ids[idx])
            cand = self._fetch_metadata(song_id)

            base = self._base_score(float(dist_value))
            # contexto opcional para penalidades (se no futuro quiser passar bpm/ano, etc.)
            context: Dict[str, Any] = {}

            pen, reasons, pen_raw = engine.total_penalty(qmeta, cand, context)
            final = max(0.0, base - pen)

            item = {
                "rank": rank,
                "id_musica": song_id,
                "title": cand.get("title"),
                "artist": cand.get("artist"),
                "genres": cand.get("genres"),
                "album": cand.get("album"),
                "cover": cand.get("cover"),
                "dist": float(dist_value),
                "base": float(base),
                "pen": float(pen),
                "final": float(final),
                "reasons": reasons,
            }

            if debug:
                # espelha o formato das suas mensagens de debug
                qg = qmeta.get("genres", "desconhecido")
                cg = cand.get("genres", "desconhecido")
                log_line = (
                    f"#{rank:<2} | {item.get('title','?')} — {item.get('artist','?')}\n"
                    f"   ├─ Score: dist={item['dist']:.3f} | base={item['base']:.3f} | pen={item['pen']:.3f} | final={item['final']:.3f}\n"
                    f"   ├─ Gênero (Query -> Candidato): '{qg or 'desconhecido'}' -> '{cg or 'desconhecido'}'\n"
                    f"   └─ Razões da Penalidade: {', '.join(reasons) if reasons else 'Nenhuma penalidade'}\n"
                    "------------------------------------------------------------------------"
                )
                print(log_line)

            results.append(item)

        # ordena por 'final' (maior para menor) e trunca topn
        results.sort(key=lambda r: r["final"], reverse=True)
        return results[: int(topn)]
