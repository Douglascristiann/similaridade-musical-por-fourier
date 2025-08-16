from __future__ import annotations
import os, sys
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import mysql.connector
import numpy as np

# === Importa config preferindo a do pacote (app_v4_new/config.py) ===
PKG_DIR  = Path(__file__).resolve().parents[1]  # .../app_v4_new
ROOT_DIR = PKG_DIR.parent                       # raiz do repo
for p in (ROOT_DIR, PKG_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from app_v4_new.config import DB_CONFIG, EXPECTED_FEATURE_LENGTH  # v5 mantém aqui
except Exception:
    from config import DB_CONFIG, EXPECTED_FEATURE_LENGTH  # fallback se existir na raiz

# === Nome da tabela principal (mantém compat. com v5) ===
DB_TABELA_NOVA  = os.getenv("DB_TABELA_NOVA", "tb_musicas_fourier")
DB_TABELA_USUARIOS = os.getenv("DB_TABELA_USUARIOS", "tb_usuarios")
DB_TABELA_NPS      = os.getenv("DB_TABELA_NPS", "tb_nps")

def conectar():
    print(f"[DB] Conectando ao banco {DB_CONFIG.get('host')}:{DB_CONFIG.get('port')}/{DB_CONFIG.get('database')}…")
    return mysql.connector.connect(**DB_CONFIG)

# ------------------ DDL ------------------
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
            channel VARCHAR(32) NULL,           -- 'youtube' | 'audio' | etc.
            input_ref TEXT NULL,                -- url ou breve referência
            result_json LONGTEXT NULL,          -- payload opcional do resultado
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
    print(f"[DB] Criando/verificando tabelas…")
    with conectar() as conn:
        with conn.cursor() as cur:
            _criar_tabela_musicas(cur)
            _criar_tabela_usuarios(cur)
            _criar_tabela_nps(cur)
        conn.commit()
    print(f"[DB] Tabelas prontas.")

# ------------------ util ------------------
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

# ------------------ músicas ------------------
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

# ------------------ usuários ------------------
def upsert_usuario(user_id: int, fullname: str, email: str) -> None:
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {DB_TABELA_USUARIOS} WHERE user_id=%s", (user_id,))
            if cur.fetchone():
                cur.execute(
                    f"UPDATE {DB_TABELA_USUARIOS} SET fullname=%s, email=%s WHERE user_id=%s",
                    (fullname, email, user_id)
                )
            else:
                cur.execute(
                    f"INSERT INTO {DB_TABELA_USUARIOS}(user_id, fullname, email) VALUES (%s,%s,%s)",
                    (user_id, fullname, email)
                )
        conn.commit()

# ------------------ NPS (user × música) ------------------
def upsert_nps(
    user_id: int,
    musica_id: int,
    rating: int,
    channel: str | None = None,
    input_ref: str | None = None,
    result_json: str | None = None
) -> int:
    r = int(rating)
    if r < 1 or r > 5:
        raise ValueError("rating deve estar em 1..5")
    with conectar() as conn:
        with conn.cursor() as cur:
            # FKs
            cur.execute(f"SELECT 1 FROM {DB_TABELA_USUARIOS} WHERE user_id=%s", (user_id,))
            if not cur.fetchone():
                raise ValueError(f"Usuário {user_id} não existe em {DB_TABELA_USUARIOS}.")
            cur.execute(f"SELECT 1 FROM {DB_TABELA_NOVA} WHERE id=%s", (musica_id,))
            if not cur.fetchone():
                raise ValueError(f"Música id={musica_id} não existe em {DB_TABELA_NOVA}.")

            cur.execute(
                f"""
                INSERT INTO {DB_TABELA_NPS}
                    (user_id, musica_id, rating, channel, input_ref, result_json)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    rating=VALUES(rating),
                    channel=VALUES(channel),
                    input_ref=VALUES(input_ref),
                    result_json=VALUES(result_json),
                    updated_at=CURRENT_TIMESTAMP
                """,
                (user_id, musica_id, r, channel, input_ref, result_json)
            )
            conn.commit()
            cur.execute(
                f"SELECT id FROM {DB_TABELA_NPS} WHERE user_id=%s AND musica_id=%s",
                (user_id, musica_id)
            )
            return int(cur.fetchone()[0])
