# API/db/setup.py

import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    "user": "root",
    "password": "managerffti8p68",
    "host": "db",
    "port": 3306,
    "database": "dbmusicadata"
}

DB_TABLE_NAME = "tb_musicas_v3"

def conectar():
    """Estabelece uma conexão com o banco de dados MySQL."""
    return mysql.connector.connect(**DB_CONFIG)

def criar_tabela():
    """Cria a tabela de músicas no banco de dados, se ela não existir."""
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

def verificar_conexao_e_criar_tabela():
    """Verifica a conexão e tenta criar a tabela no banco de dados."""
    try:
        print("🔌 Conectando ao banco de dados...")
        criar_tabela()
        print("✅ Tabela verificada/criada com sucesso.")
    except Error as e:
        print(f"❌ [MySQL Error] Falha na conexão: {e}")
    except Exception as e:
        print(f"❌ [Erro] Erro geral no banco de dados: {e}")

