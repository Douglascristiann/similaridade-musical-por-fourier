# app_v5/database/db.py
from __future__ import annotations
import os, sys
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import mysql.connector
import numpy as np

# --------------------------------------------------------------------
#  Config: prioriza app_v5/config.py; fallback para config.py na raiz.
# --------------------------------------------------------------------
PKG_DIR  = Path(__file__).resolve().parents[1]  # .../app_v5
ROOT_DIR = PKG_DIR.parent
for p in (ROOT_DIR, PKG_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from app_v5.config import DB_CONFIG, EXPECTED_FEATURE_LENGTH  # padrão do projeto v5
except Exception:
    from config import DB_CONFIG, EXPECTED_FEATURE_LENGTH  # fallback (se existir na raiz)

# --------------------------------------------------------------------
#  Tabelas (podem ser alteradas por variáveis de ambiente)
# --------------------------------------------------------------------
DB_TABELA_NOVA      = os.getenv("DB_TABELA_NOVA", "tb_musicas_fourier")
DB_TABELA_USUARIOS  = os.getenv("DB_TABELA_USUARIOS", "tb_usuarios")
DB_TABELA_NPS       = os.getenv("DB_TABELA_NPS", "tb_nps")

# --------------------------------------------------------------------
#  Conexão
# --------------------------------------------------------------------
def conectar():
    """Retorna uma conexão mysql.connector já configurada (DB_CONFIG)."""
    return mysql.connector.connect(**DB_CONFIG)

# --------------------------------------------------------------------
#  Helpers DDL
# --------------------------------------------------------------------
def _ensure_column(cur, table: str, column: str, column_sql: str) -> None:
    """Adiciona coluna se não existir (migração leve e idempotente)."""
    dbname = DB_CONFIG.get("database")
    cur.execute(
        """
        SELECT COUNT(*)
          FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (dbname, table, column)
    )
    if int(cur.fetchone()[0]) == 0:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")

# --------------------------------------------------------------------
#  DDL
# --------------------------------------------------------------------
def _criar_tabela_musicas(cur) -> None:
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

def _criar_tabela_usuarios(cur) -> None:
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {DB_TABELA_USUARIOS} (
            user_id BIGINT PRIMARY KEY,
            fullname VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            streaming_pref VARCHAR(32) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

def _criar_tabela_nps(cur) -> None:
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {DB_TABELA_NPS} (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            user_id  BIGINT NOT NULL,
            musica_id INT   NOT NULL,
            rating INT NOT NULL,                -- 1..5
            channel VARCHAR(32) NULL,           -- 'youtube' | 'audio' | 'snippet' | etc.
            input_ref TEXT NULL,                -- url ou breve referência
            result_json LONGTEXT NULL,          -- payload opcional do resultado
            alg_vencedor VARCHAR(32) NULL,      -- 'spotify' | 'ytmusic' | 'deezer' | 'apple' | 'tidal' | 'soundcloud' | 'sistema' | 'other'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
            CONSTRAINT fk_nps_user  FOREIGN KEY (user_id)  REFERENCES {DB_TABELA_USUARIOS}(user_id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT fk_nps_music FOREIGN KEY (musica_id) REFERENCES {DB_TABELA_NOVA}(id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            UNIQUE KEY uk_user_music (user_id, musica_id),
            INDEX idx_music (musica_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

def criar_tabela():
    """Cria as tabelas necessárias e garante colunas novas em bases antigas."""
    conn = conectar()
    try:
        cur = conn.cursor()
        _criar_tabela_musicas(cur)
        _criar_tabela_usuarios(cur)
        _criar_tabela_nps(cur)

        # migração leve: garante colunas se a base for antiga
        _ensure_column(cur, DB_TABELA_USUARIOS, "streaming_pref", "streaming_pref VARCHAR(32) NULL")
        _ensure_column(cur, DB_TABELA_NPS, "alg_vencedor", "alg_vencedor VARCHAR(32) NULL")
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

# --------------------------------------------------------------------
#  Utils de vetor
# --------------------------------------------------------------------
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

# --------------------------------------------------------------------
#  Músicas
# --------------------------------------------------------------------
def upsert_musica(
    nome: str,
    caracteristicas: np.ndarray,
    artista: Optional[str],
    titulo: Optional[str],
    album: Optional[str] = None,
    genero: Optional[str] = None,
    capa_album: Optional[str] = None,
    link_youtube: Optional[str] = None
) -> int:
    """Insere ou atualiza música; retorna o id."""
    v = _pad_or_trim(caracteristicas, int(EXPECTED_FEATURE_LENGTH or 0))
    carac_str = ",".join(f"{x:.9g}" for x in v)

    conn = conectar()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT id FROM {DB_TABELA_NOVA} WHERE nome=%s", (nome,))
        row = cur.fetchone()
        if row:
            rid = int(row[0])
            cur.execute(
                f"""UPDATE {DB_TABELA_NOVA}
                       SET caracteristicas=%s, artista=%s, titulo=%s, album=%s, genero=%s, capa_album=%s, link_youtube=%s
                     WHERE id=%s""",
                (carac_str, artista, titulo, album, genero, capa_album, link_youtube, rid)
            )
            conn.commit()
            return rid
        cur.execute(
            f"""INSERT INTO {DB_TABELA_NOVA}
                   (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (nome, carac_str, artista, titulo, album, genero, capa_album, link_youtube)
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def carregar_matriz() -> tuple[np.ndarray, List[int], List[dict]]:
    """
    Retorna (X, ids, metas):
      - X: matriz (n_samples, n_features)
      - ids: lista de ids
      - metas: [{id, titulo, artista, caminho, nome}, ...]
    """
    conn = conectar()
    try:
        cur = conn.cursor()
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
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    if not rows:
        raise RuntimeError("Banco vazio (tabela de músicas). Ingerir algumas faixas primeiro.")

    X, ids, metas = [], [], []
    for rid, nome, artista, titulo, link, carac in rows:
        vec = np.fromstring(carac or "", sep=',', dtype=float)
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

def listar(limit: int = 20) -> List[dict]:
    conn = conectar()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT id, titulo, artista, nome, link_youtube, criado_em
              FROM {DB_TABELA_NOVA}
          ORDER BY id DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    out: List[dict] = []
    for rid, titulo, artista, nome, link, dt in rows:
        out.append({
            "id": int(rid),
            "titulo": titulo or nome,
            "artista": artista or "",
            "caminho": link or nome,
            "created_at": str(dt),
        })
    return out

# --------------------------------------------------------------------
#  Usuários (bot)
# --------------------------------------------------------------------
def upsert_usuario(user_id: int, fullname: str, email: str, streaming_pref: Optional[str] = None) -> None:
    conn = conectar()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM {DB_TABELA_USUARIOS} WHERE user_id=%s", (user_id,))
        if cur.fetchone():
            cur.execute(
                f"""UPDATE {DB_TABELA_USUARIOS}
                       SET fullname=%s, email=%s, streaming_pref=COALESCE(%s, streaming_pref)
                     WHERE user_id=%s""",
                (fullname, email, streaming_pref, user_id)
            )
        else:
            cur.execute(
                f"""INSERT INTO {DB_TABELA_USUARIOS}(user_id, fullname, email, streaming_pref)
                    VALUES (%s,%s,%s,%s)""",
                (user_id, fullname, email, streaming_pref)
            )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def get_usuario(user_id: int) -> Optional[Dict[str, Any]]:
    conn = conectar()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"SELECT user_id, fullname, email, streaming_pref, created_at FROM {DB_TABELA_USUARIOS} WHERE user_id=%s",
            (user_id,)
        )
        row = cur.fetchone()
        return row or None
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

# --------------------------------------------------------------------
#  NPS (usuário × música)
# --------------------------------------------------------------------
def upsert_nps(
    user_id: int,
    musica_id: int,
    rating: int,
    channel: Optional[str] = None,
    input_ref: Optional[str] = None,
    result_json: Optional[str] = None,
    alg_vencedor: Optional[str] = None
) -> int:
    """Insere/atualiza NPS (UNIQUE user_id+musica_id) e retorna o id do registro."""
    r = int(rating)
    if r < 1 or r > 5:
        raise ValueError("rating deve estar em 1..5")

    conn = conectar()
    try:
        cur = conn.cursor()
        # Garantir FKs
        cur.execute(f"SELECT 1 FROM {DB_TABELA_USUARIOS} WHERE user_id=%s", (user_id,))
        if not cur.fetchone():
            raise ValueError(f"Usuário {user_id} não existe em {DB_TABELA_USUARIOS}.")
        cur.execute(f"SELECT 1 FROM {DB_TABELA_NOVA} WHERE id=%s", (musica_id,))
        if not cur.fetchone():
            raise ValueError(f"Música id={musica_id} não existe em {DB_TABELA_NOVA}.")

        cur.execute(
            f"""
            INSERT INTO {DB_TABELA_NPS}
                (user_id, musica_id, rating, channel, input_ref, result_json, alg_vencedor)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                rating=VALUES(rating),
                channel=VALUES(channel),
                input_ref=VALUES(input_ref),
                result_json=VALUES(result_json),
                alg_vencedor=COALESCE(VALUES(alg_vencedor), alg_vencedor),
                updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, musica_id, r, channel, input_ref, result_json, alg_vencedor)
        )
        conn.commit()

        cur.execute(
            f"SELECT id FROM {DB_TABELA_NPS} WHERE user_id=%s AND musica_id=%s",
            (user_id, musica_id)
        )
        return int(cur.fetchone()[0])
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def update_nps_algoritmo(user_id: int, musica_id: int, alg_vencedor: str) -> None:
    """Atualiza apenas o campo 'alg_vencedor' do NPS."""
    conn = conectar()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE {DB_TABELA_NPS}
                   SET alg_vencedor=%s, updated_at=CURRENT_TIMESTAMP
                 WHERE user_id=%s AND musica_id=%s""",
            (alg_vencedor, user_id, musica_id)
        )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()
