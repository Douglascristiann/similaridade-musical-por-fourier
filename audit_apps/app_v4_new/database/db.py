# -*- coding: utf-8 -*-
from __future__ import annotations

import mysql.connector
import numpy as np
from typing import List, Tuple, Optional, Dict, Any

from app_v4_new.config import DB_CONFIG, DB_TABLE_NAME, EXPECTED_FEATURE_LENGTH


def conectar():
    print(f"[DB] Conectando ao banco {DB_CONFIG.get('host')}:{DB_CONFIG.get('port')}/{DB_CONFIG.get('database')}…")
    return mysql.connector.connect(**DB_CONFIG)


def criar_tabela():
    print(f"[DB] Criando/verificando tabela {DB_TABLE_NAME}…")
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
    print(f"[DB] Tabela {DB_TABLE_NAME} pronta.")


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
    Insere se não existir; se já existir, atualiza todos os campos (inclusive link_youtube).
    """
    vec = caracteristicas.tolist() if isinstance(caracteristicas, np.ndarray) else caracteristicas
    vec_str = ",".join(str(float(x)) for x in vec)

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
    """
    Lê vetores da tabela e monta a matriz X (n_samples x n_features) + ids + metadados.
    Ignora linhas com vetor inválido ou de tamanho diferente de EXPECTED_FEATURE_LENGTH (se definido).
    """
    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(f"""
                SELECT id, nome, caracteristicas, titulo, artista, link_youtube
                  FROM {DB_TABLE_NAME}
                 WHERE caracteristicas IS NOT NULL AND caracteristicas <> ''
            """)
            rows = cur.fetchall()

    ids:   List[int]            = []
    metas: List[Dict[str, Any]] = []
    feats: List[List[float]]    = []

    for r in rows:
        try:
            raw = r["caracteristicas"]
            vec = [float(x) for x in str(raw).split(",") if x.strip() != ""]
            if EXPECTED_FEATURE_LENGTH and len(vec) != int(EXPECTED_FEATURE_LENGTH):
                continue  # pula vetores com tamanho inesperado
            feats.append(vec)
            ids.append(int(r["id"]))
            metas.append({
                "nome":   r.get("nome"),
                "titulo": r.get("titulo"),
                "artista": r.get("artista"),
                "caminho": r.get("link_youtube"),
            })
        except Exception:
            continue  # linha corrompida: ignora

    if not feats:
        n_cols = int(EXPECTED_FEATURE_LENGTH) if EXPECTED_FEATURE_LENGTH else 1
        return np.zeros((0, n_cols), dtype=float), [], []

    X = np.asarray(feats, dtype=float)
    return X, ids, metas
