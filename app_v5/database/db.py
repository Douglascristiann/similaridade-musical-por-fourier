# -*- coding: utf-8 -*-
from __future__ import annotations
import mysql.connector
from typing import List, Tuple, Optional, Dict, Any
import numpy as np

from app_v5.config import DB_CONFIG, DB_TABLE_NAME

def conectar():
    return mysql.connector.connect(**DB_CONFIG)

def criar_tabela():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_NAME} (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(255) NOT NULL,
                    caracteristicas LONGTEXT NOT NULL,
                    artista VARCHAR(255),
                    titulo VARCHAR(255),
                    album VARCHAR(255),
                    genero VARCHAR(255),
                    capa_album TEXT,
                    link_youtube TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
        conn.commit()

def _select_id_by_nome(nome: str) -> Optional[int]:
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM {DB_TABLE_NAME} WHERE nome=%s LIMIT 1", (nome,))
            r = cur.fetchone()
            return int(r[0]) if r else None

def upsert_musica(
    nome: str,
    caracteristicas: np.ndarray,
    artista: Optional[str],
    titulo: Optional[str],
    album: Optional[str],
    genero: Optional[str],
    capa_album: Optional[str],
    link_youtube: Optional[str],
) -> int:
    """
    Insere se não existir; caso exista, ATUALIZA todos os campos (inclui link_youtube).
    """
    vec_str = ",".join(str(float(x)) for x in caracteristicas.tolist())
    with conectar() as conn:
        with conn.cursor() as cur:
            rid = _select_id_by_nome(nome)
            if rid is None:
                cur.execute(f"""
                    INSERT INTO {DB_TABLE_NAME}
                    (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (nome, vec_str, artista, titulo, album, genero, capa_album, link_youtube))
                conn.commit()
                rid = cur.lastrowid
            else:
                cur.execute(f"""
                    UPDATE {DB_TABLE_NAME}
                       SET caracteristicas=%s,
                           artista=%s, titulo=%s, album=%s, genero=%s,
                           capa_album=%s, link_youtube=%s
                     WHERE id=%s
                """, (vec_str, artista, titulo, album, genero, capa_album, link_youtube, rid))
                conn.commit()
            return int(rid)

def listar(limit: int = 20) -> List[Dict[str, Any]]:
    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(f"""
                SELECT id, titulo, artista,
                       COALESCE(link_youtube, '') AS caminho,
                       created_at
                  FROM {DB_TABLE_NAME}
              ORDER BY id DESC
                 LIMIT %s
            """, (int(limit),))
            return [dict(r) for r in cur.fetchall()]

def carregar_matriz() -> Tuple[np.ndarray, List[int], List[Dict[str, Any]]]:
    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(f"""
                SELECT id, nome, caracteristicas, titulo, artista, link_youtube
                  FROM {DB_TABLE_NAME}
                 WHERE caracteristicas IS NOT NULL AND caracteristicas <> ''
            """)
            rows = cur.fetchall()

    ids, metas, feats = [], [], []
    for r in rows:
        try:
            vec = [float(x) for x in (r["caracteristicas"].split(","))]
            feats.append(vec)
            ids.append(int(r["id"]))
            metas.append({
                "nome": r["nome"],
                "titulo": r.get("titulo"),
                "artista": r.get("artista"),
                "caminho": r.get("link_youtube"),
            })
        except Exception:
            continue

    if not feats:
        import numpy as np
        return np.zeros((0, 1)), [], []
    X = np.asarray(feats, dtype=float)
    return X, ids, metas
