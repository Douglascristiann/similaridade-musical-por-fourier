# app_v5/database/db.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any, Union

import numpy as np
import mysql.connector
import json

# +++ NOVO: para normalização (acentos/caixa/espaços)
import unicodedata, re

# ... (mantenha as funções conectar, _select_id_by_nome, upsert_musica, e listar como estão)
from app_v5.config import DB_CONFIG, DB_TABLE_NAME

def conectar():
    """Estabelece conexão com o banco de dados."""
    return mysql.connector.connect(**DB_CONFIG)

def _select_id_by_nome(nome: str) -> Optional[int]:
    """Busca o ID de uma música pelo nome do arquivo."""
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM {DB_TABLE_NAME} WHERE nome=%s LIMIT 1", (nome,))
            r = cur.fetchone()
            return int(r[0]) if r else None

# =========================================================
# NOVO: Normalização e checagem de duplicidade SEM schema
# =========================================================

_WS_RE = re.compile(r"\s+", flags=re.UNICODE)

def _strip_accents_lower(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = _WS_RE.sub(" ", s)
    return s

def _norm_or_none(v: Optional[str]) -> Optional[str]:
    if v is None: 
        return None
    v2 = str(v).strip()
    if not v2:
        return None
    return _strip_accents_lower(v2)

def musica_existe_por_meta(artist: Optional[str], title: Optional[str], album: Optional[str]) -> Optional[int]:
    """
    Procura música existente com mesmo (artista, título, álbum) ignorando acentos/caixa/espaços.
    Retorna id se existir; senão, None. Não altera o schema do banco.
    """
    na = _norm_or_none(artist)
    nt = _norm_or_none(title)
    nal = _norm_or_none(album)
    if not (na and nt and nal):
        return None

    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            # 1) Tenta collation acento-insensível (MySQL 8+)
            try:
                cur.execute(
                    f"""
                    SELECT id, artista, titulo, album
                      FROM {DB_TABLE_NAME}
                     WHERE artista IS NOT NULL AND titulo IS NOT NULL AND album IS NOT NULL
                       AND artista COLLATE utf8mb4_0900_ai_ci = %s
                       AND titulo  COLLATE utf8mb4_0900_ai_ci = %s
                       AND album   COLLATE utf8mb4_0900_ai_ci = %s
                     LIMIT 5
                    """,
                    (artist, title, album)
                )
                rows = cur.fetchall()
            except Exception:
                # 2) Fallback: case-insensitive; validação fina no Python
                cur.execute(
                    f"""
                    SELECT id, artista, titulo, album
                      FROM {DB_TABLE_NAME}
                     WHERE artista IS NOT NULL AND titulo IS NOT NULL AND album IS NOT NULL
                       AND LOWER(artista) = LOWER(%s)
                       AND LOWER(titulo)  = LOWER(%s)
                       AND LOWER(album)   = LOWER(%s)
                     LIMIT 20
                    """,
                    (artist or "", title or "", album or "")
                )
                rows = cur.fetchall()

    # 3) Confirma normalizando em Python (remove acentos/colapsa espaços)
    for r in rows or []:
        ra = _norm_or_none(r.get("artista"))
        rt = _norm_or_none(r.get("titulo"))
        ral = _norm_or_none(r.get("album"))
        if (ra == na) and (rt == nt) and (ral == nal):
            return int(r["id"])
    return None

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

# ===== CORREÇÃO IMPORTANTE APLICADA AQUI =====
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

# ... (mantenha o restante do arquivo, incluindo as operações de Usuários e NPS, como está)
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

# =============================================================
# 3) FUNÇÕES PARA O SCRIPT DE BACKFILL
# =============================================================

def fetch_musicas_sem_metadata(db_conn=None):
    """
    Busca músicas sem gênero ou álbum no banco de dados.
    """
    conn = db_conn if db_conn else conectar()
    try:
        cursor = conn.cursor(dictionary=True)
        query = f"""
            SELECT id, titulo, artista FROM {DB_TABLE_NAME} 
            WHERE genero IS NULL OR genero = '' OR genero = 'Desconhecido' OR album IS NULL OR album = ''
        """
        cursor.execute(query)
        return cursor.fetchall()
    finally:
        if not db_conn:
            conn.close()

def update_metadata_musica(id_musica, novo_titulo, novo_artista, novo_album, novo_genero, nova_capa, novo_link_spotify, db_conn=None):
    """
    Atualiza os metadados de uma música específica pelo seu ID.
    """
    conn = db_conn if db_conn else conectar()
    try:
        cursor = conn.cursor()
        
        # --- LINHA MODIFICADA ---
        # Usa a nova função para formatar a lista de gêneros corretamente
        genero_str = _formatar_generos_para_db(novo_genero)
        
        query = f"""
            UPDATE {DB_TABLE_NAME} SET
                titulo = %s,
                artista = %s,
                album = %s,
                genero = %s,
                capa_album = %s,
                link_spotify = %s
            WHERE id = %s
        """
        cursor.execute(query, (novo_titulo, novo_artista, novo_album, genero_str, nova_capa, novo_link_spotify, id_musica))
        conn.commit()
    finally:
        if not db_conn:
            conn.close()

#------------------------------------------------------------------------------------------
import ast

def _formatar_generos_para_db(genero_input: any) -> str | None:
    """
    Converte uma lista de gêneros ou a representação em string de uma lista
    para uma única string separada por vírgulas.
    """
    if genero_input is None:
        return None

    lista_generos = genero_input
    if isinstance(genero_input, str) and genero_input.startswith('[') and genero_input.endswith(']'):
        try:
            lista_generos = ast.literal_eval(genero_input)
        except (ValueError, SyntaxError):
            return genero_input.strip("[]").replace("'", "").replace('"', '')

    if isinstance(lista_generos, list):
        return ", ".join(map(str, lista_generos))

    return str(lista_generos)
