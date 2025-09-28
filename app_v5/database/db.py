# app_v5/database/db.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any, Union

import numpy as np
import mysql.connector
import json
import logging

# Normalização (acentos/caixa/espaços) para duplicidade
import unicodedata, re, ast

from app_v5.config import DB_CONFIG, DB_TABLE_NAME

log = logging.getLogger("FourierMatch:DB")

def conectar():
    """Estabelece conexão com o banco de dados."""
    return mysql.connector.connect(**DB_CONFIG)

# =========================================================
# Normalização e checagem de duplicidade (sem alterar schema)
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

def _select_id_by_nome(nome: str) -> Optional[int]:
    """Busca o ID de uma música pelo nome do arquivo."""
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM {DB_TABLE_NAME} WHERE nome=%s LIMIT 1", (nome,))
            r = cur.fetchone()
            return int(r[0]) if r else None

def musica_existe_por_meta(artist: Optional[str], title: Optional[str], album: Optional[str]) -> Optional[int]:
    """
    Procura música existente com mesmo (artista, título, álbum) ignorando acentos/caixa/espaços.
    Retorna id se existir; senão, None.
    """
    na = _norm_or_none(artist)
    nt = _norm_or_none(title)
    nal = _norm_or_none(album)
    if not (na and nt and nal):
        return None

    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
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
    """Insere nova música ou atualiza existente com base no nome do arquivo."""
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
    """
    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(f"""
                SELECT id, nome, caracteristicas, titulo, artista, album, genero, capa_album, link_youtube, link_spotify
                  FROM {DB_TABLE_NAME}
                 WHERE caracteristicas IS NOT NULL AND caracteristicas <> ''
            """)
            rows = cur.fetchall()

    ids, metas, feats = [], [], []
    for r in rows:
        try:
            vec = [float(x) for x in (r.get("caracteristicas") or "").split(",") if x]
            if not vec:
                continue
            feats.append(vec)
            ids.append(int(r["id"]))
            metas.append({
                "nome": r.get("nome"),
                "titulo": r.get("titulo"),
                "artista": r.get("artista"),
                "album": r.get("album"),
                "genero": r.get("genero"),
                "capa_album": r.get("capa_album"),
                "caminho": (r.get("link_spotify") or r.get("link_youtube")),
                "spotify": r.get("link_spotify"),
                "youtube": r.get("link_youtube"),
            })
        except (ValueError, TypeError):
            continue

    if not feats:
        return np.array([]), [], []
    return np.asarray(feats, dtype=float), ids, metas

# =============================================================
# 2) OPERAÇÕES DE USUÁRIOS E NPS (existentes) + MIGRAÇÃO USER TEST
# =============================================================
TB_USUARIOS = "tb_usuarios"
TB_NPS      = "tb_nps"
TB_MUSICAS  = "tb_musicas"

def _tbl_exists(cur, table: str) -> bool:
    cur.execute("SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                (DB_CONFIG.get("database"), table))
    return cur.fetchone() is not None

def _get_pk_col_and_type(cur, table: str) -> Tuple[str, str]:
    cur.execute("SELECT COLUMN_NAME, COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_KEY='PRI'",
                (DB_CONFIG.get("database"), table))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Tabela '{table}' não tem PK detectável.")
    return row[0], row[1]

def _index_exists(cur, table: str, index_name: str) -> bool:
    cur.execute(f"SHOW INDEX FROM `{table}` WHERE Key_name=%s", (index_name,))
    return cur.fetchone() is not None

def _fk_exists(cur, table: str, fk_name: str) -> bool:
    cur.execute("SELECT 1 FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s",
                (DB_CONFIG.get("database"), table, fk_name))
    return cur.fetchone() is not None

def _ensure_fk(cur, table: str, fk_name: str, col: str, ref_table: str, ref_col: str):
    if _fk_exists(cur, table, fk_name):
        return
    if not _index_exists(cur, table, f"idx_{col}"):
        try:
            cur.execute(f"CREATE INDEX `idx_{col}` ON `{table}`(`{col}`)")
        except Exception:
            pass
    cur.execute(f"ALTER TABLE `{table}` "
                f"ADD CONSTRAINT `{fk_name}` FOREIGN KEY (`{col}`) "
                f"REFERENCES `{ref_table}`(`{ref_col}`) "
                f"ON DELETE CASCADE ON UPDATE CASCADE")

def _ensure_user_test_columns(cur):
    """
    Garante as colunas extras em tb_nps para armazenar:
    - pares (event_type='pair'), com nota binária e Likert;
    - NPS final da sessão (event_type='nps').
    """
    def _col_exists(table: str, col: str) -> bool:
        cur.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
            (DB_CONFIG.get("database"), table, col)
        )
        return cur.fetchone() is not None

    def _add_col(sql: str):
        try:
            cur.execute(sql)
        except Exception:
            # se já existir / sem permissão, silencie para seguir
            pass

    # Definições de coluna (sem IF NOT EXISTS)
    if not _col_exists("tb_nps", "event_type"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN event_type ENUM('pair','nps') DEFAULT 'pair'")
    if not _col_exists("tb_nps", "participant_id"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN participant_id VARCHAR(64) NULL")
    if not _col_exists("tb_nps", "seed_id"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN seed_id INT NULL")
    if not _col_exists("tb_nps", "seed_title"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN seed_title VARCHAR(255) NULL")
    if not _col_exists("tb_nps", "cand_id"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN cand_id INT NULL")
    if not _col_exists("tb_nps", "cand_title"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN cand_title VARCHAR(255) NULL")
    if not _col_exists("tb_nps", "in_topk"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN in_topk TINYINT(1) NULL")
    if not _col_exists("tb_nps", "user_sim"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN user_sim TINYINT(1) NULL")
    if not _col_exists("tb_nps", "user_sim_score"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN user_sim_score TINYINT NULL")
    if not _col_exists("tb_nps", "nps_score"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN nps_score TINYINT NULL")
    if not _col_exists("tb_nps", "nps_comment"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN nps_comment TEXT NULL")
    if not _col_exists("tb_nps", "created_at"):
        _add_col("ALTER TABLE `tb_nps` ADD COLUMN created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP")


def criar_tabela() -> None:
    """Cria as tabelas de usuários e NPS se não existirem + garante colunas do user test."""
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

            # 🔸 garante as colunas do estudo com usuário no MESMO tb_nps
            _ensure_user_test_columns(cur)

            conn.commit()

def _resolve_user_pk(cur, user_ref: Union[int, str]) -> int:
    """
    Resolve o PK do usuário a partir de id inteiro ou email (string com '@').
    """
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

def upsert_usuario(_ignored_user_id: Optional[int], fullname: Optional[str], email: Optional[str], streaming_pref: Optional[str] = None) -> int:
    if not email:
        raise ValueError("email é obrigatório.")
    with conectar() as conn:
        with conn.cursor() as cur:
            criar_tabela()
            cur.execute(f"SELECT id FROM `{TB_USUARIOS}` WHERE email=%s LIMIT 1", (email,))
            row = cur.fetchone()
            if row:
                return int(row[0])
            cur.execute(f"INSERT INTO `{TB_USUARIOS}` (fullname, email, streaming_pref) VALUES (%s, %s, %s)",
                        (fullname, email, streaming_pref))
            conn.commit()
            return int(cur.lastrowid)

def upsert_nps(
    user_ref: Union[int, str],
    musica_id: int,
    rating: int,
    channel: Optional[str] = None,
    input_ref: Optional[str] = None,
    result_json: Optional[str] = None,
    alg_vencedor: Optional[str] = None
) -> Optional[int]:
    # Mantém a regra existente (0..5). Ajuste se desejar 0..10 aqui também.
    if not 0 <= int(rating) <= 5:
        raise ValueError("rating deve estar entre 0 e 5")
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
            cur.execute(f"UPDATE `{TB_NPS}` SET alg_vencedor=%s, updated_at=CURRENT_TIMESTAMP "
                        f"WHERE user_id=%s AND musica_id=%s", (choice, fk_user, int(musica_id)))
            conn.commit()

# =============================================================
# 3) FUNÇÕES do Teste com Usuário (lista cega)
# =============================================================
def fetch_random_negatives(qtd: int, excluir_ids: List[int]) -> List[Tuple[int, str, str, Optional[str], Optional[str]]]:
    """
    Retorna até `qtd` registros aleatórios fora de `excluir_ids`.
    Colunas: id, titulo/nome, artista, link_spotify, link_youtube.
    """
    if qtd <= 0:
        return []
    placeholders = ",".join(["%s"] * len(excluir_ids)) if excluir_ids else "NULL"
    where_exclude = f"WHERE id NOT IN ({placeholders})" if excluir_ids else ""
    sql = f"""
        SELECT id,
               COALESCE(titulo, nome) AS titulo,
               COALESCE(artista, '') AS artista,
               COALESCE(link_spotify, '') AS link_spotify,
               COALESCE(link_youtube, '') AS link_youtube
        FROM {DB_TABLE_NAME}
        {where_exclude}
        ORDER BY RAND()
        LIMIT %s
    """
    with conectar() as conn:
        with conn.cursor(dictionary=True) as cur:
            params: Tuple[Any, ...] = tuple(excluir_ids) + (qtd,) if excluir_ids else (qtd,)
            cur.execute(sql, params)
            rows = cur.fetchall()
            out: List[Tuple[int, str, str, Optional[str], Optional[str]]] = []
            for r in rows:
                out.append((
                    int(r["id"]),
                    r.get("titulo") or "",
                    r.get("artista") or "",
                    r.get("link_spotify") or None,
                    r.get("link_youtube") or None
                ))
            return out

def inserir_user_test_pair(
    participant_id: str,
    seed_id: Optional[int],
    seed_title: Optional[str],
    cand_id: int,
    cand_title: str,
    in_topk: int,
    user_sim: int,
) -> int:
    """
    Registra um julgamento de par seed×candidata na tb_nps e retorna o ID da linha.
    Usa event_type='pair'.
    """
    with conectar() as conn:
        with conn.cursor() as cur:
            criar_tabela()
            sql = """
                INSERT INTO tb_nps
                    (event_type, participant_id, seed_id, seed_title,
                     cand_id, cand_title, in_topk, user_sim, created_at)
                VALUES ('pair', %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """
            cur.execute(sql, (
                participant_id, seed_id, seed_title,
                cand_id, cand_title, in_topk, user_sim
            ))
            conn.commit()
            return int(cur.lastrowid)
def update_user_test_pair_score(row_id: int, user_sim_score: int) -> None:
    """
    Atualiza a mesma linha do par com a nota 1–5 de similaridade.
    """
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tb_nps SET user_sim_score=%s WHERE id=%s AND event_type='pair'",
                (int(user_sim_score), int(row_id))
            )
            conn.commit()


def inserir_user_test_nps(
    participant_id: str,
    seed_id: Optional[int],
    seed_title: Optional[str],
    nps_score: int,
    nps_comment: Optional[str]
) -> None:
    """
    Registra o NPS final da sessão do teste com usuários (0..10).
    Usa event_type='nps'.
    """
    with conectar() as conn:
        with conn.cursor() as cur:
            criar_tabela()
            sql = """
                INSERT INTO tb_nps
                    (event_type, participant_id, seed_id, seed_title,
                     nps_score, nps_comment)
                VALUES ('nps', %s, %s, %s, %s, %s)
            """
            cur.execute(sql, (
                participant_id, seed_id, seed_title, int(nps_score), nps_comment
            ))
            conn.commit()

# =============================================================
# 4) BACKFILL de metadados (mantido)
# =============================================================
def fetch_musicas_sem_metadata(db_conn=None):
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

def update_metadata_musica(id_musica: int, novo_titulo: Optional[str], novo_artista: Optional[str],
                           novo_album: Optional[str], novo_genero: Optional[Any], nova_capa: Optional[str],
                           novo_link_spotify: Optional[str], db_conn=None):
    conn = db_conn if db_conn else conectar()
    try:
        cursor = conn.cursor()
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

def _formatar_generos_para_db(genero_input: Any) -> Optional[str]:
    """
    Converte uma lista de gêneros ou a representação em string de uma lista
    para uma única string separada por vírgulas. Compatível com Python < 3.10.
    """
    if genero_input is None:
        return None

    lista_generos = genero_input

    # Se vier como string parecendo uma lista: "[...]", tenta fazer parse seguro
    if isinstance(genero_input, str) and genero_input.strip().startswith('[') and genero_input.strip().endswith(']'):
        try:
            lista_generos = ast.literal_eval(genero_input)
        except (ValueError, SyntaxError):
            # fallback: remove colchetes e aspas sem quebrar
            s = genero_input.strip("[]").replace("'", "").replace('"', '').strip()
            return s or None

    # Se for lista (de verdade), junta com vírgula
    if isinstance(lista_generos, list):
        return ", ".join(str(x).strip() for x in lista_generos if str(x).strip())

    # Qualquer outro tipo: retorna como string simples
    s = str(lista_generos).strip()
    return s if s else None
