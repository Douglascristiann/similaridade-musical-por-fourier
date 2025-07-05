import mysql.connector

# Configurações de conexão
USER = "root"
PASSWORD = "managerffti8p68"
DB = "dbmusicadata"
HOST = "db"   # ou IP do servidor MySQL
PORT = "3306"       # padrão do MySQL

# Conectando ao banco
def conectar_e_criar():
    try:
        # Conectar ao banco
        conn = mysql.connector.connect(
            user=USER,
            password=PASSWORD,
            host=HOST,
            port=PORT,
            database=DB
        )

        cur = conn.cursor()

        # Criar tabela
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tb_teste (
                id INT AUTO_INCREMENT PRIMARY KEY,
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