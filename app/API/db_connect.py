import psycopg2

# Configurações de conexão
USER = "sa"
PASSWORD = "fft$i8p68"
DB = "fftapp"
HOST = "postgres-db"  # ou IP do servidor PostgreSQL
PORT = "5432"        # padrão do PostgreSQL

# Conectando ao banco
def conectar_e_criar():
    try:
        # Conectar ao banco
        conn = psycopg2.connect(
            dbname=DB,
            user=USER,
            password=PASSWORD,
            host=HOST,
            port=PORT
        )

        cur = conn.cursor()

        # Criar tabela
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tb_teste (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL
            );
        """)
        conn.commit()

        # Inserir dado
        cur.execute("INSERT INTO tb_teste (nome) VALUES (%s)", ("Teste",))
        conn.commit()

        # Fechar conexões
        cur.close()
        conn.close()

        return {
            "status": "sucesso",
            "mensagem": "Conexão estabelecida, tabela criada e dado inserido com sucesso."
        }

    except Exception as e:
        return {
            "status": "erro",
            "mensagem": str(e)
        }
