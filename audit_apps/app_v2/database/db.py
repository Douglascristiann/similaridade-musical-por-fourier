# database/db.py

import mysql.connector
from config import DB_CONFIG, DB_TABLE_NAME, EXPECTED_FEATURE_LENGTH

def conectar():
    print("[DB] Conectando ao banco…")
    return mysql.connector.connect(**DB_CONFIG)

def criar_tabela():
    print(f"[DB] Criando/verificando tabela {DB_TABLE_NAME}…")
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
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
    print(f"[DB] Tabela {DB_TABLE_NAME} pronta.")

def musica_existe(nome):
    print(f"[DB] Verificando existência de '{nome}'…")
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {DB_TABLE_NAME} WHERE nome = %s", (nome,))
            exists = cur.fetchone() is not None
    print(f"[DB] Existe? {'Sim' if exists else 'Não'}")
    return exists

def inserir_musica(nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube):
    print(f"[DB] Inserindo música '{nome}'…")
    if len(caracteristicas) != EXPECTED_FEATURE_LENGTH:
        print(f"❌ Tamanho inválido: {len(caracteristicas)} (esperado {EXPECTED_FEATURE_LENGTH}).")
        return
    if musica_existe(nome):
        print(f"⚠️ '{nome}' já cadastrado, pulando.")
        return
    carac_str = ",".join(map(str, caracteristicas))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {DB_TABLE_NAME}
                (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (nome, carac_str, artista, titulo, album, genero, capa_album, link_youtube))
        conn.commit()
    print(f"[DB] '{nome}' inserido com sucesso.")

def carregar_musicas():
    print(f"[DB] Carregando músicas de {DB_TABLE_NAME}…")
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT nome, caracteristicas, artista, titulo, link_youtube
                FROM {DB_TABLE_NAME}
                WHERE (LENGTH(caracteristicas) - LENGTH(REPLACE(caracteristicas, ',', ''))) + 1 = {EXPECTED_FEATURE_LENGTH}
            """)
            rows = cur.fetchall()
    musicas = [(nome, list(map(float, carac.split(","))), art, tit, lnk)
               for nome, carac, art, tit, lnk in rows]
    print(f"[DB] {len(musicas)} músicas carregadas.")
    return musicas
