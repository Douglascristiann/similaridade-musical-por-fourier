from __future__ import annotations
from typing import Dict, Any, Optional
import logging
log = logging.getLogger("FourierMatch")

class QueryMetadataProvider:
    """
    Espera um adaptador 'db' com:
      - by_id(id_musica) -> dict|obj (.genres)
      - by_artist_title(artist, title) -> idem
      - by_path(path) -> idem
    """
    def __init__(self, db) -> None:
        self.db = db

    def get(self, query: Dict[str, Any]) -> Dict[str, Optional[str]]:
        g = (query.get("genres") or "").strip()
        if g:
            return {"genres": g}
        try:
            row = None
            if query.get("id_musica"):
                row = self.db.by_id(query["id_musica"])
            if not row and query.get("artist") and query.get("title"):
                row = self.db.by_artist_title(query["artist"], query["title"])
            if not row and query.get("path"):
                row = self.db.by_path(query["path"])
            if row:
                return {"genres": (row.get("genres") if isinstance(row, dict) else getattr(row, "genres", None))}
        except Exception as e:
            log.warning(f"Lookup de metadados da query falhou: {e}")
        log.warning("Função 'get_query_metadata' não está disponível para busca em tempo real.")
        return {"genres": None}
