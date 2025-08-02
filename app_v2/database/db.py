# database/db.py

import mysql.connector
from config import DB_CONFIG, DB_TABLE_NAME, EXPECTED_FEATURE_LENGTH

def conectar():
    """Estabelece uma conexão com o banco de dados MySQL."""
    return mysql.connector.connect(**DB_CONFIG)

def criar_tabela():
    """Cria a tabela de músicas se ela não existir."""
    try:
        conn = conectar()
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
                    capa_album VARCHAR(255),
                    link_youtube VARCHAR(255),
                    UNIQUE (titulo, artista)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """)
            conn.commit()
            print(f"✅ Tabela '{DB_TABLE_NAME}' verificada/criada com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao criar a tabela '{DB_TABLE_NAME}': {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

def musica_existe(titulo, artista):
    """Verifica se uma música já existe na tabela do banco de dados."""
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {DB_TABLE_NAME} WHERE titulo = %s AND artista = %s", (titulo, artista))
            return cur.fetchone() is not None

def inserir_musica(nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube):
    """Insere as informações de uma música e suas características no banco de dados."""
    if len(caracteristicas) != EXPECTED_FEATURE_LENGTH:
        print(f"❌ Erro: Características da música '{nome}' têm tamanho incorreto ({len(caracteristicas)}). Esperado: {EXPECTED_FEATURE_LENGTH}. Não será inserida na '{DB_TABLE_NAME}'.")
        return

    if musica_existe(titulo, artista):
        print(f"⚠️ Música '{titulo}' de '{artista}' já cadastrada em '{DB_TABLE_NAME}'.\n🔗 Link: '{link_youtube}'")
        return

    carac_str = ",".join(map(str, caracteristicas))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {DB_TABLE_NAME} (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                nome,
                carac_str,
                artista or "Não Encontrado",
                titulo or "Não Encontrado",
                album or "Não Encontrado",
                genero or "Não Encontrado",
                capa_album or "Não Encontrado",
                link_youtube or "Não Encontrado"
            ))
            conn.commit()
            print(f"✅ Inserida no banco '{DB_TABLE_NAME}': {titulo} - {artista}")
            print(f"🔗 Link da Música: {link_youtube}")

def carregar_musicas():
    """Carrega todas as músicas com características consistentes do banco de dados."""
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT nome, caracteristicas, artista, titulo, link_youtube FROM {DB_TABLE_NAME} WHERE LENGTH(caracteristicas) - LENGTH(REPLACE(caracteristicas, ',', '')) + 1 = {EXPECTED_FEATURE_LENGTH}")
            rows = cur.fetchall()
    return [(nome, list(map(float, carac.split(","))), artista, titulo, link) for nome, carac, artista, titulo, link in rows]