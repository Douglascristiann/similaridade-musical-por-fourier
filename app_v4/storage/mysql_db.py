
from __future__ import annotations
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import mysql.connector
import numpy as np
import logging

from ..integrations.external_config_bridge import load_external_config

log = logging.getLogger("FourierMatch")

_CFG = load_external_config()
DB_CONFIG = _CFG["DB_CONFIG"]
DB_TABLE_NAME = _CFG["DB_TABLE_NAME"]
EXPECTED_FEATURE_LENGTH = int(_CFG["EXPECTED_FEATURE_LENGTH"] or 0)

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".aiff", ".aif"}

def conectar():
    return mysql.connector.connect(**DB_CONFIG)

def ensure_schema() -> None:
    log.info(f"[DB] Verificando/criando tabela {DB_TABLE_NAME} (MySQL)…")
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_NAME} (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nome VARCHAR(255) NOT NULL,
                    caracteristicas TEXT NOT NULL,
                    artista VARCHAR(255),
                    titulo VARCHAR(255),
                    album VARCHAR(255),
                    genero VARCHAR(255),
                    capa_album TEXT,
                    link_youtube TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_nome (nome)
                );
            """)
        conn.commit()
    log.info(f"[DB] Tabela '{DB_TABLE_NAME}' pronta.")

def _vec_to_str(vec: np.ndarray) -> str:
    v = np.asarray(vec).ravel().astype(float)
    return ",".join(f"{x:.9g}" for x in v)

def _pad_or_trim(vec: np.ndarray, expected: int) -> np.ndarray:
    if expected <= 0:
        return vec
    v = np.asarray(vec).ravel()
    if v.size == expected:
        return v
    if v.size > expected:
        return v[:expected]
    # pad com zeros se faltar
    out = np.zeros(expected, dtype=v.dtype)
    out[:v.size] = v
    return out

def musica_existe(nome: str) -> bool:
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {DB_TABLE_NAME} WHERE nome = %s", (nome,))
            return cur.fetchone() is not None

def insert_track(nome: str, vec: np.ndarray, artista: Optional[str], titulo: Optional[str],
                 album: Optional[str] = None, genero: Optional[str] = None, capa_album: Optional[str] = None,
                 link_youtube: Optional[str] = None, upsert: bool = True) -> int:
    ensure_schema()
    v = _pad_or_trim(vec, EXPECTED_FEATURE_LENGTH)
    carac_str = _vec_to_str(v)

    with conectar() as conn:
        with conn.cursor() as cur:
            if musica_existe(nome):
                if not upsert:
                    return -1
                cur.execute(
                    f"""UPDATE {DB_TABLE_NAME}
                        SET caracteristicas=%s, artista=%s, titulo=%s, album=%s, genero=%s, capa_album=%s, link_youtube=%s
                        WHERE nome=%s
                    """,
                    (carac_str, artista, titulo, album, genero, capa_album, link_youtube, nome)
                )
                conn.commit()
                cur.execute(f"SELECT id FROM {DB_TABLE_NAME} WHERE nome=%s", (nome,))
                rid = cur.fetchone()[0]
                return int(rid)
            else:
                cur.execute(
                    f"""INSERT INTO {DB_TABLE_NAME}
                        (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (nome, carac_str, artista, titulo, album, genero, capa_album, link_youtube)
                )
                conn.commit()
                return int(cur.lastrowid)

def load_feature_matrix() -> tuple[np.ndarray, List[int], List[Dict[str, str]]]:
    ensure_schema()
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id, nome, artista, titulo, link_youtube, caracteristicas FROM {DB_TABLE_NAME}")
            rows = cur.fetchall()
    if not rows:
        raise RuntimeError("Banco vazio (MySQL). Ingestione algumas músicas primeiro.")
    X, ids, metas = [], [], []
    for rid, nome, artista, titulo, link, carac in rows:
        vec = np.fromstring(carac, sep=',', dtype=float)
        vec = _pad_or_trim(vec, EXPECTED_FEATURE_LENGTH)
        X.append(vec.astype(np.float32))
        ids.append(int(rid))
        metas.append({
            "id": int(rid),
            "titulo": titulo or nome,
            "artista": artista or "",
            "caminho": link or nome,
            "nome": nome,
        })
    return np.vstack(X), ids, metas

def list_tracks(limit: int = 20) -> List[Dict[str, str]]:
    ensure_schema()
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, titulo, artista, nome, link_youtube, criado_em
                FROM {DB_TABLE_NAME} ORDER BY id DESC LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
    out = []
    for rid, titulo, artista, nome, link, dt in rows:
        out.append({
            "id": int(rid),
            "titulo": titulo or nome,
            "artista": artista or "",
            "caminho": link or nome,
            "created_at": str(dt),
        })
    return out
