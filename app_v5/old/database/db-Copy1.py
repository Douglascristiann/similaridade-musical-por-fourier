# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any, Union

import numpy as np
import mysql.connector

# -------------------------------------------------------------
# Configurações (preservadas do projeto)
# -------------------------------------------------------------
from app_v5.config import DB_CONFIG, DB_TABLE_NAME

# -------------------------------------------------------------
# Conexão
# -------------------------------------------------------------
def conectar():
    """Estabelece conexão com o banco de dados."""
    return mysql.connector.connect(**DB_CONFIG)

# =============================================================
# 1) OPERAÇÕES NO CATÁLOGO DE MÚSICAS (tb_musicas)
# =============================================================

def _select_id_by_nome(nome: str) -> Optional[int]:
    """Busca o ID de uma música pelo nome do arquivo."""
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
    link_spotify: Optional[str],
) -> int:
    """Insere uma nova música ou atualiza uma existente com base no nome do arquivo."""
    vec = np.asarray(caracteristicas, dtype=float).ravel()
    vec_str = ",".join(str(float(x)) for x in vec.tolist())

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
            return int(rid) if rid else -1

def listar(limit: int = 20) -> List[Dict[str, Any]]:
    """Lista as últimas músicas inseridas no banco."""
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
    Carrega todas as músicas e seus metadados do banco para a memória.
    Esta é a versão corrigida que garante o carregamento de todos os campos.
    """
    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            # Seleciona todos os campos de metadados necessários do banco
            cur.execute(f"""
                SELECT id, nome, caracteristicas, titulo, artista, album, genero, capa_album, link_youtube, link_spotify
                  FROM {DB_TABLE_NAME}
                 WHERE caracteristicas IS NOT NULL AND caracteristicas <> ''
            """)
            rows = cur.fetchall()

    ids, metas, feats = [], [], []
    for r in rows:
        try:
            # Converte a string de características em um vetor numérico
            vec = [float(x) for x in (r.get("caracteristicas") or "").split(",") if x]
            if not vec:
                continue
            
            feats.append(vec)
            ids.append(int(r["id"]))
            
            # Monta o dicionário de metadados, garantindo que todos os campos sejam incluídos
            metas.append({
                "nome": r.get("nome"),
                "titulo": r.get("titulo"),
                "artista": r.get("artista"),
                "album": r.get("album"),
                "genero": r.get("genero"), # Campo crucial que estava faltando
                "capa_album": r.get("capa_album"),
                "caminho": (r.get("link_spotify") or r.get("link_youtube")),
                "spotify": r.get("link_spotify"),
                "youtube": r.get("link_youtube"),
            })
        except (ValueError, TypeError):
            # Ignora linhas com dados corrompidos
            continue

    if not feats:
        return np.array([]), [], []
    
    return np.asarray(feats, dtype=float), ids, metas

# =============================================================
# 2) OPERAÇÕES DE USUÁRIOS E NPS
# =============================================================

TB_USUARIOS = "tb_usuarios"
TB_NPS      = "tb_nps"
TB_MUSICAS  = "tb_musicas"

def _tbl_exists(cur, table: str) -> bool:
    cur.execute("SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (DB_CONFIG.get("database"), table))
    return cur.fetchone() is not None

def _get_pk_col_and_type(cur, table: str) -> Tuple[str, str]:
    cur.execute("SELECT COLUMN_NAME, COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_KEY='PRI'", (DB_CONFIG.get("database"), table))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Tabela '{table}' não tem PK detectável.")
    return row[0], row[1]

def _index_exists(cur, table: str, index_name: str) -> bool:
    cur.execute(f"SHOW INDEX FROM `{table}` WHERE Key_name=%s", (index_name,))
    return cur.fetchone() is not None

def _fk_exists(cur, table: str, fk_name: str) -> bool:
    cur.execute("SELECT 1 FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s", (DB_CONFIG.get("database"), table, fk_name))
    return cur.fetchone() is not None

def _ensure_fk(cur, table: str, fk_name: str, col: str, ref_table: str, ref_col: str):
    if _fk_exists(cur, table, fk_name):
        return
    if not _index_exists(cur, table, f"idx_{col}"):
        try:
            cur.execute(f"CREATE INDEX `idx_{col}` ON `{table}`(`{col}`)")
        except Exception:
            pass
    cur.execute(f"ALTER TABLE `{table}` ADD CONSTRAINT `{fk_name}` FOREIGN KEY (`{col}`) REFERENCES `{ref_table}`(`{ref_col}`) ON DELETE CASCADE ON UPDATE CASCADE")

def criar_tabela() -> None:
    """Cria as tabelas de usuários e NPS se não existirem."""
    with conectar() as conn:
        with conn.cursor() as cur:
            if not _tbl_exists(cur, TB_MUSICAS):
                raise RuntimeError(f"Tabela de músicas '{TB_MUSICAS}' não encontrada.")
            if not _tbl_exists(cur, TB_USUARIOS):
                cur.execute(f"""
                    CREATE TABLE `{TB_USUARIOS}` (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        fullname VARCHAR(255) NULL,
                        email VARCHAR(255) NOT NULL,
                        streaming_pref VARCHAR(64) NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY `uk_users_email` (`email`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)
            mus_pk, mus_type = _get_pk_col_and_type(cur, TB_MUSICAS)
            if not _tbl_exists(cur, TB_NPS):
                cur.execute(f"""
                    CREATE TABLE `{TB_NPS}` (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        musica_id {mus_type} NOT NULL,
                        rating INT NOT NULL,
                        channel VARCHAR(32) NULL,
                        input_ref TEXT NULL,
                        result_json LONGTEXT NULL,
                        alg_vencedor VARCHAR(32) NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY `uk_user_music` (`user_id`,`musica_id`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)
            _ensure_fk(cur, TB_NPS, "fk_nps_user", "user_id", TB_USUARIOS, "id")
            _ensure_fk(cur, TB_NPS, "fk_nps_music", "musica_id", TB_MUSICAS, mus_pk)
            conn.commit()

def upsert_usuario(_ignored_user_id: Optional[int], fullname: Optional[str], email: Optional[str], streaming_pref: Optional[str] = None) -> int:
    if not email:
        raise ValueError("email é obrigatório.")
    with conectar() as conn:
        with conn.cursor() as cur:
            criar_tabela()
            cur.execute(f"SELECT id FROM `{TB_USUARIOS}` WHERE email=%s LIMIT 1", (email,))
            row = cur.fetchone()
            if row:
                pk = int(row[0])
                # A lógica de update pode ser adicionada aqui se necessário
                return pk
            cur.execute(f"INSERT INTO `{TB_USUARIOS}` (fullname, email, streaming_pref) VALUES (%s, %s, %s)", (fullname, email, streaming_pref))
            conn.commit()
            return int(cur.lastrowid)

def _resolve_user_pk(cur, user_ref: Union[int, str]) -> int:
    if isinstance(user_ref, int) or (isinstance(user_ref, str) and user_ref.isdigit()):
        cur.execute(f"SELECT id FROM `{TB_USUARIOS}` WHERE id=%s", (int(user_ref),))
    elif isinstance(user_ref, str) and "@" in user_ref:
        cur.execute(f"SELECT id FROM `{TB_USUARIOS}` WHERE email=%s", (user_ref,))
    else:
        raise ValueError("Referência de usuário inválida.")
    r = cur.fetchone()
    if not r:
        raise ValueError("Usuário não encontrado.")
    return int(r[0])

def upsert_nps(
    user_ref: Union[int, str],
    musica_id: int,
    rating: int,
    channel: Optional[str] = None,
    input_ref: Optional[str] = None,
    result_json: Optional[str] = None,
    alg_vencedor: Optional[str] = None
) -> Optional[int]:
    if not 1 <= int(rating) <= 5:
        raise ValueError("rating deve estar entre 1 e 5")
    with conectar() as conn:
        with conn.cursor() as cur:
            criar_tabela()
            fk_user = _resolve_user_pk(cur, user_ref)
            cur.execute(f"SELECT 1 FROM `{TB_MUSICAS}` WHERE id=%s", (musica_id,))
            if not cur.fetchone():
                raise ValueError(f"Música id={musica_id} não existe.")
            cur.execute(
                f"""
                INSERT INTO `{TB_NPS}` (user_id, musica_id, rating, channel, input_ref, result_json, alg_vencedor)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    rating=VALUES(rating), channel=VALUES(channel), input_ref=VALUES(input_ref),
                    result_json=VALUES(result_json), alg_vencedor=COALESCE(VALUES(alg_vencedor), alg_vencedor),
                    updated_at=CURRENT_TIMESTAMP
                """,
                (fk_user, musica_id, int(rating), channel, input_ref, result_json, alg_vencedor)
            )
            conn.commit()
            cur.execute(f"SELECT id FROM `{TB_NPS}` WHERE user_id=%s AND musica_id=%s", (fk_user, musica_id))
            row = cur.fetchone()
            return int(row[0]) if row else None

def update_nps_algoritmo(user_ref: Union[int, str], musica_id: int, choice: str) -> None:
    with conectar() as conn:
        with conn.cursor() as cur:
            fk_user = _resolve_user_pk(cur, user_ref)
            cur.execute(f"UPDATE `{TB_NPS}` SET alg_vencedor=%s, updated_at=CURRENT_TIMESTAMP WHERE user_id=%s AND musica_id=%s", (choice, fk_user, int(musica_id)))
            conn.commit()