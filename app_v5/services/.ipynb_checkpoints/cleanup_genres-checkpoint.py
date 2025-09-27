# app_v5/services/cleanup_genres.py
import sys
from pathlib import Path
import ast
import logging

# Adiciona o diretório raiz do projeto ao path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app_v5.database.db import conectar, DB_TABLE_NAME, _formatar_generos_para_db

log = logging.getLogger("GenreCleanup")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def limpar_generos_db():
    log.info("Iniciando limpeza de gêneros no banco de dados...")
    db_conn = None
    update_cursor = None
    try:
        db_conn = conectar()
        cursor = db_conn.cursor(dictionary=True)
        
        log.info(f"Buscando gêneros na tabela {DB_TABLE_NAME}...")
        # Busca apenas os gêneros que começam com '[' para otimizar
        cursor.execute(f"SELECT id, genero FROM {DB_TABLE_NAME} WHERE genero LIKE '[%'")
        
        musicas_para_limpar = cursor.fetchall()
        total = len(musicas_para_limpar)
        
        if total == 0:
            log.info("Nenhum gênero no formato de lista encontrado para limpar. Tudo certo!")
            return

        log.info(f"{total} registros de gênero para formatar.")
        
        update_cursor = db_conn.cursor()
        for musica in musicas_para_limpar:
            id_musica = musica['id']
            genero_antigo = musica['genero']
            genero_novo = _formatar_generos_para_db(genero_antigo)
            
            if genero_novo != genero_antigo:
                log.info(f"ID {id_musica}: '{genero_antigo}' -> '{genero_novo}'")
                update_cursor.execute(
                    f"UPDATE {DB_TABLE_NAME} SET genero = %s WHERE id = %s",
                    (genero_novo, id_musica)
                )
        
        db_conn.commit()
        log.info(f"Limpeza concluída. {update_cursor.rowcount} registros foram atualizados.")

    except Exception as e:
        log.error(f"Ocorreu um erro durante a limpeza: {e}", exc_info=True)
        if db_conn:
            db_conn.rollback()
    finally:
        if db_conn and db_conn.is_connected():
            cursor.close()
            if update_cursor:
                update_cursor.close()
            db_conn.close()
            log.info("Conexão com o banco de dados fechada.")

if __name__ == "__main__":
    limpar_generos_db()