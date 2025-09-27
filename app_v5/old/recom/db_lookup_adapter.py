# app_v5/recom/db_lookup_adapter.py
from __future__ import annotations
from typing import Optional, Dict, Any
from app_v5.database import db  # <- ajuste se o caminho/nome for outro

class DBLookup:
    """Adaptador fino do banco para o recomendador/penalidades."""
    def __init__(self, conn=None) -> None:
        # se o seu db.py precisa de conexão explícita, guarde aqui
        self.conn = conn

    def by_id(self, id_musica: int) -> Optional[Dict[str, Any]]:
        # tente casar com a sua função real, por exemplo:
        # row = db.get_musica_by_id(id_musica, conn=self.conn)
        row = db.get_musica_by_id(id_musica)  # ajuste o nome/assinatura
        return self._to_dict(row)

    def by_artist_title(self, artist: str, title: str) -> Optional[Dict[str, Any]]:
        # row = db.get_musica_by_artist_title(artist, title, conn=self.conn)
        row = db.get_musica_by_artist_title(artist, title)
        return self._to_dict(row)

    def by_path(self, path: str) -> Optional[Dict[str, Any]]:
        # row = db.get_musica_by_path(path, conn=self.conn)
        row = db.get_musica_by_path(path)
        return self._to_dict(row)

    @staticmethod
    def _to_dict(row) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        if isinstance(row, dict):
            return row
        # Se vier um objeto (ORM), mapeie os campos que o KNN usa:
        return {
            "id_musica": getattr(row, "id_musica", None),
            "title":     getattr(row, "title", None),
            "artist":    getattr(row, "artist", None),
            "genres":    getattr(row, "genres", None),
            "album":     getattr(row, "album", None),
            "cover":     getattr(row, "cover", None),
            # acrescente o que fizer sentido no seu app
        }
