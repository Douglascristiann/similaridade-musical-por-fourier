# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import json
from typing import List, Tuple, Optional, Dict, Any

import numpy as np
import mysql.connector

# --------------------------------------------------------------------
# Configurações existentes do projeto (preservadas do seu db.py atual)
# --------------------------------------------------------------------
from app_v5.config import DB_CONFIG, DB_TABLE_NAME  # DB_TABLE_NAME = tabela de catálogo (não alterada aqui)

# --------------------------------------------------------------------
# Conexão
# --------------------------------------------------------------------
def conectar():
    return mysql.connector.connect(**DB_CONFIG)

# ====================================================================
# 1) FUNÇÕES DO CATÁLOGO (preservadas) - NÃO mexem na tb_musicas
# ====================================================================

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
    link_spotify: Optional[str],  # compat com sua versão anterior
) -> int:
    """
    Insere se não existir; caso exista, atualiza.
    OBS: opera em DB_TABLE_NAME (tabela de catálogo já existente) — NÃO cria/ALTER essa tabela aqui.
    """
    vec_str = ",".join(str(float(x)) for x in caracteristicas.tolist())
    with conectar() as conn:
        with conn.cursor() as cur:
            rid = _select_id_by_nome(nome)
            if rid is None:
                cur.execute(f"""
                    INSERT INTO {DB_TABLE_NAME}
                    (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube, link_spotify)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (nome, vec_str, artista, titulo, album, genero, capa_album, link_youtube, link_spotify))
                conn.commit()
                rid = cur.lastrowid
            else:
                cur.execute(f"""
                    UPDATE {DB_TABLE_NAME}
                       SET caracteristicas=%s,
                           artista=%s, titulo=%s, album=%s, genero=%s, capa_album=%s,
                           link_youtube=%s, link_spotify=%s
                     WHERE id=%s
                """, (vec_str, artista, titulo, album, genero, capa_album, link_youtube, link_spotify, rid))
                conn.commit()
            return int(rid)

def listar(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Lista últimos itens do catálogo (DB_TABLE_NAME).
    """
    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(f"""
                SELECT id, titulo, artista,
                       COALESCE(link_spotify, link_youtube, '') AS caminho,
                       created_at
                  FROM {DB_TABLE_NAME}
              ORDER BY id DESC
                 LIMIT %s
            """, (int(limit),))
            return [dict(r) for r in cur.fetchall()]

def carregar_matriz() -> Tuple[np.ndarray, List[int], List[Dict[str, Any]]]:
    """
    Carrega matriz de características do catálogo (DB_TABLE_NAME).
    """
    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(f"""
                SELECT id, nome, caracteristicas, titulo, artista, link_youtube, link_spotify
                  FROM {DB_TABLE_NAME}
                 WHERE caracteristicas IS NOT NULL AND caracteristicas <> ''
            """)
            rows = cur.fetchall()

    ids, metas, feats = [], [], []
    for r in rows:
        try:
            vec = [float(x) for x in (r["caracteristicas"] or "").split(",") if x != ""]
            if not vec:
                continue
            feats.append(vec)
            ids.append(int(r["id"]))
            metas.append({
                "nome": r["nome"],
                "titulo": r.get("titulo"),
                "artista": r.get("artista"),
                "caminho": (r.get("link_spotify") or r.get("link_youtube")),
                "spotify": r.get("link_spotify"),
                "youtube": r.get("link_youtube"),
            })
        except Exception:
            continue

    if not feats:
        return np.zeros((0, 1)), [], []

    X = np.asarray(feats, dtype=float)
    return X, ids, metas

# ====================================================================
# 2) TABELAS NOVAS: tb_usuarios e tb_nps (FK -> tb_usuarios, tb_musicas)
#    NÃO tocamos em tb_musicas (plural) conforme sua exigência.
# ====================================================================

TB_USUARIOS = os.getenv("DB_TABELA_USUARIOS", "tb_usuarios")
TB_NPS      = os.getenv("DB_TABELA_NPS",      "tb_nps")
TB_MUSICAS  = os.getenv("DB_TABELA_MUSICAS",  "tb_musicas")  # tabela-alvo da FK (já existente no seu projeto)

# ---------- helpers de schema (somente INFORMATION_SCHEMA; não altera tb_musicas) ----------
def _tbl_exists(cur, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
        (DB_CONFIG.get("database"), table)
    )
    return cur.fetchone() is not None

def _get_pk_col_and_type(cur, table: str) -> Tuple[str, str]:
    cur.execute(
        """
        SELECT COLUMN_NAME, COLUMN_TYPE
          FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_KEY='PRI'
        """,
        (DB_CONFIG.get("database"), table)
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Tabela '{table}' não tem PK detectável.")
    return row[0], row[1]

def _col_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1
          FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (DB_CONFIG.get("database"), table, column)
    )
    return cur.fetchone() is not None

def _index_exists(cur, table: str, index_name: str) -> bool:
    cur.execute(f"SHOW INDEX FROM `{table}` WHERE Key_name=%s", (index_name,))
    return cur.fetchone() is not None

def _fk_exists(cur, table: str, fk_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
          FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
         WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s
        """,
        (DB_CONFIG.get("database"), table, fk_name)
    )
    return cur.fetchone() is not None

def _ensure_fk(cur, table: str, fk_name: str, col: str, ref_table: str, ref_col: str):
    if _fk_exists(cur, table, fk_name):
        return
    if not _index_exists(cur, table, f"idx_{col}"):
        try:
            cur.execute(f"CREATE INDEX `idx_{col}` ON `{table}`(`{col}`)")
        except Exception:
            pass
    cur.execute(
        f"""ALTER TABLE `{table}`
            ADD CONSTRAINT `{fk_name}`
            FOREIGN KEY (`{col}`) REFERENCES `{ref_table}`(`{ref_col}`)
            ON DELETE CASCADE ON UPDATE CASCADE"""
    )

# ---------- criação das tabelas novas ----------
def criar_tabela() -> None:
    """
    Cria SOMENTE:
      - tb_usuarios
      - tb_nps (com FKs para tb_usuarios(id) e tb_musicas(id))
    Não cria/ALTERA 'tb_musicas'.
    """
    with conectar() as conn:
        with conn.cursor() as cur:
            # 1) tb_usuarios
            if not _tbl_exists(cur, TB_USUARIOS):
                cur.execute(f"""
                    CREATE TABLE `{TB_USUARIOS}` (
                        id BIGINT PRIMARY KEY,                 -- ex.: ID do Telegram
                        fullname        VARCHAR(255) NULL,
                        email           VARCHAR(255) NULL,
                        streaming_pref  VARCHAR(64)  NULL,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

            # 2) Garantir que tb_musicas exista (apenas valida; NÃO cria/ALTERA)
            if not _tbl_exists(cur, TB_MUSICAS):
                raise RuntimeError(f"Tabela de músicas '{TB_MUSICAS}' não encontrada. "
                                   f"Crie/popule-a com seu pipeline antes de usar o bot.")

            # PKs e tipos das tabelas referenciadas
            mus_pk, mus_type = _get_pk_col_and_type(cur, TB_MUSICAS)
            usr_pk, usr_type = _get_pk_col_and_type(cur, TB_USUARIOS)

            # 3) tb_nps
            if not _tbl_exists(cur, TB_NPS):
                cur.execute(f"""
                    CREATE TABLE `{TB_NPS}` (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id   {usr_type} NOT NULL,
                        musica_id {mus_type}  NOT NULL,
                        rating INT NOT NULL,               -- 1..5
                        channel VARCHAR(32) NULL,          -- "youtube" | "audio_local" | "snippet" | ...
                        input_ref TEXT NULL,               -- link/arquivo informado
                        result_json LONGTEXT NULL,         -- payload da recomendação para auditoria
                        alg_vencedor VARCHAR(32) NULL,     -- "A" | "B" | "="
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY `uk_user_music` (`user_id`,`musica_id`),
                        INDEX `idx_user` (`user_id`),
                        INDEX `idx_music` (`musica_id`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

            # 4) FKs (idempotentes). NÃO tocam nas tabelas referenciadas.
            _ensure_fk(cur, TB_NPS, "fk_nps_user",  "user_id",   TB_USUARIOS, usr_pk)
            _ensure_fk(cur, TB_NPS, "fk_nps_music", "musica_id", TB_MUSICAS,  mus_pk)

        conn.commit()

# ---------- APIs de usuários e NPS ----------
def upsert_usuario(user_id: int, fullname: str, email: str, streaming_pref: str = "other") -> None:
    """
    Insere/atualiza o usuário em tb_usuarios (PK=id).
    """
    criar_tabela()  # idempotente
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO `{TB_USUARIOS}` (id, fullname, email, streaming_pref)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE fullname=VALUES(fullname), email=VALUES(email), streaming_pref=VALUES(streaming_pref)
            """, (int(user_id), fullname, email, streaming_pref))
        conn.commit()

def get_usuario(user_id: int) -> Optional[Dict[str, Any]]:
    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(f"SELECT * FROM `{TB_USUARIOS}` WHERE id=%s", (int(user_id),))
            return cur.fetchone()

def upsert_nps(
    user_id: int,
    musica_id: int,
    rating: int,
    *,
    channel: Optional[str] = None,
    input_ref: Optional[str] = None,
    result_json: Optional[str] = None,
    alg_vencedor: Optional[str] = None
) -> int:
    """
    Cria/atualiza (UNIQUE user_id+musica_id) o registro em tb_nps.
    NÃO altera tb_musicas; exige que o 'musica_id' exista lá.
    """
    criar_tabela()  # garante tb_usuarios e tb_nps com FKs
    r = int(rating)
    if r < 1 or r > 5:
        raise ValueError("rating deve estar em 1..5")

    with conectar() as conn:
        with conn.cursor() as cur:
            # valida existência das FKs (sem tocar nas tabelas)
            cur.execute(f"SELECT 1 FROM `{TB_USUARIOS}` WHERE id=%s", (int(user_id),))
            if not cur.fetchone():
                raise ValueError(f"Usuário id={user_id} não existe em {TB_USUARIOS}.")
            cur.execute(f"SELECT 1 FROM `{TB_MUSICAS}` WHERE id=%s", (int(musica_id),))
            if not cur.fetchone():
                raise ValueError(f"Música id={musica_id} não existe em {TB_MUSICAS}.")

            cur.execute(
                f"""
                INSERT INTO `{TB_NPS}` (user_id, musica_id, rating, channel, input_ref, result_json, alg_vencedor)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    rating=VALUES(rating),
                    channel=VALUES(channel),
                    input_ref=VALUES(input_ref),
                    result_json=VALUES(result_json),
                    alg_vencedor=COALESCE(VALUES(alg_vencedor), alg_vencedor),
                    updated_at=CURRENT_TIMESTAMP
                """,
                (int(user_id), int(musica_id), r, channel, input_ref, result_json, alg_vencedor)
            )
            conn.commit()
            cur.execute(f"SELECT id FROM `{TB_NPS}` WHERE user_id=%s AND musica_id=%s", (int(user_id), int(musica_id)))
            row = cur.fetchone()
            return int(row[0]) if row else 0

def update_nps_algoritmo(user_id: int, musica_id: int, choice: str) -> None:
    """
    Atualiza 'alg_vencedor' do NPS mais recente do par (user_id, musica_id).
    """
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""UPDATE `{TB_NPS}`
                       SET alg_vencedor=%s, updated_at=CURRENT_TIMESTAMP
                     WHERE user_id=%s AND musica_id=%s""",
                (choice, int(user_id), int(musica_id))
            )
        conn.commit()
