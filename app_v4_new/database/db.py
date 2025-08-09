
from __future__ import annotations
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import mysql.connector
import numpy as np

# Importa seu config.py (na raiz do projeto)
from config import DB_CONFIG, EXPECTED_FEATURE_LENGTH  # tipo: ignore

# Nova tabela em português
DB_TABELA_NOVA = os.getenv("DB_TABELA_NOVA", "tb_musicas_fourier")

def conectar():
    print(f"[DB] Conectando ao banco {DB_CONFIG.get('host')}:{DB_CONFIG.get('port')}/{DB_CONFIG.get('database')}…")
    return mysql.connector.connect(**DB_CONFIG)

def criar_tabela():
    print(f"[DB] Criando/verificando tabela {DB_TABELA_NOVA}…")
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABELA_NOVA} (
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
    print(f"[DB] Tabela {DB_TABELA_NOVA} pronta.")

def _pad_or_trim(vec: np.ndarray, expected: int) -> np.ndarray:
    v = np.asarray(vec).ravel().astype(float)
    if expected and expected > 0:
        if v.size == expected:
            return v
        if v.size > expected:
            return v[:expected]
        out = np.zeros(expected, dtype=float)
        out[:v.size] = v
        return out
    return v

def musica_existe(nome: str) -> bool:
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {DB_TABELA_NOVA} WHERE nome = %s", (nome,))
            return cur.fetchone() is not None

def upsert_musica(nome: str, caracteristicas: np.ndarray, artista: Optional[str], titulo: Optional[str],
                  album: Optional[str] = None, genero: Optional[str] = None, capa_album: Optional[str] = None,
                  link_youtube: Optional[str] = None) -> int:
    v = _pad_or_trim(caracteristicas, int(EXPECTED_FEATURE_LENGTH or 0))
    carac_str = ",".join(f"{x:.9g}" for x in v)
    with conectar() as conn:
        with conn.cursor() as cur:
            if musica_existe(nome):
                cur.execute(
                    f"""UPDATE {DB_TABELA_NOVA}
                           SET caracteristicas=%s, artista=%s, titulo=%s, album=%s, genero=%s, capa_album=%s, link_youtube=%s
                         WHERE nome=%s""",
                    (carac_str, artista, titulo, album, genero, capa_album, link_youtube, nome)
                )
                conn.commit()
                cur.execute(f"SELECT id FROM {DB_TABELA_NOVA} WHERE nome=%s", (nome,))
                rid = cur.fetchone()[0]
                return int(rid)
            else:
                cur.execute(
                    f"""INSERT INTO {DB_TABELA_NOVA}
                           (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (nome, carac_str, artista, titulo, album, genero, capa_album, link_youtube)
                )
                conn.commit()
                return int(cur.lastrowid)

def carregar_matriz() -> tuple[np.ndarray, list[int], list[dict]]:
    with conectar() as conn:
        with conn.cursor() as cur:
            expected = int(EXPECTED_FEATURE_LENGTH or 0)
            if expected > 0:
                cur.execute(f"""
                    SELECT id, nome, artista, titulo, link_youtube, caracteristicas
                    FROM {DB_TABELA_NOVA}
                    WHERE (LENGTH(caracteristicas) - LENGTH(REPLACE(caracteristicas, ',', ''))) + 1 = %s
                """, (expected,))
            else:
                cur.execute(f"""
                    SELECT id, nome, artista, titulo, link_youtube, caracteristicas
                    FROM {DB_TABELA_NOVA}
                """)
            rows = cur.fetchall()
    if not rows:
        raise RuntimeError("Banco vazio (tabela nova). Ingerir algumas músicas primeiro.")
    X, ids, metas = [], [], []
    for rid, nome, artista, titulo, link, carac in rows:
        vec = np.fromstring(carac, sep=',', dtype=float)
        vec = _pad_or_trim(vec, int(EXPECTED_FEATURE_LENGTH or 0))
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

def listar(limit: int = 20) -> list[dict]:
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, titulo, artista, nome, link_youtube, criado_em
                FROM {DB_TABELA_NOVA} ORDER BY id DESC LIMIT %s
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
